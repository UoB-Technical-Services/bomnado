""" Settings for the CI test run: the base, against the Postgres service GitHub Actions provides.

Production runs Postgres and development runs SQLite; this is the configuration that proves the
suite passes on what production actually uses.
"""
import os

from bomnado.settings.base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'bomnado'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'bomnado_ci',
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# No broker on the runner: anything queued runs inline.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
BOMNADO_AI_THREADS = False
