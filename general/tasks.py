from celery import shared_task

from general.utils import perform_backup


@shared_task
def perform_full_backup():
    """Perform a django database backup

    A full-backup records both the database media and database.
    """
    perform_backup()
