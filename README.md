# Thumbnail service

This is a flask application that generates thumbnails from data stored on the
[LCOGT Science Archive](https://developers.lcogt.net/pages/archive.html).

## Requirements

This script uses amazon S3 to temporarily store images. You'll need a bucket and the
[correct environmental variables](http://boto3.readthedocs.io/en/latest/guide/quickstart.html#configuration)
set.

This script also relies on [fits2image](https://github.com/LCOGT/fits2image). Make sure it is installed
in your virtualenv.

All other dependencies are listed in the requirements.txt file and can be installed with pip.

Run the tests with `pytest tests.py`.

## Authorization

The api passes through the `Authorization` header to the archive API. You only need to provide
this header if the data you are attempting to get a thumbnail for is proprietary. See the archive
documentation for more details.

## Endpoints

There are only 2 endpoints: `/<frame_id>/` and `/<basename>/` where `frame_id` is the ID of the frame
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


## Example

[https://thumbnails.lcogt.net/3863274/?width=500&height=500&label=So%20many%20stars](https://thumbnails.lcogt.net/3863274/?width=500&height=500&label=So%20many%20stars)

## Changelog

### 2.11
2019-04-05
* Update boto3, requests, and flask
* Temporary file cleanup improvements
* Validate frame before attempting thumbnail generation
* Update error handling

### 2.10
2019-02-16
* Update numpy version
* Add DejaVu True Type Fonts
* Add freetype dependency for text overlay support
* Use standard LCO Jenkins automated docker container build pipeline
* Migrate Docker container to Alpine Linux base

### 2.9
2018-11-13
* Upgrade requests
* Initialize a variable that could have been referenced before assignment

### 2.5
* 2017-05-15
* Upgrade Dockerfile to be more sensible, upgrade to python 3.6

### 2.4
2017-04-04
* Add better exception handling to clean up temporary files even if generation fails.

### 2.3
2017-03-17
* Add quality paramter and reduce default quality. Improves speed without a noticeable change in image quality.
* Improve filename key so that any differnt combination of parameters will reuslt in a new image.

### 2.2
2017-02-27
* Added median filtering support

### 2.1
2016-08-24
* Fixed bug where images of different reduction levels were used to compose color images

### 2.0
2016-08-17
* Added color image support! Use ?color=True for frames which belong to a request that have other exposures
using red, visual and blue filters.

### 1.1
2016-08-11
* Added `image` url parameter to return image directly instead of json. Useful
for using as the src attribute in img tags.
