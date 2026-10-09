#!/usr/bin/env python
import os
import uuid
import logging
import hashlib

import boto3
import requests
import numpy as np
from flask_cors import CORS
from flask.logging import default_handler
from flask import Flask, request, jsonify, redirect, send_from_directory
from fits2image.conversions import fits_to_jpg
from fits_align.ident import make_transforms
from fits_align.align import affineremap
from astropy.io import fits
from astropy.nddata import Cutout2D, NoOverlapError
from PIL import Image, ImageDraw

from thumbservice.common import settings, get_temp_filename_prefix


app = Flask(__name__, static_folder='static')
CORS(app)

class RequestFormatter(logging.Formatter):
    def format(self, record):
        record.url = request.url
        return super().format(record)

formatter = RequestFormatter('[%(asctime)s] %(levelname)s in %(module)s for %(url)s: %(message)s')
default_handler.setFormatter(formatter)


class ThumbnailAppException(Exception):
    status_code = 500

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        result = dict(self.payload or ())
        result['message'] = self.message
        return result


@app.errorhandler(ThumbnailAppException)
def handle_thumbnail_app_exception(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


def get_response(url, params=None, headers=None, timeout=10):
    response = None
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        message = 'Timeout while accessing resource'
        payload = {'url': url, 'params': params}
        raise ThumbnailAppException(message, status_code=504, payload=payload)
    except requests.RequestException:
        status_code = getattr(response, 'status_code', None)
        payload = {}
        message = 'Got error response'
        if status_code is None or 500 <= status_code < 600:
            status_code = 502
        elif status_code == 404:
            message = 'Not found'
        else:
            try:
                payload['response'] = response.json()
            except:
                pass
        raise ThumbnailAppException(message, status_code=status_code, payload=payload)
    return response


def can_generate_thumbnail_on(frame, request):
    frame_has_required_validation_keys = all([key in frame.keys() for key in settings.REQUIRED_FRAME_VALIDATION_KEYS])
    if not frame_has_required_validation_keys:
        return {'result': False, 'reason': 'Cannot generate thumbnail for given frame'}

    configuration_type = frame.get('configuration_type').upper()
    request_id = frame.get('request_id')
    is_color_request = request.args.get('color', 'false') == 'true'
    is_fits_file = any([frame.get('filename').endswith(ext) for ext in ['.fits', '.fits.fz']])

    if configuration_type not in settings.VALID_CONFIGURATION_TYPES:
        return {'result': False, 'reason': f'Cannot generate thumbnail for configuration_type={configuration_type}'}

    if is_color_request and not request_id:
        return {'result': False, 'reason': 'Cannot generate color thumbnail for a frame that does not have a request'}

    if is_color_request and configuration_type not in settings.VALID_CONFIGURATION_TYPES_FOR_COLOR_THUMBS:
        return {'result': False, 'reason': f'Cannot generate color thumbnail for configuration_type={configuration_type}'}

    if not is_fits_file:
        return {'result': False, 'reason': 'Cannot generate thumbnail for non FITS-type frame'}

    return {'result': True, 'reason': ''}


def unique_temp_path_start():
    return f'{settings.TMP_DIR}{get_temp_filename_prefix()}{uuid.uuid4().hex}-'


def save_temp_file(frame):
    path = f'{unique_temp_path_start()}{frame["filename"]}'
    with open(path, 'wb') as f:
        f.write(get_response(frame['url'], timeout=60).content)
    return path


def key_for_jpeg(frame_id, **params):
    return f'{frame_id}.{hashlib.blake2b(repr(frozenset(params.items())).encode(), digest_size=20).hexdigest()}.jpg'


def convert_to_jpg(paths, key, **params):
    jpg_path = f'{unique_temp_path_start()}{key}'
    fits_to_jpg(paths, jpg_path, **params)
    return jpg_path


def get_s3_client():
    config = boto3.session.Config(region_name=settings.AWS_DEFAULT_REGION, signature_version='s3v4', s3={'addressing_style': 'virtual'})
    return boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        endpoint_url=settings.STORAGE_URL,
        config=config,
    )


def upload_to_s3(key, jpg_path):
    client = get_s3_client()
    with open(jpg_path, 'rb') as f:
        client.put_object(
            Bucket=settings.AWS_BUCKET,
            Body=f,
            Key=key,
            ContentType='image/jpeg'
        )


def generate_url(key):
    client = get_s3_client()
    return client.generate_presigned_url(
        'get_object',
        ExpiresIn=3600 * 8,
        Params={'Bucket': settings.AWS_BUCKET, 'Key': key}
    )


def key_exists(key):
    client = get_s3_client()
    try:
        client.head_object(Bucket=settings.AWS_BUCKET, Key=key)
        return True
    except:
        return False


def frames_for_requestnum(request_id, request, reduction_level):
    headers = {
        'Authorization': request.headers.get('Authorization')
    }
    params = {'request_id': request_id, 'reduction_level': reduction_level}
    return get_response(f'{settings.ARCHIVE_API_URL}frames/', params=params, headers=headers, timeout=30).json()['results']


def rvb_frames(frames):
    FILTERS_FOR_COLORS = {
        'red': ['R', 'rp'],
        'visual': ['V'],
        'blue': ['B'],
    }
    selected_frames = []
    for color in ['red', 'visual', 'blue']:
        try:
            selected_frames.append(
                next(f for f in frames if f['primary_optical_element'] in FILTERS_FOR_COLORS[color])
            )
        except StopIteration:
            raise ThumbnailAppException('RVB frames not found', status_code=404)
    return selected_frames


def reproject_files(ref_image, images_to_align):
    """Return three aligned images."""
    aligned_images = []
    reprojected_file_list = [ref_image]
    try:
        identifications = make_transforms(ref_image, images_to_align[1:3])
        for id in identifications:
            if id.ok:
                aligned_image = affineremap(id.ukn.filepath, id.trans, outdir=settings.TMP_DIR)
                aligned_images.append(aligned_image)
    except Exception:
        app.logger.warning('Error aligning images, falling back to original image list', exc_info=True)

    # Clean up aligned images if they will not be used
    if len(aligned_images) != 2:
        while len(aligned_images) > 0:
            aligned_image = aligned_images.pop()
            if os.path.exists(aligned_image):
                os.remove(aligned_image)

    reprojected_file_list = reprojected_file_list + aligned_images
    return reprojected_file_list if len(reprojected_file_list) == 3 else images_to_align


class Paths:
    """Retain all paths set"""
    def __init__(self):
        self._all_paths = set()
        self.paths = []

    def set(self, paths):
        for path in paths:
            self._all_paths.add(path)
        self.paths = paths

    @property
    def all_paths(self):
        return list(self._all_paths)


def generate_thumbnail(frame, request):
    params = {
        'width': int(request.args.get('width', 200)),
        'height': int(request.args.get('height', 200)),
        'label_text': request.args.get('label'),
        'color': request.args.get('color', 'false') != 'false',
        'median': request.args.get('median', 'false') != 'false',
        'percentile': float(request.args.get('percentile', 99.5)),
        'quality': int(request.args.get('quality', 80)),
    }
    key = key_for_jpeg(frame['id'], **params)
    if key_exists(key):
        return generate_url(key)
    # Cfitsio is a bit crappy and can only read data off disk
    jpg_path = None
    paths = Paths()
    try:
        if not params['color']:
            paths.set([save_temp_file(frame)])
        else:
            # Color thumbnails can only be generated on rlevel 91 images
            reqnum_frames = frames_for_requestnum(frame['request_id'], request, reduction_level=91)
            paths.set([save_temp_file(frame) for frame in rvb_frames(reqnum_frames)])
            paths.set(reproject_files(paths.paths[0], paths.paths))
        jpg_path = convert_to_jpg(paths.paths, key, **params)
        upload_to_s3(key, jpg_path)
    finally:
        # Cleanup actions
        if jpg_path and os.path.exists(jpg_path):
            os.remove(jpg_path)
        for path in paths.all_paths:
            if os.path.exists(path):
                os.remove(path)
    return generate_url(key)


def getsky(data):
    """
    Determine the sky parameters for a FITS data extension.

    data -- array holding the image data
    """

    # maximum number of interations for mean,std loop
    maxiter = 30

    # maximum number of data points to sample
    maxsample = 10000

    # size of the array
    ny, nx = data.shape

    # how many sampels should we take?
    if data.size > maxsample:
        nsample = maxsample
    else:
        nsample = data.size

    # create sample indicies
    xs = np.random.uniform(low=0, high=nx, size=nsample).astype('L')
    ys = np.random.uniform(low=0, high=ny, size=nsample).astype('L')

    # sample the data
    sample = data[ys, xs].copy()
    sample = sample.reshape(nsample)

    # determine the clipped mean and standard deviation
    mean = sample.mean()
    std = sample.std()
    oldsize = 0
    niter = 0
    while oldsize != sample.size and niter < maxiter:
        niter += 1
        oldsize = sample.size
        wok = (sample < mean + 3 * std)
        sample = sample[wok]
        wok = (sample > mean - 3 * std)
        sample = sample[wok]
        mean = sample.mean()
        std = sample.std()

    return mean, std


def make_depth_256(data, spansig=4):
    """
    Convert image to 256 colors.

    data is an image array

    Scale image data so that black is (sky - sig) and white is (sky + 5
    * sig). If optional sky and sig keywords are not set, they are
    calculated using getsky(data)

   """
    depth = 256
    zerosig = 0
    data = data.astype(np.float64)
    sky, sig = getsky(data)

    # set the color range
    zero = sky + zerosig * sig
    span = spansig * sig

    # scale the data to the requested display values
    # greys
    data -= zero
    data *= (depth - 1) / span

    # black
    w = data < 0
    data[w] = 0

    # white
    w = data > (depth - 1)
    data[w] = (depth - 1)

    data += 256 - depth

    return data


def generate_cutout_thumbnail(frame, request):
    params = {
        'x': int(request.args.get('x', 0)),
        'y': int(request.args.get('y', 0)),
        'width': int(request.args.get('width', 200)),
        'height': int(request.args.get('height', 200)),
        'zoom': float(request.args.get('zoom', 1.0)),
        'sigma': float(request.args.get('sigma', 4.0)),
        'ticks': request.args.get('ticks', 'false') != 'false',
    }
    key = key_for_jpeg(frame['id'], **params)
    if key_exists(key):
        return generate_url(key)

    fits_path = None
    jpg_path = None
    try:
        x = params['x']
        y = params['y']
        width = params['width']
        height = params['height']
        zoom = params['zoom']
        sigma = params['sigma']
        ticks = params['ticks']

        # x, y, width, height validation is left up to astropy

        if zoom <= 0:
            raise ThumbnailAppException("zoom must be greater than 0", status_code=400)

        if sigma <= 0:
            raise ThumbnailAppException("sigma must be greater than 0", status_code=400)

        fits_path = save_temp_file(frame)
        with fits.open(fits_path) as hdul:
            try:
                cutout = Cutout2D(hdul[0].data, position=(x, y), size=(width, height), mode='trim')
            except NoOverlapError:
                raise ThumbnailAppException("x, y, width, height combo leads to no overlapping region", status_code=400)

            color_corrected_cutout = make_depth_256(cutout, sigma)

            im = Image.fromarray(color_corrected_cutout.astype(np.uint8), mode='L')

            if zoom < 1.0:
                # shrink image
                filt = Image.Resampling.LANCZOS
            else:
                # grow image
                filt = Image.Resampling.NEAREST

            # resize the image
            nx, ny = im.size
            im = im.resize((int(nx * zoom), int(ny * zoom)), filt)

            # now flip/rotate the image as appropiate
            im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert('RGB')

            if ticks:
                xoff = -0.5
                yoff = 1.0

                cutoutx, cutouty = cutout.input_position_cutout
                x_new = int(round(cutoutx + xoff * zoom))
                y_new = int(round(cutouty + yoff * zoom))

                draw = ImageDraw.Draw(im)
                draw.line((x_new,y_new+7,x_new,y_new+25), fill='white')
                draw.line((x_new-7,y_new,x_new-25,y_new), fill='white')

            jpg_path = f'{unique_temp_path_start()}{key}'
            im.save(jpg_path, "JPEG")

        upload_to_s3(key, jpg_path)
    finally:
        # Cleanup actions
        if jpg_path and os.path.exists(jpg_path):
            os.remove(jpg_path)

        if fits_path and os.path.exists(fits_path):
            os.remove(fits_path)

    return generate_url(key)


def handle_response(frame, request):
    can_generate_thumbnail_on_frame = can_generate_thumbnail_on(frame, request)
    if not can_generate_thumbnail_on_frame['result']:
        raise ThumbnailAppException(can_generate_thumbnail_on_frame['reason'], status_code=400)

    url = generate_thumbnail(frame, request)
    if request.args.get('image'):
        return redirect(url)
    else:
        return jsonify({'url': url, 'propid': frame['proposal_id']})


def handle_cutout_response(frame, request):
    can_generate_thumbnail_on_frame = can_generate_thumbnail_on(frame, request)
    if not can_generate_thumbnail_on_frame['result']:
        raise ThumbnailAppException(can_generate_thumbnail_on_frame['reason'], status_code=400)

    url = generate_cutout_thumbnail(frame, request)
    if request.args.get('image'):
        return redirect(url)
    else:
        return jsonify({'url': url})


@app.route('/<frame_basename>/')
def bn_thumbnail(frame_basename):
    headers = {
        'Authorization': request.headers.get('Authorization')
    }
    params = {'basename_exact': frame_basename}
    frames = get_response(f'{settings.ARCHIVE_API_URL}frames/', params=params, headers=headers).json()

    if not frames['count'] == 1:
        raise ThumbnailAppException('Not found', status_code=404)

    return handle_response(frames['results'][0], request)


@app.route('/cutout/<fname_basename>/')
def cutout(frame_basename):
    headers = {
        'Authorization': request.headers.get('Authorization')
    }
    params = {'basename_exact': frame_basename}
    frames = get_response(f'{settings.ARCHIVE_API_URL}frames/', params=params, headers=headers).json()

    if not frames['count'] == 1:
        raise ThumbnailAppException('Not found', status_code=404)

    return handle_cutout_response(frames['results'][0], request)


@app.route('/<int:frame_id>/')
def thumbnail(frame_id):
    headers = {
        'Authorization': request.headers.get('Authorization')
    }
    frame = get_response(f'{settings.ARCHIVE_API_URL}frames/{frame_id}/', headers=headers).json()

    return handle_response(frame, request)


@app.route('/favicon.ico')
def favicon():
    return redirect('https://cdn.lco.global/mainstyle/img/favicon.ico')


@app.route('/robots.txt')
def robots():
    return send_from_directory(app.static_folder, 'robots.txt')


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path):
    return ((
        'Please see the documentation for the thumbnail service at '
        '<a href="https://developers.lco.global">developers.lco.global</a>'
    ))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
