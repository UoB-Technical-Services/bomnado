from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bom.models import SubAssemblyLineItem
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory

FRAGMENT_ROOT = 'id="existingsubComponentsContainer"'
# Markup that only the full editor page has - the tree, the two-pane layout, the <html> shell.
FULL_PAGE_MARKERS = ('<html', 'id="app_left"', 'tree_assembly_', 'id="bomando-assembly-form"')


class AssemblyLineItemFragmentTests(TestCase):
    """ Adding and removing line items returns just the line-items table, never the page. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

        self.root = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, reference='ROOT')
        self.sub = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=False, project=self.root,
                                      reference='SUB')
        self.part = PartFactory(team=self.team, picture=None, reference='M8-NUT')
        self.add_url = reverse('bom:assembly_line_item_add', kwargs={'pk': self.root.id})

    def _delete_url(self, line):
        return reverse('bom:assembly_line_item_delete', kwargs={'pk': line.subassembly_id, 'line_id': line.id})

    def _assert_fragment(self, response):
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(FRAGMENT_ROOT, html)
        self.assertIn('name="line_items-TOTAL_FORMS"', html)
        for marker in FULL_PAGE_MARKERS:
            self.assertNotIn(marker, html)
        return html

    # --- adding ------------------------------------------------------------

    def test_add_part_returns_fragment_with_new_row(self):
        response = self.client.post(self.add_url, {'child_part': self.part.id})

        html = self._assert_fragment(response)
        line = SubAssemblyLineItem.objects.get(subassembly=self.root)
        self.assertEqual(line.child_part, self.part)
        self.assertEqual(line.quantity, 1)
        self.assertIn('M8-NUT', html)
        self.assertNotIn('id="lineItemError"', html)

    def test_add_assembly_with_quantity(self):
        response = self.client.post(self.add_url, {'child_subassembly': self.sub.id, 'quantity': '4'})

        html = self._assert_fragment(response)
        line = SubAssemblyLineItem.objects.get(subassembly=self.root)
        self.assertEqual(line.child_subassembly, self.sub)
        self.assertEqual(line.quantity, 4)
        self.assertIn('SUB', html)

    def test_adding_does_not_build_the_tree(self):
        """ The fragment is cheap: far fewer queries than the full editor page, and no tree. """
        for i in range(6):
            child = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=False, project=self.root)
            SubAssemblyLineItem.objects.create(subassembly=self.root, child_subassembly=child, quantity=1)

        with CaptureQueriesContext(connection) as page_queries:
            page = self.client.get(reverse('bom:assembly_editor_update', kwargs={'pk': self.root.id}))
        with CaptureQueriesContext(connection) as fragment_queries:
            fragment = self.client.post(self.add_url, {'child_part': self.part.id})

        self._assert_fragment(fragment)
        self.assertLess(len(fragment.content), len(page.content) / 2)
        self.assertLess(len(fragment_queries), len(page_queries))

    def test_circular_add_shows_inline_error_and_creates_nothing(self):
        SubAssemblyLineItem.objects.create(subassembly=self.root, child_subassembly=self.sub, quantity=1)

        response = self.client.post(reverse('bom:assembly_line_item_add', kwargs={'pk': self.sub.id}),
                                    {'child_subassembly': self.root.id})

        html = self._assert_fragment(response)
        self.assertIn('id="lineItemError"', html)
        self.assertIn('circular reference', html)
        self.assertFalse(SubAssemblyLineItem.objects.filter(subassembly=self.sub).exists())

    def test_self_add_shows_inline_error(self):
        response = self.client.post(self.add_url, {'child_subassembly': self.root.id})
        html = self._assert_fragment(response)
        self.assertIn('circular reference', html)
        self.assertFalse(SubAssemblyLineItem.objects.exists())

    def test_missing_item_shows_inline_error(self):
        html = self._assert_fragment(self.client.post(self.add_url, {}))
        self.assertIn('Choose a part or assembly to insert.', html)
        self.assertFalse(SubAssemblyLineItem.objects.exists())

    def test_cannot_insert_another_teams_part(self):
        foreign = PartFactory(picture=None, reference='FOREIGN')
        html = self._assert_fragment(self.client.post(self.add_url, {'child_part': foreign.id}))
        self.assertIn('Choose a part or assembly to insert.', html)
        self.assertNotIn('FOREIGN', html)
        self.assertFalse(SubAssemblyLineItem.objects.exists())

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.add_url).status_code, 405)

    def test_non_member_is_forbidden(self):
        outsider = User.objects.create_user(username='bob', email='bob@example.com', password='password123')
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(self.add_url, {'child_part': self.part.id}).status_code, 403)
        self.assertFalse(SubAssemblyLineItem.objects.exists())

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(self.add_url, {'child_part': self.part.id})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    # --- removing ----------------------------------------------------------

    def test_delete_returns_fragment_without_row(self):
        line = SubAssemblyLineItem.objects.create(subassembly=self.root, child_part=self.part, quantity=2)
        other = SubAssemblyLineItem.objects.create(subassembly=self.root, child_subassembly=self.sub, quantity=1)

        html = self._assert_fragment(self.client.post(self._delete_url(line)))

        self.assertFalse(SubAssemblyLineItem.objects.filter(pk=line.pk).exists())
        self.assertTrue(SubAssemblyLineItem.objects.filter(pk=other.pk).exists())
        self.assertNotIn('M8-NUT', html)
        self.assertIn('SUB', html)

    def test_delete_line_of_another_assembly_is_not_found(self):
        line = SubAssemblyLineItem.objects.create(subassembly=self.sub, child_part=self.part, quantity=1)
        url = reverse('bom:assembly_line_item_delete', kwargs={'pk': self.root.id, 'line_id': line.id})
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(SubAssemblyLineItem.objects.filter(pk=line.pk).exists())

    def test_delete_get_is_not_allowed(self):
        line = SubAssemblyLineItem.objects.create(subassembly=self.root, child_part=self.part, quantity=1)
        self.assertEqual(self.client.get(self._delete_url(line)).status_code, 405)


class AssemblyEditorPageTests(TestCase):
    """ The editor page still embeds the fragment, and the full-form save path is unchanged. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)
        self.root = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, reference='ROOT',
                                       revision='1.0.0')
        self.part = PartFactory(team=self.team, picture=None, reference='M8-NUT')
        self.line = SubAssemblyLineItem.objects.create(subassembly=self.root, child_part=self.part, quantity=2)
        self.url = reverse('bom:assembly_editor_update', kwargs={'pk': self.root.id})

    def test_page_embeds_fragment_and_htmx(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn(FRAGMENT_ROOT, html)
        self.assertIn('M8-NUT', html)
        self.assertIn('htmx.min.js', html)
        self.assertIn('hx-headers', html)
        self.assertIn(reverse('bom:assembly_line_item_add', kwargs={'pk': self.root.id}), html)

    def test_full_form_post_still_saves_line_item_quantities(self):
        """ The non-htmx path: the whole form, including the inline formset, is posted as before. """
        data = {
            'reference': 'ROOT', 'name': self.root.name, 'revision': '1.0.0', 'is_toplevel': 'on',
            'instructions': self.root.instructions, 'qc_steps': '', 'spec': '', 'production_phase': '',
            'review_notes': '', 'sale_code': '', 'hs_code': '', 'deprecated': '',
            'line_items-TOTAL_FORMS': '1', 'line_items-INITIAL_FORMS': '1',
            'line_items-MIN_NUM_FORMS': '0', 'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-id': self.line.id, 'line_items-0-child_part': self.part.id,
            'line_items-0-child_subassembly': '', 'line_items-0-quantity': '7', 'line_items-0-notes': 'seven',
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, 7)
        self.assertEqual(self.line.notes, 'seven')
