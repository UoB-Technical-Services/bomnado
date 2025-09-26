import os
import glob

from django.core import management
from django.conf import settings


def get_all_database_backups():
    """
    Returns a list of all database backups.
    :return: a sorted list of all database backups by creation date
    """
    backup_location = settings.STORAGES['dbbackup']['OPTIONS']['location']
    sqlite_backups = glob.glob(os.path.join(backup_location, "*.sqlite3.gz"))
    sorted_database_backups = sorted(sqlite_backups)
    return sorted_database_backups


def get_last_database_backup_filepath():
    """
    Returns the filepath of the last database backup.
    :return: The filepath of the last database backup, None if no database backup exists
    """
    sorted_json_database_backups = get_all_database_backups()
    if len(sorted_json_database_backups) > 0:
        return sorted_json_database_backups[-1]
    else:
        return None


def perform_backup():
    """
    Performs a backup of the database and media files.
    :return: None
    """

    management.call_command("dbbackup", "--clean", compress=True)
    management.call_command("mediabackup", "--clean", compress=True)


def perform_restore():
    """
    Performs a restore of the database and media files.
    :return: None
    """
    management.call_command("mediarestore", "--uncompress", "--replace", "--noinput")
    management.call_command("dbrestore", "--uncompress", "--noinput")
