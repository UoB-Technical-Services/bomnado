from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from bom.middleware import SETUP_COMPLETE_CACHE_KEY

from general import views

LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'danger-tests'}}


class DangerViewGuardTests(TestCase):
    """ reset / backup / restore must only ever run for a superuser.

    The views are exercised directly through a RequestFactory because they are
    deliberately not routed in `bomnado.urls`, and the destructive work is mocked
    out so nothing touches the real database or disk.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='user', email='user@example.com', password='password123')
        self.staff = User.objects.create_user(username='staff', email='staff@example.com', password='password123',
                                              is_staff=True)
        self.admin = User.objects.create_superuser(username='admin', email='admin@example.com',
                                                   password='password123')

    def _post(self, view, user):
        request = self.factory.post('/admin/danger/')
        request.user = user
        return view(request)

    def test_anonymous_post_is_forbidden(self):
        for view in (views.reset_database, views.backup_all, views.restore_all):
            with self.subTest(view=view.__name__):
                with mock.patch.object(views, 'perform_backup') as backup, \
                        mock.patch.object(views, 'perform_restore') as restore, \
                        mock.patch.object(views, 'call_command') as command, \
                        mock.patch.object(views.os, 'remove') as remove:
                    response = self._post(view, AnonymousUser())
                self.assertEqual(response.status_code, 403)
                for action in (backup, restore, command, remove):
                    action.assert_not_called()

    def test_regular_and_staff_users_are_forbidden(self):
        for user in (self.user, self.staff):
            for view in (views.reset_database, views.backup_all, views.restore_all):
                with self.subTest(user=user.username, view=view.__name__):
                    with mock.patch.object(views, 'perform_backup') as backup, \
                            mock.patch.object(views, 'perform_restore') as restore, \
                            mock.patch.object(views, 'call_command') as command, \
                            mock.patch.object(views.os, 'remove') as remove:
                        response = self._post(view, user)
                    self.assertEqual(response.status_code, 403)
                    for action in (backup, restore, command, remove):
                        action.assert_not_called()

    def test_get_is_not_allowed_even_for_superuser(self):
        for view in (views.reset_database, views.backup_all, views.restore_all):
            with self.subTest(view=view.__name__):
                request = self.factory.get('/admin/danger/')
                request.user = self.admin
                self.assertEqual(view(request).status_code, 405)

    def test_superuser_can_backup(self):
        with mock.patch.object(views, 'perform_backup') as backup:
            response = self._post(views.backup_all, self.admin)
        self.assertEqual(response.status_code, 204)
        backup.assert_called_once_with()

    def test_superuser_can_restore(self):
        with mock.patch.object(views, 'perform_restore') as restore:
            response = self._post(views.restore_all, self.admin)
        self.assertEqual(response.status_code, 204)
        restore.assert_called_once_with()

    @override_settings(CACHES=LOCMEM_CACHE)
    def test_superuser_can_reset(self):
        cache.set(SETUP_COMPLETE_CACHE_KEY, True, None)
        with mock.patch.object(views, 'call_command') as command, \
                mock.patch.object(views.os, 'remove') as remove, \
                mock.patch.object(views, 'close_old_connections'):
            response = self._post(views.reset_database, self.admin)
        self.assertEqual(response.status_code, 204)
        command.assert_called_with('migrate', '--noinput')
        # The test database is SQLite, so the file-removal branch runs.
        remove.assert_called_once()
        # The first-time-setup latch is released so the wizard runs again.
        self.assertIsNone(cache.get(SETUP_COMPLETE_CACHE_KEY))


class SuperuserRequiredDecoratorTests(SimpleTestCase):

    def test_request_without_user_attribute_is_forbidden(self):
        @views.superuser_required
        def view(request):
            raise AssertionError('must not be reached')

        response = view(RequestFactory().post('/'))
        self.assertEqual(response.status_code, 403)
