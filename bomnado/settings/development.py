from bomnado.settings.base import *  # noqa: F401

DEBUG = True

ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1',
    'https://127.0.0.1',
    'http://localhost',
    'https://localhost',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'db.sqlite3',
    }
}

# Caches
# https://docs.djangoproject.com/en/3.0/ref/settings/#caches
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'bomnado_cache',
    }
}

# Email Settings For Dev
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# No broker in development: AI jobs run in a background thread of the dev server.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
BOMNADO_AI_THREADS = not TESTING  # tests run jobs inline
