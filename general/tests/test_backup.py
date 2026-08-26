import os
import tempfile

from django.conf import settings
from django.test import TestCase, override_settings

from general.utils import perform_backup


class HTMLTests(TestCase):
    def test_backup(self):
        """ A backup writes a database dump and a media archive - into a scratch folder, so test
        runs stop littering the real backups/, and named for whichever backend is running (the
        SQLite connector writes .sqlite3.gz; the Postgres one .psql-flavoured files). """
        with tempfile.TemporaryDirectory() as scratch:
            storages = dict(settings.STORAGES)
            storages['dbbackup'] = {'BACKEND': 'django.core.files.storage.FileSystemStorage',
                                    'OPTIONS': {'location': scratch}}
            with override_settings(STORAGES=storages):
                perform_backup()
                files = os.listdir(scratch)

        self.assertTrue(any('.sqlite3' in name or '.psql' in name or '.dump' in name for name in files), files)
        self.assertTrue(any(name.endswith('.tar.gz') or name.endswith('.tar') for name in files), files)
