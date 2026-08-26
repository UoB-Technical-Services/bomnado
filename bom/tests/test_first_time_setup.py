import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bom.setup_views import DEMO_SESSION_KEY


class FirstTimeSetupCreateSuperuserTests(TestCase):
    """ The wizard asks for an email and password; the username is derived from the email. """

    def setUp(self):
        self.url = reverse('bom:first_time_setup_api')

    def _create(self, **overrides):
        data = {'action': 'create_superuser', 'email': 'John@Example.com',
                'password': 'password123', 'confirm_password': 'password123'}
        data.update(overrides)
        return self.client.post(self.url, data=json.dumps(data), content_type='application/json').json()

    def test_username_is_derived_from_email(self):
        result = self._create()
        self.assertTrue(result['success'], result)
        user = User.objects.get(email__iexact='john@example.com')
        self.assertEqual(user.username, 'john')
        self.assertTrue(user.is_superuser)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_explicit_username_is_still_honoured(self):
        result = self._create(username='boss')
        self.assertTrue(result['success'], result)
        self.assertEqual(User.objects.get(email__iexact='john@example.com').username, 'boss')

    def test_email_is_required(self):
        result = self._create(email='')
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Email is required')
        self.assertFalse(User.objects.exists())

    def test_duplicate_email_is_rejected_ignoring_case(self):
        User.objects.create_user(username='someone', email='john@example.com', password='x')
        result = self._create()
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Email already exists')

    def test_derived_username_avoids_existing_handle(self):
        User.objects.create_user(username='john', email='other@example.com', password='x')
        result = self._create()
        self.assertTrue(result['success'], result)
        self.assertEqual(User.objects.get(email__iexact='john@example.com').username, 'john2')


class FirstTimeSetupDemoViewTests(TestCase):
    """ The demo project may only be created by the superuser who has just completed setup. """

    def setUp(self):
        self.url = reverse('bom:first_time_setup_demo')

    def _post(self):
        with mock.patch('bom.setup_views.call_command') as command:
            response = self.client.post(self.url, data='{}', content_type='application/json')
        return response, command

    def _allow_demo_in_session(self):
        session = self.client.session
        session[DEMO_SESSION_KEY] = True
        session.save()

    def test_anonymous_is_forbidden(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='password123')
        response, command = self._post()
        self.assertEqual(response.status_code, 403)
        command.assert_not_called()

    def test_regular_user_is_forbidden_even_with_session_flag(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='password123')
        user = User.objects.create_user(username='user', email='user@example.com', password='password123')
        self.client.force_login(user)
        self._allow_demo_in_session()

        response, command = self._post()
        self.assertEqual(response.status_code, 403)
        command.assert_not_called()

    def test_superuser_after_setup_is_forbidden(self):
        """ A superuser in a fresh session (i.e. post-setup) may not re-run the demo from the web. """
        admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='password123')
        self.client.force_login(admin)

        response, command = self._post()
        self.assertEqual(response.status_code, 403)
        self.assertIn('first-time setup', response.json()['error'])
        command.assert_not_called()

    def test_superuser_during_setup_can_create_demo_once(self):
        admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='password123')
        self.client.force_login(admin)
        self._allow_demo_in_session()

        response, command = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        command.assert_called_once_with('createdemo', user='admin', force=True)

        # The permission is consumed.
        response, command = self._post()
        self.assertEqual(response.status_code, 403)
        command.assert_not_called()

    def test_command_failure_keeps_permission_and_reports_error(self):
        admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='password123')
        self.client.force_login(admin)
        self._allow_demo_in_session()

        with mock.patch('bom.setup_views.call_command', side_effect=RuntimeError('boom')):
            response = self.client.post(self.url, data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['success'])
        self.assertIn('boom', response.json()['error'])
        self.assertTrue(self.client.session.get(DEMO_SESSION_KEY))

    def test_get_redirects_to_dashboard(self):
        admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='password123')
        self.client.force_login(admin)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('bom:start'), fetch_redirect_response=False)

    def test_setup_api_grants_demo_permission_to_the_new_superuser(self):
        """ End to end: creating the superuser through the setup API allows the demo in that session. """
        api_url = reverse('bom:first_time_setup_api')
        response = self.client.post(api_url, data=json.dumps({
            'action': 'create_superuser',
            'username': 'admin',
            'email': 'admin@example.com',
            'password': 'password123',
            'confirm_password': 'password123',
        }), content_type='application/json')
        self.assertTrue(response.json()['success'], response.content)
        self.assertTrue(User.objects.get(username='admin').is_superuser)
        self.assertTrue(self.client.session.get(DEMO_SESSION_KEY))

        response, command = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        command.assert_called_once_with('createdemo', user='admin', force=True)
