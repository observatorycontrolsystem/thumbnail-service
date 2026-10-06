import os
import logging
import numpy as np
from astropy.io import fits

from PIL import Image

logger = logging.getLogger(__name__)


def get_temp_filename_prefix(pid=None):
    # Common prefix for all files created by a single process. Used to both create
    # files and find files from a given pid to clean up if necessary.
    pid = os.getpid() if pid is None else pid
    return f'pid{pid}-'


def rebin(arr, binning):
    # Reduce resolution of data array to help with identifying planets
    # make sure the array is an integer number of our binning
    xlim = arr.shape[0] - arr.shape[0] % binning
    ylim = arr.shape[1] - arr.shape[1] % binning
    new_shape = (int(arr.shape[0]/binning), int(arr.shape[1]/binning))
    shape = (new_shape[0], arr.shape[0] // new_shape[0],
             new_shape[1], arr.shape[1] // new_shape[1])
    return arr[0:xlim,0:ylim].reshape(shape).mean(-1).mean(1)

def find_planet(data):
    # Find the planet in the image to perform an approximate align and crop
    binning = 3
    rebinned = rebin(data, binning)
    max_coord = np.unravel_index(np.argmax(rebinned),rebinned.shape)

    # xw, yw = scale_coordinates(max_coord[0], max_coord[1], width, height)
    x1, x2 = binning*max_coord[0]-300, binning*max_coord[0]+300
    y1, y2 = binning*max_coord[1]-300, binning*max_coord[1]+300
    return data[x1:x2,y1:y2]

def planet_image_data(filename, colour=False):
    # Open the fits file and scale the image appropriately
    with fits.open(filename) as hdul:
        img = hdul['sci'].data
        header = hdul['sci'].header

    # Remove the background glow from scattered light   
    cutoff = 200
    img[img<cutoff] = 0
    
    n = 1.
    
    if colour and (header['FILTER'].lower() == 'h-alpha' or header['FILTER'] == 'V'):
        n = 1.1
        
    if header['object'].lower() == 'saturn':
        planet = 5.
    elif header['object'].lower() == 'jupiter':
        planet = 1.4 
    elif header['object'].lower() == 'mars':
        planet = 5.
    elif header['object'].lower() == 'uranus':
        n = 1.
        planet = 0.5
        if header['FILTER'] == 'B':
            n = 1.5
    else:
        planet = 1.0
    vals = planet*n*np.power(img, 0.5)
    if np.max(vals) > 255:
        # scaled to 8 bit for jpg generation
        vals = vals/np.max(vals)*255
    return vals

def stack_images(images_to_stack):
    rgb_cube = np.dstack(images_to_stack).astype(np.uint8)
    return Image.fromarray(rgb_cube)

def planet_image_to_jpg(filenames, output_path, **params):
    '''
    Create a jpg of planet. If the size is less than 600x600, zoom in on the planet. If not use the full image size.
    Resize the image to the specified height and width.
    '''
    max_size = (params['height'], params['width'])
    if params['height'] <= 600 and params['width'] <= 600:
       zoom = True
    else:
       zoom = False
    if len(filenames) >= 3:
        stack = []
        for filename in filenames:
            data = planet_image_data(filename=filename, colour=True)
            if zoom:
                stack.append(find_planet(data))
            else:
                stack.append(data)
        img = stack_images(stack)
        img.convert('RGB')

    elif len(filenames) == 1:
        data = planet_image_data(filenames[0])
        if zoom:
            data = find_planet(data)
        img = Image.fromarray(data.astype(np.uint8))

    img.thumbnail(max_size)
    img.save(output_path)
    return

class Settings:
    def __init__(self, settings=None):
        self._settings = settings or {}
        self.ARCHIVE_API_URL = self.set_value('ARCHIVE_API_URL', 'http://localhost/', True)
        self.TMP_DIR = self.set_value('TMP_DIR', '/tmp/', True)
        self.AWS_BUCKET = self.set_value('AWS_BUCKET', 'changeme')
        self.AWS_ACCESS_KEY_ID = self.set_value('AWS_ACCESS_KEY_ID', 'changeme')
        self.AWS_SECRET_ACCESS_KEY = self.set_value('AWS_SECRET_ACCESS_KEY', 'changeme')
        self.AWS_DEFAULT_REGION = self.set_value('AWS_DEFAULT_REGION', 'us-west-2')
        self.STORAGE_URL = self.set_value('STORAGE_URL', None)
        self.REQUIRED_FRAME_VALIDATION_KEYS = self.get_tuple_from_environment('REQUIRED_FRAME_VALIDATION_KEYS', 'configuration_type,request_id,filename')
        self.VALID_CONFIGURATION_TYPES = self.get_tuple_from_environment('VALID_CONFIGURATION_TYPES', 'ARC,BIAS,BPM,DARK,DOUBLE,EXPERIMENTAL,EXPOSE,GUIDE,LAMPFLAT,SKYFLAT,SPECTRUM,STANDARD,TARGET,TRAILED')
        self.VALID_CONFIGURATION_TYPES_FOR_COLOR_THUMBS = self.get_tuple_from_environment('VALID_CONFIGURATION_TYPES_FOR_COLOR_THUMBS', 'EXPOSE,STANDARD')

    def set_value(self, env_var, default, must_end_with_slash=False):
        if env_var in self._settings:
            value = self._settings[env_var]
        else:
            value = os.getenv(env_var, default)
        return self.end_with_slash(value) if must_end_with_slash else value

    @staticmethod
    def end_with_slash(path):
        return os.path.join(path, '')

    def get_tuple_from_environment(self, variable_name, default):
        return tuple(os.getenv(variable_name, default).strip(',').replace(' ', '').split(','))

settings = Settings()

