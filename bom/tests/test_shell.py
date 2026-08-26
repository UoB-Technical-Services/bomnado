""" Every page keeps the shell whole: the library, the main region and the AI drawer are the shell's own children.

A stray closing tag in a page template silently closes <main> and the shell early, and the drawer then lands
under the page as a block (the "AI in a window on the Teams page" bug). This parses each page and checks. """
from html.parser import HTMLParser

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bom.models import UserAISettings
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Parents(HTMLParser):
    """ Records the parent element's id of every element that has an id. """

    def __init__(self):
        super().__init__()
        self.stack = []
        self.parent_of = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.parent_of[attrs['id']] = next((i for t, i in reversed(self.stack) if i), None)
        if tag not in VOID:
            self.stack.append((tag, attrs.get('id')))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


class ShellTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        config = UserAISettings(user=self.user)                                  # so the drawer is rendered
        config.api_key = 'sk-ant-test'
        config.save()
        self.client.force_login(self.user)

    def test_the_drawer_is_in_the_shell_on_every_page(self):
        box = SubAssemblyFactory(team=self.team, reference='BOX', is_toplevel=True, picture=None)
        part = PartFactory(team=self.team, reference='NUT', picture=None)
        pages = [reverse('bom:start'), reverse('bom:teams'), reverse('bom:user_settings'), reverse('bom:ai_jobs'),
                 reverse('bom:part_editor_update', kwargs={'pk': part.id}), reverse('bom:assembly_editor_update', kwargs={'pk': box.id})]
        tools = ('bom:tools_reviews', 'bom:tools_production_phases', 'bom:tools_orphan_finder', 'bom:tools_sales_codes', 'bom:tools_deals')
        pages += [reverse(name, kwargs={'pk': box.id}) for name in tools]
        for url in pages:
            html = self.client.get(url).content.decode()
            parser = Parents()
            parser.feed(html)
            self.assertEqual(parser.parent_of.get('app_drawer'), 'app_shell', url)
            self.assertEqual(parser.parent_of.get('app_main'), 'app_shell', url)
            self.assertEqual(parser.parent_of.get('app_library'), 'app_shell', url)

    def test_the_tools_belong_to_their_project(self):
        box = SubAssemblyFactory(team=self.team, reference='BOX', is_toplevel=True, picture=None)
        for name in ('bom:tools_reviews', 'bom:tools_production_phases', 'bom:tools_orphan_finder', 'bom:tools_sales_codes', 'bom:tools_deals'):
            html = self.client.get(reverse(name, kwargs={'pk': box.id})).content.decode()
            self.assertIn(f'<a href="{reverse("bom:assembly_editor_update", kwargs={"pk": box.id})}">BOX</a>', html, name)


class AuthPagesTests(TestCase):

    def test_sign_in_and_reset_pages_share_the_card(self):
        for url, title in (('/accounts/login/', 'Sign in'), ('/accounts/password_reset/', 'Reset your password'),
                           ('/accounts/password_reset/done/', 'Check your email'), ('/accounts/reset/done/', 'Password set')):
            html = self.client.get(url).content.decode()
            self.assertIn('class="bn-auth-card"', html, url)
            self.assertIn(f'<h1>{title}</h1>', html, url)
            self.assertIn('class="app-topbar"', html, url)

    def test_a_wrong_password_says_so(self):
        User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        html = self.client.post('/accounts/login/', {'username': 'alice@example.com', 'password': 'nope'}).content.decode()
        self.assertIn('did not match', html)
