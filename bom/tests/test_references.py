""" References look the same everywhere: an underline by kind, marks for state, from one renderer. """
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from bom import library
from bom.templatetags.markdown_render import as_markdown
from bom.templatetags.utils import reference_html, stylised_assembly, stylised_part
from bom.models import Feedback, PartSource
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory


class ReferenceTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def test_a_complete_part_is_just_an_underlined_link(self):
        part = PartFactory(team=self.team, reference='M8-NUT-BZP', name='M8 nut', kgs=0.1, dimensions='1 x 1 x 1', sale_code='', deprecated=None)
        PartSource.objects.create(part=part, supplier='RS', rrp=0.1)
        html = stylised_part(part)
        self.assertEqual(html, f'<a class="bn-ref is-part bomlink part" href="/part/{part.id}" title="M8 nut"><span class="reference">M8-NUT-BZP</span></a>')

    def test_marks_follow_the_state(self):
        part = PartFactory(team=self.team, reference='LOOK', name='Look', kgs=0, dimensions='', colour='', picture=None, sale_code='S1', deprecated=now())
        Feedback.objects.create(content_object=part, text='?', author=self.user)
        part.refresh_from_db()
        html = stylised_part(part)
        self.assertIn('bn-ref is-part bomlink part is-deprecated', html)
        self.assertIn('<span class="bn-mark is-bad" title="Needs review" aria-label="Needs review"></span>', html)
        self.assertIn('<span class="bn-mark is-warn" title="Missing weight, dimensions, colour, price, picture"', html)
        self.assertIn('<span class="bn-tag" title="Sale code S1">sale</span>', html)
        self.assertIn('title="Look; Deprecated ', html)
        for emoji in ('\U0001F440', '\u26a0', '\U0001F4D1', '<kbd'):
            self.assertNotIn(emoji, html)

    def test_assemblies_are_blue_and_never_missing_data(self):
        box = SubAssemblyFactory(team=self.team, reference='BOX', name='A box', is_toplevel=True, picture=None, sale_code='', deprecated=None)
        self.assertEqual(stylised_assembly(box), f'<a class="bn-ref is-assembly bomlink assembly" href="/assembly/{box.id}" title="A box"><span class="reference">BOX</span></a>')
        self.assertEqual(library.marks(box), [])
        self.assertIn('is-assembly', reference_html(box))

    def test_markdown_renders_references_the_same_way(self):
        part = PartFactory(team=self.team, reference='M8-NUT-BZP', name='M8 nut', kgs=0, picture=None, deprecated=None, sale_code='')
        html = as_markdown('Fit the `M8-NUT-BZP` now.', None)
        self.assertIn(f'<a class="bn-ref is-part bomlink part" href="/part/{part.id}" title="M8 nut"><span class="reference">M8-NUT-BZP</span><span class="bn-mark is-warn"', html)

    def test_pages_have_no_boxes_or_emoji_marks(self):
        part = PartFactory(team=self.team, reference='M8-NUT-BZP', picture=None, sale_code='S1')
        box = SubAssemblyFactory(team=self.team, reference='BOX', is_toplevel=True, picture=None)
        Feedback.objects.create(content_object=part, text='?', author=self.user)
        for url in (reverse('bom:part_editor_update', kwargs={'pk': part.id}), reverse('bom:assembly_editor_update', kwargs={'pk': box.id}),
                    reverse('bom:tools_reviews', kwargs={'pk': box.id}), reverse('bom:library_parts'), reverse('bom:library_search') + '?q=m8'):
            html = self.client.get(url).content.decode()
            self.assertNotRegex(html, r'bomlink [a-z]+" href="[^"]*"><kbd', url)   # no boxed references anywhere
            for emoji in ('\U0001F440', '\U0001F4D1', '\U0001F529', '\U0001F4E6'):
                self.assertNotIn(emoji, html, url)
            if 'tools/reviews' not in url:   # an empty project lists nothing
                self.assertIn('bn-ref is-', html, url)

    def test_search_api_says_what_is_missing(self):
        part = PartFactory(team=self.team, reference='M8-NUT-BZP', name='M8 nut', kgs=0, dimensions='', picture=None, sale_code='')
        data = self.client.get('/api/parts/search/?search=m8', HTTP_ACCEPT='application/json').json()
        self.assertEqual((data[0]['id'], data[0]['reference']), (part.id, 'M8-NUT-BZP'))
        self.assertEqual(data[0]['missing'], ['price', 'picture'])           # no sale code: weight etc. optional
