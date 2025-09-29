from enum import StrEnum
from logging import getLogger
import os
from celery.schedules import crontab
from bomnado.settings import get_bool_environment_var, get_list_environment_var, get_str_enum_environment_var, get_time_environment_var
from bomnado.settings.base import *

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration


log = getLogger()
DEBUG = False

ALLOWED_HOSTS = get_list_environment_var('DJANGO_ALLOWED_HOSTS', None)

CSRF_TRUSTED_ORIGINS = get_list_environment_var('CSRF_TRUSTED_ORIGINS', None)

POSTGRES_USER = os.environ.get('POSTGRES_USER')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD')
POSTGRES_DB = os.environ.get('POSTGRES_DB')
POSTGRES_HOST = os.environ.get('POSTGRES_HOST')
POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432')

if not all([
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    POSTGRES_DB,
    POSTGRES_HOST,
]):
    raise ValueError('All PostgreSQL database settings must be cofigured: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST')

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': POSTGRES_DB,
        'USER': POSTGRES_USER,
        'PASSWORD': POSTGRES_PASSWORD,
        'HOST': POSTGRES_HOST,
        'PORT': POSTGRES_PORT,
    }
}

REDIS_LOCATION = os.environ.get('REDIS_LOCATION', 'redis://redis:6379')
""" Where is Redis located (for caching and Celery tasks) """

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_LOCATION,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient"
        },
        "KEY_PREFIX": "cache_default",
    }
}

SENTRY_DSN = os.environ.get('SENTRY_DSN')
"""The Sentry DSN to use for this Bomnado instance when submitting error logs"""

SENTRY_ENVIRONMENT = os.environ.get('SENTRY_ENVIRONMENT', 'production')
"""Sentry environment to push events under"""

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=True,
        release=VERSION,
        environment="production",
    )

EMAIL_SUBJECT_PREFIX = 'Bomnado'

class EmailMode(StrEnum):
    EMAIL = 'email'
    CONSOLE = 'console'


EMAIL_MODE = get_str_enum_environment_var('EMAIL_MODE', EmailMode.CONSOLE, EmailMode)
if EMAIL_MODE == EmailMode.EMAIL:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.environ.get('EMAIL_HOST')
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
    EMAIL_PORT = os.environ.get('EMAIL_PORT')
    EMAIL_USE_TLS = get_bool_environment_var('EMAIL_USE_TLS', False)
    if not all([
        EMAIL_HOST,
        EMAIL_HOST_USER,
        EMAIL_HOST_PASSWORD,
        EMAIL_PORT,
    ]):
        raise ValueError(f'All email settings must be cofigured when using \"email\" mode: EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_PORT, EMAIL_USE_TLS. Set these or use EMAIL_MODE={EmailMode.CONSOLE}')
elif EMAIL_MODE == EmailMode.CONSOLE:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL')

USE_DROPBOX_BACKUPS = get_bool_environment_var('USE_DROPBOX_BACKUPS', False)
if USE_DROPBOX_BACKUPS:
    # Store the backups in dropbox for extra security
    DBBACKUP_STORAGE = 'storages.backends.dropbox.DropBoxStorage'
    # TODO validate that all of these are set when using USE_DROPBOX_BACKUPS
    DROPBOX_ROOT_PATH = os.environ.get('DROPBOX_ROOT_PATH')
    DROPBOX_APP_KEY = os.environ.get('DROPBOX_APP_KEY')
    DROPBOX_APP_SECRET = os.environ.get('DROPBOX_APP_SECRET')
    DROPBOX_OAUTH2_TOKEN = os.environ.get('DROPBOX_OAUTH2_TOKEN')
    DROPBOX_OAUTH2_REFRESH_TOKEN = os.environ.get('DROPBOX_OAUTH2_REFRESH_TOKEN')

    if all([DROPBOX_ROOT_PATH, DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_OAUTH2_TOKEN, DROPBOX_OAUTH2_REFRESH_TOKEN]):
        # Store the backups in dropbox for extra security
        # Preserve the staticfiles backend from base settings
        STORAGES = {
            **STORAGES,  # Include base STORAGES configuration
            "dbbackup": {
                "BACKEND": "storages.backends.dropbox.DropBoxStorage",
                "OPTIONS": {
                    "oauth2_access_token": DROPBOX_OAUTH2_TOKEN,
                    "oauth2_refresh_token": DROPBOX_OAUTH2_REFRESH_TOKEN,
                    "app_key": DROPBOX_APP_KEY,
                    "app_secret": DROPBOX_APP_SECRET,
                    "root_path": DROPBOX_ROOT_PATH,
                },
            },
        }
    else:
        raise ValueError("Please ensure that all Dropbox backup settings are configured: DROPBOX_ROOT_PATH, DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_OAUTH2_TOKEN, DROPBOX_OAUTH2_REFRESH_TOKEN")

BACKUP_TIME = get_time_environment_var('BACKUP_TIME', (5, 00))

# Celery settings
CELERY_BROKER_URL = REDIS_LOCATION
CELERY_RESULT_BACKEND = "django-db"
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_BEAT_SCHEDULE = {
    "full_backup": {  # Backup database + media
        "task": "general.tasks.perform_full_backup",
        "schedule": crontab(hour=BACKUP_TIME[0], minute=BACKUP_TIME[1]),
    }
}

# The following will tell db backup to email the people listed below if that backup fails for any reason
dbbackup_admins_input = get_list_environment_var('DBBACKUP_ADMINS', [])
if len(dbbackup_admins_input) > 0:
    DBBACKUP_SEND_EMAIL = True
    if len(dbbackup_admins_input) % 2 != 0:
        raise ValueError('DBBACKUP_ADMINS must contain an even number of values')

    # Group into pairs (name, email)
    # grab every other item, starting from 0 for names, and 1 for their emails
    DBBACKUP_ADMINS = tuple(zip(dbbackup_admins_input[0::2], dbbackup_admins_input[1::2]))