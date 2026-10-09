FROM python:3.13-alpine

WORKDIR /app
CMD [ "gunicorn", "--config=thumbservice/config.py", "thumbservice.thumbservice:app" ]

COPY ./pyproject.toml ./poetry.lock ./poetry.toml ./

RUN apk --no-cache add freetype libjpeg-turbo libpng ttf-dejavu zlib \
        && apk --no-cache add --virtual .build-deps \
                freetype-dev \
                gcc \
                g++ \
                libffi-dev \
                libjpeg-turbo-dev \
                libpng-dev \
                make \
                musl-dev \
                openssl-dev \
                zlib-dev \
        && pip install --upgrade pip && pip install poetry \
        && poetry install \
        && apk --no-cache del .build-deps

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
