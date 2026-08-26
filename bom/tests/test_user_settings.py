from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bom.tests.factories import TeamFactory


class UserSettingsViewTests(TestCase):
    """ The per-user settings page: account details and privileges. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.other = User.objects.create_user(username='bob', email='bob@example.com', password='password123')
        self.url = reverse('bom:user_settings')

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_shows_account_details_and_privileges(self):
        owned = TeamFactory(name='Owned Team', owner=self.user)
        owned.users.add(self.user)
        joined = TeamFactory(name='Joined Team', owner=self.other)
        joined.users.add(self.user, self.other)
        TeamFactory(name='Other Team', owner=self.other).users.add(self.other)

        self.client.login(username='alice@example.com', password='password123')
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alice')
        self.assertContains(response, 'alice@example.com')
        self.assertContains(response, 'Owned Team')
        self.assertContains(response, 'Joined Team')
        self.assertNotContains(response, 'Other Team')
        self.assertContains(response, 'Member')
        self.assertNotContains(response, 'Administrator')

    def test_shows_administrator_badge_for_superuser(self):
        admin = User.objects.create_superuser(username='root', email='root@example.com', password='password123')
        self.client.force_login(admin)
        response = self.client.get(self.url)
        self.assertContains(response, 'administrator')

    def test_change_email_and_login_with_new_address(self):
        self.client.login(username='alice@example.com', password='password123')
        response = self.client.post(self.url, {
            'username': 'alice',
            'first_name': 'Alice',
            'last_name': 'Smith',
            'email': 'alice.smith@example.com',
        })
        # Don't fetch the redirect target here - that would consume the one-shot success message.
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice.smith@example.com')
        self.assertEqual(self.user.first_name, 'Alice')
        self.assertEqual(self.user.last_name, 'Smith')

        # Success message is shown once, then cleared.
        response = self.client.get(self.url)
        self.assertContains(response, 'Account details saved.')
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Account details saved.')

        # The new address is now the login identifier.
        self.client.logout()
        self.assertFalse(self.client.login(username='alice@example.com', password='password123'))
        self.assertTrue(self.client.login(username='alice.smith@example.com', password='password123'))

    def test_email_must_be_unique_ignoring_case(self):
        self.client.login(username='alice@example.com', password='password123')
        response = self.client.post(self.url, {'username': 'alice', 'first_name': '', 'last_name': '',
                                               'email': 'BOB@example.com'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already in use')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice@example.com')

    def test_email_is_required(self):
        self.client.login(username='alice@example.com', password='password123')
        response = self.client.post(self.url, {'username': 'alice', 'first_name': '', 'last_name': '', 'email': ''})

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice@example.com')

    def test_change_username(self):
        self.client.login(username='alice@example.com', password='password123')
        response = self.client.post(self.url, {'username': 'ally', 'email': 'alice@example.com'})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'ally')
        # Login is by email, so it is unaffected.
        self.client.logout()
        self.assertTrue(self.client.login(username='alice@example.com', password='password123'))

    def test_username_must_be_unique_ignoring_case(self):
        self.client.login(username='alice@example.com', password='password123')
        response = self.client.post(self.url, {'username': 'BOB', 'email': 'alice@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already taken')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'alice')

    def test_username_must_be_valid(self):
        self.client.login(username='alice@example.com', password='password123')
        for bad in ('', 'has space', 'no!bang'):
            with self.subTest(username=bad):
                response = self.client.post(self.url, {'username': bad, 'email': 'alice@example.com'})
                self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'alice')

    def test_cannot_change_privilege_fields(self):
        """ Posting extra fields (e.g. is_superuser) must not change them. """
        self.client.login(username='alice@example.com', password='password123')
        self.client.post(self.url, {
            'username': 'alice',
            'is_superuser': 'on',
            'is_staff': 'on',
            'email': 'alice@example.com',
        })
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.is_staff)


class UserMenuTests(TestCase):
    """ The user menu holds the account links, and admin-only actions flagged as such. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.admin = User.objects.create_superuser(username='root', email='root@example.com', password='password123')
        self.url = reverse('bom:user_settings')

    def test_regular_user_sees_account_links_but_no_admin_actions(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        menu = self._menu(response)
        for text in ('alice@example.com', '>Settings<', '>Teams<', 'Logout'):
            self.assertIn(text, menu)
        # The username is an internal handle - the menu identifies people by email.
        self.assertNotIn('>alice<', menu)
        for text in ('Django Admin', 'Export Database Backup', '>Admin<'):
            self.assertNotIn(text, menu)
        self.assertNotIn('🧠', response.content.decode())

    def test_superuser_sees_admin_actions_with_badge(self):
        self.client.force_login(self.admin)
        menu = self._menu(self.client.get(self.url))
        for text in ('>Settings<', '>Teams<', 'Logout', 'Django Admin', 'Export Database Backup'):
            self.assertIn(text, menu)
        self.assertEqual(menu.count('>Admin<'), 3)   # admin, export, back up now

    def _menu(self, response):
        html = response.content.decode()
        start = html.index('id="app_user_menu"')
        end = html.index('</header>', start)
        return html[start:end]
