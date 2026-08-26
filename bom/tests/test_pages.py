""" The pages without a record share the shell's header and width, and the search overlay finds things. """
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bom.models import Feedback, PartSource, SubAssemblyLineItem
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory


class PagesTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw', first_name='Alice')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def test_pages_share_the_header(self):
        box = SubAssemblyFactory(team=self.team, reference='BOX', is_toplevel=True, picture=None)
        tools = {'pk': box.id}
        for name, kwargs, title in (('bom:tools_production_phases', tools, 'Production phases'), ('bom:tools_sales_codes', tools, 'Sales items'),
                                    ('bom:tools_orphan_finder', tools, 'Orphans'), ('bom:tools_deals', tools, 'Supplier deals'),
                                    ('bom:teams', {}, 'Teams'), ('bom:user_settings', {}, 'Settings'), ('bom:ai_jobs', {}, 'AI activity'),
                                    ('bom:start', {}, 'Dashboard')):
            html = self.client.get(reverse(name, kwargs=kwargs)).content.decode()
            self.assertIn('class="app-page', html, name)
            self.assertIn(f'<h1 class="bn-page-title">{title}</h1>', html, name)
            self.assertNotIn('min-width: 600px', html, name)
            self.assertNotIn('🙋', html, name)
            self.assertNotIn('icon-line', html, name)

    def test_reviews_tool_lists_what_needs_a_look_in_the_project(self):
        box = SubAssemblyFactory(team=self.team, reference='BOX', is_toplevel=True, picture=None)
        lid = SubAssemblyFactory(team=self.team, reference='LID', picture=None, is_toplevel=False)
        nut = PartFactory(team=self.team, reference='NUT', name='A nut', kgs=0, dimensions='1 x 1 x 1', sale_code='N1')
        PartSource.objects.create(part=nut, supplier='RS', rrp=0.1)
        fine = PartFactory(team=self.team, reference='FINE', kgs=0.1, dimensions='1 x 1 x 1')
        PartSource.objects.create(part=fine, supplier='RS', rrp=0.1)
        elsewhere = PartFactory(team=self.team, reference='ELSEWHERE', picture=None)
        SubAssemblyLineItem.objects.create(subassembly=box, child_subassembly=lid, quantity=1)
        SubAssemblyLineItem.objects.create(subassembly=lid, child_part=nut, quantity=4)
        SubAssemblyLineItem.objects.create(subassembly=lid, child_part=fine, quantity=1)
        Feedback.objects.create(content_object=nut, text='Check the thread', author=self.user)
        Feedback.objects.create(content_object=lid, text='Needs a drawing', author=self.user)
        Feedback.objects.create(content_object=elsewhere, text='Not in the box', author=self.user)
        html = self.client.get(reverse('bom:tools_reviews', kwargs={'pk': box.id})).content.decode()
        self.assertIn('<h1 class="bn-page-title">Reviews</h1>', html)
        self.assertIn('Check the thread', html)
        self.assertIn('Needs a drawing', html)
        self.assertNotIn('Not in the box', html)                     # a part outside the project
        self.assertIn('Missing weight', html)                        # the nut has no weight
        self.assertNotIn('>FINE<', html.split('Missing data')[1])    # complete parts are not listed as missing
        self.assertIn(reverse('bom:tools_reviews', kwargs={'pk': box.id}), self.client.get(reverse('bom:start')).content.decode())
        self.client.logout()
        self.assertEqual(self.client.get(reverse('bom:tools_reviews', kwargs={'pk': box.id})).status_code, 302)

    def test_search_overlay(self):
        part = PartFactory(team=self.team, reference='M8-NUT-BZP', name='M8 nut', kgs=0.1, dimensions='1 x 1 x 1')
        PartSource.objects.create(part=part, supplier='RS', rrp=0.1)
        box = SubAssemblyFactory(team=self.team, reference='NUT-BOX', name='A box of nuts', is_toplevel=True, picture=None)
        PartFactory(team=TeamFactory(), reference='M8-NUT-THEIRS', name='Not ours', picture=None)
        html = self.client.get(reverse('bom:start')).content.decode()
        self.assertIn('id="app_search_overlay"', html)
        self.assertNotIn('app_search_bar', html)  # the select2 dialog is gone
        html = self.client.get(reverse('bom:library_search') + '?q=nut').content.decode()
        self.assertIn(f'href="/part/{part.id}"', html)
        self.assertIn(f'href="/assembly/{box.id}"', html)
        self.assertNotIn('M8-NUT-THEIRS', html)
        self.assertIn('>Parts<', html)
        self.assertIn('>Assemblies<', html)
        self.assertIn('Type a reference', self.client.get(reverse('bom:library_search')).content.decode())
        self.assertIn('Nothing matches', self.client.get(reverse('bom:library_search') + '?q=zzz').content.decode())
