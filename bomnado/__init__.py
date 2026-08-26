""" Load the Celery app with Django so `shared_task`s use its settings (e.g. eager mode). """
from .celery import app as celery_app

__all__ = ('celery_app',)
