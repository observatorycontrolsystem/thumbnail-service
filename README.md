# Thumbnail service

This is a flask application that generates thumbnails from data stored on an
[OCS Science Archive](https://github.com/observatorycontrolsystem/science-archive).

## Requirements

This script uses amazon S3 to temporarily store images. You'll need a bucket and the
[correct environmental variables](http://boto3.readthedocs.io/en/latest/guide/quickstart.html#configuration)
set.

This script also relies on [fits2image](https://github.com/LCOGT/fits2image). Make sure it is installed
in your virtualenv.

All other dependencies are listed in the pyproject.toml file and can be installed via [poetry](https://python-poetry.org/).

```bash
pip install --upgrade pip
pip install poetry
poetry install
```

`poetry install` will create a virtual environment for you, which will have all requirements installed.

Run the tests with `poetry run pytest thumbservice/tests.py`.

## Configuration

This project can be configured using the following environment variables:

|Environment Variable| Description | Default |
|--------------------|-------------|---------|
| `ARCHIVE_API_URL` | Archive API URL | http://localhost/
| `TMP_DIR` | Temporary directory for image operations | '/tmp/'
| `AWS_BUCKET` | AWS S3 Bucket to store thumbnails | 'changeme'
| `AWS_ACCESS_KEY_ID` | AWS Access Key ID for S3 Bucket | 'changeme'
| `AWS_SECRET_ACCESS_KEY` | AWS Secret Access Key for S3 Bucket | 'changeme'
| `STORAGE_URL` | URL for bucket storage if different than AWS. Defaults to None to connect to AWS S3 | None
| `STORAGE_URL_STYLE` | S3 URL style. Can be 'virtual' or 'path'. | 'virtual'
| `REQUIRED_FRAME_VALIDATION_KEYS` | Keys from Archive API record required in order to create a thumbnail from the FITS image | 'configuration_type,request_id,filename'
| `VALID_CONFIGURATION_TYPES` | Only generate thumbnails from images of these configuration types | 'ARC,BIAS,BPM,DARK,DOUBLE,EXPERIMENTAL,EXPOSE,GUIDE,LAMPFLAT,SKYFLAT,SPECTRUM,STANDARD,TARGET,TRAILED'
| `VALID_CONFIGURATION_TYPES_FOR_COLOR_THUMBS` | Only generate color thumbnails from images of these configuration types | 'EXPOSE,STANDARD'

## Authorization

The API passes through the `Authorization` header to the archive API. You only need to provide
this header if the data you are attempting to get a thumbnail for is proprietary. See the archive
documentation for more details.

## Endpoints

### Full Frame

There are 2 endpoints: `/<frame_id>/` and `/<basename>/` where `frame_id` is the ID of the frame
in the archive, and `basename` is the base part of the filename (no file extension) you wish to make
a thumbnail of. Using the frame_id is faster to return if you happen to know it
ahead of time.

Both endpoints take the following query parameters:

* width
* height
* label
* image

Width and height are in pixels, label will appear as white text in the lower left had corner of the image.

They both **return a url** to the thumbnail file that will be good for 1 week unless the `image` parameter
is supplied which will return an image directly.

### Cutout

Cutouts can be generated using `/cutout/<basename>/`.

It takes the following paramters:

- x: pixel to center cutout around (default: 0)
- y: pixel to center cutout around (default: 0)
- width: in pixels (default: 200)
- height: in pixels (default: 200)
- zoom: grow/shrink the cutout (default: 1)
- sigma: color adjustment scaling factor (default: 4)
- ticks: whether to add a crosshairs (default: false; set to any value to enable)


## Example

[https://thumbnails.lco.global/3863274/?width=500&height=500&label=So%20many%20stars](https://thumbnails.lco.global/3863274/?width=500&height=500&label=So%20many%20stars)

## Development

Setup a mock S3:

```sh
docker run -d --rm -p 9090:9090 -p 9191:9191 -e COM_ADOBE_TESTING_S3MOCK_STORE_INITIAL_BUCKETS=thumbservice --name thumbservice-mock-s3 adobe/s3mock
```

Install dependencies:

```sh
poetry install
```

Set needed envrionment variables:

```sh
export ARCHIVE_API_URL=https://archive-api.lco.global/ AWS_BUCKET=thumbservice STORAGE_URL=http://localhost:9090 STORAGE_URL_STYLE=path
```

Run server:

```sh
poetry run python -m thumbservice.thumbservice
```
