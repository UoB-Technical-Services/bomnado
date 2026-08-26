import re

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from bom.tests.factories import TeamFactory


class AddToTeamViewTests(TestCase):
    """ Team owners add existing users by username/email, or invite new users by email. """

    def setUp(self):
        self.owner = User.objects.create_user(username='owner', email='owner@example.com', password='password123')
        self.member = User.objects.create_user(username='member', email='Member@example.com', password='password123')
        self.team = TeamFactory(name='Widgets', owner=self.owner)
        self.team.users.add(self.owner)
        self.url = reverse('bom:teams_add', kwargs={'pk': self.team.id})
        self.client.force_login(self.owner)

    def _add(self, identifier):
        response = self.client.post(self.url, {'username': identifier})
        self.assertRedirects(response, reverse('bom:teams'), fetch_redirect_response=False)
        return self.client.get(reverse('bom:teams'))

    def test_add_existing_user_by_username(self):
        page = self._add('member')
        self.assertTrue(self.team.users.filter(pk=self.member.pk).exists())
        self.assertContains(page, 'Member@example.com has been added to Widgets.')

    def test_add_existing_user_by_email_case_insensitive(self):
        page = self._add('member@EXAMPLE.com')
        self.assertTrue(self.team.users.filter(pk=self.member.pk).exists())
        self.assertContains(page, 'Member@example.com has been added to Widgets.')
        self.assertEqual(User.objects.count(), 2)

    def test_adding_existing_member_again_is_reported(self):
        self.team.users.add(self.member)
        page = self._add('member')
        self.assertContains(page, 'already a member')
        self.assertEqual(self.team.users.filter(pk=self.member.pk).count(), 1)

    def test_blank_identifier_is_reported(self):
        page = self._add('   ')
        self.assertContains(page, 'Enter a username or email address')

    def test_unknown_username_is_reported_and_creates_nothing(self):
        page = self._add('nobody')
        self.assertContains(page, 'No user called')
        self.assertEqual(User.objects.count(), 2)

    def test_unknown_email_invites_new_user(self):
        page = self._add('new.person@example.com')

        user = User.objects.get(email='new.person@example.com')
        self.assertEqual(user.username, 'new.person')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(self.team.users.filter(pk=user.pk).exists())

        # The owner is shown a set-password link, and it is emailed too.
        self.assertContains(page, 'Created an account for new.person@example.com')
        link = re.search(r'id="invite-link" value="([^"]+)"', page.content.decode()).group(1)
        self.assertIn('/accounts/reset/', link)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['new.person@example.com'])
        self.assertIn(link, mail.outbox[0].body)

        # The link is one-shot in the page too.
        self.assertNotContains(self.client.get(reverse('bom:teams')), 'invite-link')
        return user, link

    def test_invite_link_lets_the_new_user_set_a_password_and_log_in(self):
        user, link = self.test_unknown_email_invites_new_user()
        self.client.logout()

        # Django's confirm view stashes the token in the session and redirects to a set-password form.
        response = self.client.get(link)
        self.assertEqual(response.status_code, 302)
        set_password_url = response['Location']
        response = self.client.get(set_password_url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(set_password_url, {
            'new_password1': 'a-long-secret-9', 'new_password2': 'a-long-secret-9'})
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertTrue(user.has_usable_password())
        self.assertTrue(self.client.login(username='new.person@example.com', password='a-long-secret-9'))

        # Used links stop working.
        self.client.logout()
        response = self.client.get(link, follow=True)
        self.assertContains(response, 'invalid', status_code=200)

    def test_invited_username_is_deduplicated(self):
        User.objects.create_user(username='Sam', email='sam@elsewhere.com', password='password123')
        User.objects.create_user(username='sam2', email='sam2@elsewhere.com', password='password123')

        self._add('sam@example.com')

        user = User.objects.get(email='sam@example.com')
        self.assertEqual(user.username, 'sam3')
        self.assertTrue(self.team.users.filter(pk=user.pk).exists())

    def test_invited_username_drops_invalid_characters(self):
        self._add("o'neil!@example.com")
        self.assertEqual(User.objects.get(email="o'neil!@example.com").username, 'oneil')

    def test_non_owner_cannot_add(self):
        self.team.users.add(self.member)
        self.client.force_login(self.member)
        response = self.client.post(self.url, {'username': 'new.person@example.com'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email='new.person@example.com').exists())

    def test_non_member_cannot_add(self):
        outsider = User.objects.create_user(username='outsider', email='out@example.com', password='password123')
        self.client.force_login(outsider)
        response = self.client.post(self.url, {'username': 'member'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.team.users.filter(pk=self.member.pk).exists())
