FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1

# ENVs that will be overridden by env file, but sensible defaults
ENV DJANGO_SETTINGS_MODULE=bomnado.settings.production
ENV EMAIL_MODE=console
ENV DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Install some necessary things.
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    swig \
    libssl-dev \
    dpkg-dev \
    netcat-traditional \
    uwsgi-plugin-python3 \
    nginx \
    python3-dev \
    libpq-dev \
    supervisor \
    memcached \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create work directory
RUN mkdir /code
WORKDIR /code
VOLUME /code/media
VOLUME /code/backups

# Install PDM (modern package/dependency manager)
RUN pip install --no-cache-dir pdm

# Copy dependency metadata first (for better Docker layer caching) then install deps
COPY pyproject.toml pdm.lock* ./
RUN pdm sync -v

# Copy project code
COPY . /code/

RUN pdm run manage collectstatic --noinput

EXPOSE 80
CMD ["pdm", "run", "gunicorn", "bomnado.wsgi:application", "--bind", "0.0.0.0:80"]
