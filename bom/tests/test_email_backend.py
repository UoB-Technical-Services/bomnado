from unittest import mock

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.test import TestCase


class EmailBackendTests(TestCase):
    """ Logging in by email address, including the awkward cases. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='Alice@example.com', password='password123')

    def test_correct_credentials(self):
        self.assertEqual(authenticate(username='Alice@example.com', password='password123'), self.user)

    def test_email_is_case_insensitive(self):
        self.assertEqual(authenticate(username='alice@EXAMPLE.com', password='password123'), self.user)

    def test_wrong_password(self):
        self.assertIsNone(authenticate(username='Alice@example.com', password='nope'))

    def test_unknown_email(self):
        self.assertIsNone(authenticate(username='nobody@example.com', password='password123'))

    def test_missing_credentials(self):
        self.assertIsNone(authenticate(username=None, password='password123'))
        self.assertIsNone(authenticate(username='Alice@example.com', password=None))

    def test_inactive_user_cannot_authenticate(self):
        self.user.is_active = False
        self.user.save()
        self.assertIsNone(authenticate(username='Alice@example.com', password='password123'))

    def test_duplicate_emails_do_not_raise(self):
        """ Two accounts sharing an address used to raise MultipleObjectsReturned (a 500 on login). """
        second = User.objects.create_user(username='alice2', email='alice@example.com', password='different456')

        self.assertEqual(authenticate(username='alice@example.com', password='password123'), self.user)
        self.assertEqual(authenticate(username='alice@example.com', password='different456'), second)
        self.assertIsNone(authenticate(username='alice@example.com', password='neither'))

    def test_duplicate_emails_skip_inactive_match(self):
        self.user.is_active = False
        self.user.save()
        second = User.objects.create_user(username='alice2', email='alice@example.com', password='password123')
        self.assertEqual(authenticate(username='alice@example.com', password='password123'), second)

    def test_login_view_with_duplicate_emails_does_not_500(self):
        User.objects.create_user(username='alice2', email='alice@example.com', password='different456')
        response = self.client.post('/accounts/login/', {'username': 'alice@example.com', 'password': 'password123'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_unknown_email_still_runs_password_hasher(self):
        """ Timing mitigation: rejecting an unknown address should cost a hash, like a wrong password. """
        with mock.patch.object(User, 'set_password') as set_password:
            authenticate(username='nobody@example.com', password='password123')
        set_password.assert_called_once_with('password123')

    def test_known_email_does_not_run_dummy_hasher(self):
        with mock.patch.object(User, 'set_password') as set_password:
            authenticate(username='Alice@example.com', password='wrong')
        set_password.assert_not_called()
