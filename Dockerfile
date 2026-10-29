FROM python:3.14-alpine

WORKDIR /app

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

CMD [ "gunicorn", "-b", "0.0.0.0:8000", "--config=thumbservice/config.py", "thumbservice.thumbservice:app" ]
