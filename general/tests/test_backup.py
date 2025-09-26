import os

from django.test import TestCase
from django.conf import settings

from general.utils import perform_backup


class HTMLTests(TestCase):
    def test_backup(self):
        """
        Basic test on database + media backup
        :return: none
        """

        perform_backup()
        database_dump_found = False
        media_backup_found = False

        # Get backup location from STORAGES configuration
        backup_location = settings.STORAGES['dbbackup']['OPTIONS']['location']

        for file in os.listdir(backup_location):
            # Check for database backups - extension depends on database backend
            if file.endswith(".sqlite3.gz"):
                database_dump_found = True

        for file in os.listdir(backup_location):
            if file.endswith(".tar.gz"):
                media_backup_found = True

        self.assertEqual(database_dump_found, True)
        self.assertEqual(media_backup_found, True)
