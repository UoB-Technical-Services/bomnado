""" The pages around the AI: the New Part panel without it, the window and its jumping-off points with it. """

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bom.models import Part, PartSource, Team, UserAISettings
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory

KEY = 'sk-ant-api03-' + 'x' * 40 + 'wxyz'


class AIViewTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)
        self.create_url = reverse('bom:part_editor_create')

    def configure(self):
        config = UserAISettings(user=self.user)
        config.api_key = KEY
        config.save()
        self.user.refresh_from_db()


class NewPartPanelTests(AIViewTestCase):

    def test_a_reference_makes_a_blank_part(self):
        response = self.client.post(self.create_url, {'url': 'm8-nut-bzp', 'team': self.team.id})
        part = Part.objects.get(reference='M8-NUT-BZP')
        self.assertRedirects(response, reverse('bom:part_editor_update', kwargs={'pk': part.id}), fetch_redirect_response=False)
        self.assertEqual(part.sources.count(), 1)  # the blank supplier row

    def test_a_link_becomes_the_first_supplier_row(self):
        self.client.post(self.create_url, {'url': 'https://unknown.example/p/1', 'team': self.team.id})
        self.assertEqual(PartSource.objects.get().url, 'https://unknown.example/p/1')

    def test_panel_offers_the_ai_only_when_configured(self):
        part = PartFactory(team=self.team, picture=None)
        html = self.client.get(reverse('bom:part_editor_update', kwargs={'pk': part.id})).content.decode()
        self.assertNotIn('data-ai-prompt', html)
        self.assertNotIn('id="aiChat"', html)
        self.assertNotIn('Ingest', html)
        self.configure()
        html = self.client.get(reverse('bom:part_editor_update', kwargs={'pk': part.id})).content.decode()
        self.assertIn('data-ai-prompt="Create a part from this link: "', html)
        self.assertIn('Find suppliers', html)
        self.assertIn('Draft QC steps', html)
        self.assertIn(f'data-ai-context="part:{part.id}"', html)
        self.assertIn('id="aiChat"', html)             # the window
        self.assertIn('id="aiChatToggle"', html)       # the top-bar button
        self.assertIn('app/ai_chat.js', html)
        self.assertIn('app/ai_tornado.js', html)  # the signature animation

    def test_assembly_page_has_its_own_jumping_off_points(self):
        self.configure()
        assembly = SubAssemblyFactory(team=self.team, picture=None)
        html = self.client.get(reverse('bom:assembly_editor_update', kwargs={'pk': assembly.id})).content.decode()
        self.assertIn(f'data-ai-context="assembly:{assembly.id}"', html)
        self.assertIn('Check this BOM for gaps', html)
        self.assertIn('Draft instructions from the line items', html)

    def test_other_teams_cannot_be_used(self):
        other = TeamFactory()
        response = self.client.post(self.create_url, {'url': 'X', 'team': other.id})
        self.assertEqual(response.status_code, 403)


class NamingGuideTests(AIViewTestCase):

    def test_owner_sets_the_guide_from_the_teams_page(self):
        response = self.client.post(reverse('bom:teams_naming_guide', kwargs={'pk': self.team.id}),
                                    {'naming_guide': 'Bolts are BOLT-<size>.'})
        self.assertRedirects(response, reverse('bom:teams'), fetch_redirect_response=False)
        self.assertEqual(Team.objects.get(pk=self.team.pk).naming_guide, 'Bolts are BOLT-<size>.')
        html = self.client.get(reverse('bom:teams')).content.decode()
        self.assertIn('Bolts are BOLT-&lt;size&gt;.', html)

    def test_only_the_owner(self):
        bob = User.objects.create_user(username='bob', email='bob@example.com', password='password123')
        self.team.users.add(bob)
        self.client.force_login(bob)
        response = self.client.post(reverse('bom:teams_naming_guide', kwargs={'pk': self.team.id}), {'naming_guide': 'x'})
        self.assertEqual(response.status_code, 403)
