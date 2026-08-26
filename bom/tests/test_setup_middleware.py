from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from bom.middleware import SETUP_COMPLETE_CACHE_KEY, FirstTimeSetupMiddleware, mark_setup_incomplete

# The middleware's cheap first check is "does the SQLite file exist?". The test
# database is in memory, so point NAME at a file that certainly exists.
EXISTING_DB_FILE = {'default': {**settings.DATABASES['default'], 'NAME': __file__}}
LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'setup-latch-tests'}}


@override_settings(DATABASES=EXISTING_DB_FILE, CACHES=LOCMEM_CACHE)
class FirstTimeSetupMiddlewareTests(TestCase):
    """ The middleware is not installed while testing, so it is driven directly. """

    def setUp(self):
        cache.clear()
        self.middleware = FirstTimeSetupMiddleware(lambda request: HttpResponse('ok'))
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    def _dashboard(self):
        return self.middleware.process_request(self.factory.get('/'))

    def test_redirects_to_setup_when_no_superuser(self):
        response = self._dashboard()
        self.assertEqual(response.status_code, 302)
        self.assertIn('/setup/', response['Location'])
        self.assertIsNone(cache.get(SETUP_COMPLETE_CACHE_KEY))

    def test_setup_pages_are_always_allowed(self):
        self.assertIsNone(self.middleware.process_request(self.factory.get('/setup/')))

    def test_latches_once_setup_is_complete(self):
        User.objects.create_superuser(username='root', email='root@example.com', password='password123')

        # First request does the full check and records the result...
        with mock.patch('bom.middleware.MigrationExecutor') as executor:
            executor.return_value.migration_plan.return_value = []
            self.assertIsNone(self._dashboard())
            self.assertEqual(executor.call_count, 1)
        self.assertTrue(cache.get(SETUP_COMPLETE_CACHE_KEY))

        # ...subsequent requests skip the migration-plan and superuser checks.
        with mock.patch('bom.middleware.MigrationExecutor') as executor, \
                mock.patch('bom.middleware.User.objects') as users:
            for _ in range(5):
                self.assertIsNone(self._dashboard())
            executor.assert_not_called()
            users.filter.assert_not_called()

    def test_mark_setup_incomplete_clears_the_latch(self):
        User.objects.create_superuser(username='root', email='root@example.com', password='password123')
        self.assertIsNone(self._dashboard())
        self.assertTrue(cache.get(SETUP_COMPLETE_CACHE_KEY))

        mark_setup_incomplete()
        self.assertIsNone(cache.get(SETUP_COMPLETE_CACHE_KEY))

        with mock.patch('bom.middleware.MigrationExecutor') as executor:
            executor.return_value.migration_plan.return_value = []
            self.assertIsNone(self._dashboard())
            self.assertEqual(executor.call_count, 1)

    def test_missing_sqlite_file_is_noticed_even_when_latched(self):
        cache.set(SETUP_COMPLETE_CACHE_KEY, True, None)
        databases = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': 'C:/definitely/not/here.sqlite3'}}
        with override_settings(DATABASES=databases):
            response = self._dashboard()
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(cache.get(SETUP_COMPLETE_CACHE_KEY))
