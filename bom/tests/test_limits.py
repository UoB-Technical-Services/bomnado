""" The doors have springs: sign-in and reset are rate-limited, and a chat message cannot carry
an unbounded pile of files. The counters live in the cache, so each test starts it clean. """
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from bom.tests.factories import TeamFactory
from bom.views import ai as ai_views


class AuthThrottleTests(TestCase):

    def setUp(self):
        cache.clear()
        User.objects.create_user(username='alice', email='alice@example.com', password='right')

    def test_the_eleventh_sign_in_attempt_in_a_minute_waits(self):
        for _ in range(10):
            response = self.client.post('/accounts/login/', {'username': 'alice@example.com', 'password': 'wrong'})
            self.assertNotContains(response, 'Too many attempts')
        response = self.client.post('/accounts/login/', {'username': 'alice@example.com', 'password': 'right'})
        self.assertContains(response, 'Too many attempts')            # even the right password waits now

    def test_reset_emails_stop_quietly_after_five(self):
        for _ in range(7):
            response = self.client.post('/accounts/password_reset/', {'email': 'alice@example.com'})
            self.assertEqual(response.status_code, 302)               # always the done page: nothing to enumerate
        self.assertEqual(len(mail.outbox), 5)


class ChatUploadLimitTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        team = TeamFactory(owner=self.user)
        team.users.add(self.user)
        self.client.force_login(self.user)

    def test_too_many_files_are_refused(self):
        files = [SimpleUploadedFile(f'file{i}.txt', b'x') for i in range(11)]
        response = self.client.post(reverse('bom:ai_chat_send'), {'text': 'here', 'files': files})
        self.assertContains(response, 'At most 10 files')

    def test_a_file_over_the_size_limit_is_refused_by_name(self):
        with mock.patch.object(ai_views, 'CHAT_FILE_BYTES', 1024):
            big = SimpleUploadedFile('huge-scan.pdf', b'x' * 2048)
            response = self.client.post(reverse('bom:ai_chat_send'), {'text': 'here', 'files': [big]})
        self.assertContains(response, 'huge-scan.pdf is over 0 MB')
