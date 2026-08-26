""" Bomnado AI: the foundation - encrypted per-user keys, the settings card,
cost accounting and the server-side fetcher. No call here reaches the real API. """
import socket
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from bom.ai import crypto, fetch
from bom.ai.client import AINotConfigured, client_for, cost_of, model_for
from bom.models import AIJob, UserAISettings

KEY = 'sk-ant-api03-' + 'x' * 40 + 'wxyz'


class CryptoTests(TestCase):

    def test_round_trip_and_empty(self):
        token = crypto.encrypt(KEY)
        self.assertNotIn(KEY, token)
        self.assertEqual(crypto.decrypt(token), KEY)
        self.assertEqual(crypto.encrypt(''), '')
        self.assertEqual(crypto.decrypt(''), '')

    def test_tampered_or_foreign_tokens_read_as_empty(self):
        token = crypto.encrypt(KEY)
        self.assertEqual(crypto.decrypt(token[:-2] + 'zz'), '')
        with override_settings(BOMNADO_FERNET_KEY='rDz1yvUbjnm3_FMnUoYaKuICGGfEZ1YnYCWQOSHjQrw='):
            self.assertEqual(crypto.decrypt(token), '')  # a different key: not ours


class UserAISettingsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')

    def test_key_is_stored_encrypted_and_masked(self):
        config = UserAISettings(user=self.user)
        config.api_key = KEY
        config.save()
        config = UserAISettings.objects.get()
        self.assertNotIn(KEY, config.encrypted_api_key)
        self.assertEqual(config.api_key, KEY)
        self.assertTrue(config.is_configured)
        self.assertEqual(config.masked_key, 'sk-ant-…wxyz')

    def test_client_needs_a_key(self):
        with self.assertRaises(AINotConfigured):
            client_for(self.user)
        self.assertEqual(model_for(self.user), 'claude-opus-5')
        config = UserAISettings(user=self.user, model='claude-sonnet-5')
        config.api_key = KEY
        config.save()
        self.user.refresh_from_db()
        self.assertEqual(model_for(self.user), 'claude-sonnet-5')
        client = client_for(self.user)
        self.assertEqual(client.api_key, KEY)

    def test_cost_and_spend(self):
        self.assertEqual(cost_of('claude-opus-5', 1_000_000, 100_000), Decimal('7.5000'))
        self.assertEqual(cost_of('claude-sonnet-5', 1000, 1000, web_searches=2), Decimal('0.0380'))
        config = UserAISettings(user=self.user, monthly_budget=Decimal('5'))
        config.api_key = KEY
        config.save()
        AIJob.objects.create(user=self.user, kind=AIJob.KIND_CHAT, cost=Decimal('2.5'))
        AIJob.objects.create(user=self.user, kind=AIJob.KIND_CHAT, cost=Decimal('3'))
        self.assertEqual(config.spend_this_month(), Decimal('5.5'))
        self.assertTrue(config.over_budget())

    def test_job_records_usage(self):
        job = AIJob.objects.create(user=self.user, kind=AIJob.KIND_CHAT, model='claude-opus-5')
        response = mock.Mock()
        response.usage = mock.Mock(input_tokens=1000, output_tokens=500, cache_read_input_tokens=200,
                                   cache_creation_input_tokens=0, server_tool_use=mock.Mock(web_search_requests=3))
        job.add_usage(response)
        job.refresh_from_db()
        self.assertEqual((job.input_tokens, job.output_tokens, job.web_searches), (1200, 500, 3))
        self.assertEqual(job.cost, Decimal('0.0485'))  # 1200*5 + 500*25 per M, + 3 searches


class SettingsPageTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.client.force_login(self.user)
        self.url = reverse('bom:user_settings')

    def test_card_saves_key_without_ever_showing_it(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('AI assistant', html)
        self.assertIn('Not set', html)

        response = self.client.post(self.url, {'form_name': 'ai', 'api_key': KEY, 'model': 'claude-sonnet-5',
                                               'monthly_budget': '10'})
        self.assertRedirects(response, self.url + '#ai-settings')
        config = UserAISettings.objects.get(user=self.user)
        self.assertEqual((config.api_key, config.model, config.monthly_budget), (KEY, 'claude-sonnet-5', Decimal('10')))

        html = self.client.get(self.url).content.decode()
        self.assertNotIn(KEY, html)
        self.assertIn('sk-ant-…wxyz', html)
        self.assertIn('Test connection', html)
        self.assertIn('Remove key', html)

        # Saving again with a blank key keeps the stored one.
        self.client.post(self.url, {'form_name': 'ai', 'api_key': '', 'model': 'claude-opus-5', 'monthly_budget': ''})
        config.refresh_from_db()
        self.assertEqual((config.api_key, config.model, config.monthly_budget), (KEY, 'claude-opus-5', None))

        self.client.post(self.url, {'form_name': 'ai', 'remove_key': '1'})
        config.refresh_from_db()
        self.assertFalse(config.is_configured)

    def test_key_must_look_like_a_key(self):
        response = self.client.post(self.url, {'form_name': 'ai', 'api_key': 'hunter2', 'model': 'claude-opus-5'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('does not look like an Anthropic API key', response.content.decode())
        self.assertFalse(UserAISettings.objects.exists())

    def test_account_form_still_works(self):
        response = self.client.post(self.url, {'username': 'alice', 'first_name': 'Alice', 'last_name': '',
                                               'email': 'alice@example.com'})
        self.assertRedirects(response, self.url)
        self.assertEqual(User.objects.get(pk=self.user.pk).first_name, 'Alice')

    def test_test_connection(self):
        url = reverse('bom:ai_test_connection')
        self.assertIn('Add an AI API key', self.client.post(url).content.decode())

        config = UserAISettings(user=self.user)
        config.api_key = KEY
        config.save()
        with mock.patch('bom.ai.client.anthropic.Anthropic') as anthropic_cls:
            anthropic_cls.return_value.models.retrieve.return_value = mock.Mock(display_name='Claude Opus 5')
            html = self.client.post(url).content.decode()
        self.assertIn('Connected - Claude Opus 5 is ready.', html)
        anthropic_cls.assert_called_once()
        self.assertEqual(anthropic_cls.call_args.kwargs['api_key'], KEY)
        anthropic_cls.return_value.models.retrieve.assert_called_once_with('claude-opus-5')

        with mock.patch('bom.ai.client.anthropic.Anthropic') as anthropic_cls:
            anthropic_cls.return_value.models.retrieve.side_effect = RuntimeError('401 invalid x-api-key')
            html = self.client.post(url).content.decode()
        self.assertIn('Could not connect: 401 invalid x-api-key', html)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse('bom:ai_test_connection')).status_code, 302)


class FetchTests(TestCase):

    def _resolve_to(self, address):
        return mock.patch('bom.ai.fetch.socket.getaddrinfo', return_value=[(2, 1, 6, '', (address, 443))])

    def test_refuses_private_and_odd_urls(self):
        for url in ('ftp://example.com/x', 'file:///etc/passwd', 'http://localhost/', 'http://user:pw@example.com/',
                    'not a url', 'http://printer.local/'):
            with self.subTest(url=url):
                with self.assertRaises(fetch.UnsafeURL):
                    fetch.check_url(url)
        for address in ('127.0.0.1', '10.1.2.3', '192.168.0.1', '169.254.169.254', '172.16.0.9', '::1', 'fd00::1'):
            with self.subTest(address=address), self._resolve_to(address):
                with self.assertRaises(fetch.UnsafeURL):
                    fetch.check_url('https://supplier.example.com/p/1')
        with mock.patch('bom.ai.fetch.socket.getaddrinfo', side_effect=socket.gaierror):
            with self.assertRaises(fetch.UnsafeURL):
                fetch.check_url('https://no-such-host.example/')
        with self._resolve_to('93.184.216.34'):
            self.assertEqual(fetch.check_url('https://supplier.example.com/p/1').hostname, 'supplier.example.com')

    def test_fetch_follows_safe_redirects_and_caps_size(self):
        redirect = mock.Mock(is_redirect=True, is_permanent_redirect=False, headers={'Location': '/p/2'}, status_code=301)
        page = mock.Mock(is_redirect=False, is_permanent_redirect=False, status_code=200,
                         headers={'Content-Type': 'text/html'})
        page.iter_content.return_value = [b'<html>', b'ok</html>']
        with self._resolve_to('93.184.216.34'), mock.patch('bom.ai.fetch.requests.get', side_effect=[redirect, page]) as get:
            url, content_type, body = fetch.fetch_url('https://supplier.example.com/p/1')
        self.assertEqual((url, content_type, body), ('https://supplier.example.com/p/2', 'text/html', b'<html>ok</html>'))
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

        # A redirect to somewhere private is refused, even from a public start.
        inward = mock.Mock(is_redirect=True, is_permanent_redirect=False, headers={'Location': 'http://169.254.169.254/'},
                           status_code=302)
        with mock.patch('bom.ai.fetch.socket.getaddrinfo',
                        side_effect=[[(2, 1, 6, '', ('93.184.216.34', 443))], [(2, 1, 6, '', ('169.254.169.254', 80))]]), \
                mock.patch('bom.ai.fetch.requests.get', return_value=inward):
            with self.assertRaises(fetch.UnsafeURL):
                fetch.fetch_url('https://supplier.example.com/p/1')

        big = mock.Mock(is_redirect=False, is_permanent_redirect=False, status_code=200, headers={})
        big.iter_content.return_value = [b'x' * 1024] * 5
        with self._resolve_to('93.184.216.34'), mock.patch('bom.ai.fetch.requests.get', return_value=big):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch_url('https://supplier.example.com/p/1', max_bytes=2048)

    def test_html_to_text_keeps_what_matters(self):
        html = '''<html><head><title>M8 x 20mm Button Head Screw BZP</title>
            <meta name="description" content="Zinc plated button head screw">
            <meta property="og:image" content="/img/m8.jpg"></head>
            <body><nav><a>Home</a><a>Home</a></nav><script>alert(1)</script><style>p{}</style>
            <h1>M8 x 20mm Button Head</h1><p>Pack of 100.   Price £4.20</p>
            <table><tr><th>Thread</th><td>M8</td></tr><tr><th>Length</th><td>20mm</td></tr></table>
            <img src="/img/big.jpg" alt="Product photo"><img src="data:image/png;base64,xx" alt="inline">
            <ul><li>Button head</li><li>BZP finish</li></ul></body></html>'''
        text, pictures = fetch.html_to_text(html, base_url='https://shop.example.com/p/1')
        self.assertIn('# M8 x 20mm Button Head Screw BZP', text)
        self.assertIn('description: Zinc plated button head screw', text)
        self.assertIn('| Thread | M8 |', text)
        self.assertIn('- BZP finish', text)
        self.assertIn('Pack of 100. Price £4.20', text)
        self.assertNotIn('alert(1)', text)
        self.assertEqual(text.count('Home'), 0)  # nav links are anchors, not paragraphs: dropped
        self.assertEqual(pictures, [
            {'url': 'https://shop.example.com/img/m8.jpg', 'alt': 'og:image'},
            {'url': 'https://shop.example.com/img/big.jpg', 'alt': 'Product photo'},
        ])
