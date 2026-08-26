""" The library: statuses from data, and the searchable, filterable lists the editors show. """
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from bom import library
from bom.models import Feedback, PartSource, SubAssemblyLineItem
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory


class LibraryTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw', first_name='Alice')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def complete(self, **kwargs):
        part = PartFactory(team=self.team, kgs=0.1, dimensions='10 x 10 x 10', **kwargs)
        PartSource.objects.create(part=part, supplier='RS', rrp=1.5)
        return part


class StatusTests(LibraryTestCase):

    def test_statuses_in_order_of_importance(self):
        part = self.complete(reference='OK')
        self.assertEqual((library.part_status(part).label, library.part_status(part).tone), ('Complete', 'ok'))
        light = PartFactory(team=self.team, reference='LIGHT', kgs=0, dimensions='', picture=None, sale_code='', colour='')
        status = library.part_status(light)
        self.assertEqual((status.label, status.tone, status.missing), ('Missing price', 'warn', ['price', 'picture']))
        light.sale_code = 'L1'   # sold on its own: a buyer also needs weight, dimensions and colour
        status = library.part_status(light)
        self.assertEqual((status.label, status.missing), ('Missing weight', ['weight', 'dimensions', 'colour', 'price', 'picture']))
        light.sale_code = ''
        Feedback.objects.create(content_object=light, text='Check the thread', author=self.user)
        light.refresh_from_db()
        self.assertEqual(library.part_status(light).label, 'Needs review')
        light.deprecated = now()
        self.assertEqual(library.part_status(light).tone, 'muted')

    def test_assembly_status(self):
        empty = SubAssemblyFactory(team=self.team, picture=None)
        self.assertEqual(library.assembly_status(empty).label, 'Empty')
        SubAssemblyLineItem.objects.create(subassembly=empty, child_part=self.complete(), quantity=1)
        self.assertEqual(library.assembly_status(empty).label, 'Complete')


class ListTests(LibraryTestCase):

    def test_search_filter_and_privacy(self):
        nut = self.complete(reference='M8-NUT-BZP', name='M8 nut')
        bolt = PartFactory(team=self.team, reference='M8-20MM-BOLT', name='M8 bolt', kgs=0, picture=None)
        Feedback.objects.create(content_object=bolt, text='?', author=self.user)
        PartFactory(team=TeamFactory(), reference='M8-THEIRS', picture=None)
        url = reverse('bom:library_parts')

        html = self.client.get(url).content.decode()
        self.assertIn('M8-NUT-BZP', html)
        self.assertIn('M8-20MM-BOLT', html)
        self.assertNotIn('M8-THEIRS', html)
        self.assertNotIn('>Complete<', html)                                 # complete is silent
        self.assertIn('>Needs review<', html)                                 # broken is noisy

        html = self.client.get(url + '?q=m8+nut').content.decode()
        self.assertIn('M8-NUT-BZP', html)
        self.assertNotIn('M8-20MM-BOLT', html)
        self.assertIn('value="m8 nut"', html)

        html = self.client.get(url + '?which=attention').content.decode()
        self.assertNotIn('M8-NUT-BZP', html)
        self.assertIn('M8-20MM-BOLT', html)
        self.assertIn('bn-pill active" hx-get="/library/parts/?which=attention', html)

        html = self.client.get(url + f'?selected=part:{nut.id}').content.decode()
        self.assertIn(f'bn-row is-selected" href="/part/{nut.id}" aria-current="page"', html)
        # Rows swap the main region in place (the library and the drawer stay); the search box is not re-rendered
        # on a search (so it keeps focus): only the results are.
        self.assertIn(f'hx-get="/part/{nut.id}" hx-target="#app_main" hx-select="#app_main"', html)
        self.assertIn('hx-target="#library_results" hx-select="#library_results"', html)
        self.assertIn(f'name="selected" value="part:{nut.id}"', html)

    def test_pages(self):
        for index in range(library.PAGE_SIZE + 2):
            PartFactory(team=self.team, reference=f'P-{index:02d}', picture=None)
        html = self.client.get(reverse('bom:library_parts')).content.decode()
        self.assertIn('1 / 2', html)
        self.assertIn('page=2', html)
        self.assertNotIn('P-13', html)
        html = self.client.get(reverse('bom:library_parts') + '?page=2').content.decode()
        self.assertIn('P-13', html)

    def test_assemblies_list(self):
        project = SubAssemblyFactory(team=self.team, reference='BOX', name='A box', is_toplevel=True, picture=None)
        SubAssemblyFactory(team=self.team, reference='LID', name='A lid', picture=None)   # pinned names: a random one can contain "box"
        html = self.client.get(reverse('bom:library_assemblies') + '?q=box').content.decode()
        self.assertIn('BOX', html)
        self.assertNotIn('>LID<', html)
        self.assertIn('>project<', html)
        self.assertIn(f'href="/assembly/{project.id}"', html)

    def test_tree(self):
        box = SubAssemblyFactory(team=self.team, reference='BOX', is_toplevel=True, picture=None)
        lid = SubAssemblyFactory(team=self.team, reference='LID', picture=None, project=box, is_toplevel=False)
        hinge = SubAssemblyFactory(team=self.team, reference='HINGE', picture=None, project=box, is_toplevel=False)
        SubAssemblyFactory(team=self.team, reference='LOOSE', picture=None, is_toplevel=False)
        SubAssemblyLineItem.objects.create(subassembly=box, child_subassembly=lid, quantity=1)
        SubAssemblyLineItem.objects.create(subassembly=lid, child_subassembly=hinge, quantity=2)
        roots, orphans = library.assembly_tree(self.user, selected_id=hinge.id)
        self.assertEqual([r['assembly'].reference for r in roots], ['BOX'])
        self.assertEqual(roots[0]['children'][0]['assembly'].reference, 'LID')
        self.assertEqual(roots[0]['children'][0]['children'][0]['selected'], True)
        self.assertTrue(roots[0]['expanded'] and roots[0]['children'][0]['expanded'])
        self.assertEqual([o['assembly'].reference for o in orphans], ['LOOSE'])
        # A search keeps only the branches that lead to a match.
        roots, orphans = library.assembly_tree(self.user, query='hinge')
        self.assertEqual(roots[0]['children'][0]['children'][0]['assembly'].reference, 'HINGE')
        self.assertEqual(orphans, [])
        html = self.client.get(reverse('bom:library_assemblies') + f'?view=tree&selected=assembly:{hinge.id}').content.decode()
        self.assertIn('bn-tree-node is-selected', html)
        self.assertIn('Not in any project', html)
        self.assertIn(f'hx-get="/assembly/{lid.id}" hx-target="#app_main"', html)

    def test_assembly_editor_has_the_same_shape(self):
        box = SubAssemblyFactory(team=self.team, reference='BOX', name='A box', is_toplevel=True, picture=None)
        html = self.client.get(reverse('bom:assembly_editor_update', kwargs={'pk': box.id})).content.decode()
        self.assertIn('id="library"', html)
        self.assertIn('+ New assembly', html)
        self.assertNotIn('bn-library-tabs', html)                           # no context switch in the library
        self.assertIn('bn-tree-node is-selected', html)                      # opens on the tree, this branch unfolded
        self.assertIn('<h1 class="bn-editor-title">A box</h1>', html)
        self.assertIn('href="#sec-bom">Bill of materials</a>', html)
        self.assertNotIn('aiChatFloat', html)                                 # the drawer is the window; no pop-out
        self.assertIn('<div class="bn-resizer" data-resize="library"', html)
        # Every section sits inside the editor column: the form closes after Lifecycle, nothing escapes.
        form_end = html.index('</form>', html.index('id="sec-usage"'))
        self.assertLess(form_end, html.index('id="sec-history"'))
        self.assertIn('hx-post="/assembly/%d" hx-encoding="multipart/form-data" hx-target="#app_main"' % box.id, html)
        self.assertIn(f'data-ai-context="assembly:{box.id}" data-ai-reference="BOX"', html)
        # The page's behaviour is a static module named by data-page; the template carries data, not scripts.
        self.assertIn('data-page="assembly-editor" data-assembly-id="%d"' % box.id, html)
        self.assertIn('data-url-line-add="/assembly/%d/line_items/add"' % box.id if '/line_items/add' in html else 'data-url-line-add="', html)
        self.assertNotIn('<script type="text/x-bomnado-page"', html)
        self.assertNotIn('onclick="delete', html)
        self.assertIn('data-action="delete-assembly"', html)
        self.assertIn('data-action="find-unreferenced"', html)
        self.assertIn('class="bn-legend"', html)   # what the dots mean, under the BOM
        self.assertNotIn('🙋', html)
        self.assertNotIn('[Needs review]', html)  # one mark, from one place (ATTENTION_MARK)
        # The "+ New assembly" form offers to put the new one under this assembly, and the KiCad import.
        self.assertIn(f'<input name="parent" type="hidden" value="{box.id}">', html)
        self.assertIn('name="csv_file"', html)

    def test_the_marks_come_from_one_place(self):
        from bom.templatetags.utils import stylised_part
        part = PartFactory(team=self.team, reference='LOOK', picture=None)
        Feedback.objects.create(content_object=part, text='?', author=self.user)
        part.refresh_from_db()
        self.assertEqual([kind for kind, _ in library.marks(part)], ['bad', 'warn', 'sale'])
        self.assertIn('bn-mark is-bad', stylised_part(part))
        html = self.client.get(reverse('bom:part_editor_update', kwargs={'pk': part.id})).content.decode()
        self.assertIn('marks: {"bad": "Needs review"', html)   # the browser builds the same dots

    def test_editor_pages_carry_the_library(self):
        part = self.complete(reference='M8-NUT-BZP')
        html = self.client.get(reverse('bom:part_editor_update', kwargs={'pk': part.id})).content.decode()
        self.assertIn('id="library"', html)
        self.assertIn('bn-row is-selected', html)
        self.assertIn('+ New part', html)
        self.assertNotIn('partsTable', html)  # the DataTables list is gone
        self.assertIn('hx-post="/part/%d" hx-encoding="multipart/form-data" hx-target="#app_main"' % part.id, html)
        self.assertIn('id="editorMore"', html)
        self.assertIn('data-page="part-editor" data-part-id="%d" data-part-reference="M8-NUT-BZP"' % part.id, html)
        self.assertNotIn('<script type="text/x-bomnado-page"', html)
        self.assertNotIn('onclick="', html.split('id="part-editor"')[1])
        self.assertIn('data-action="delete-source" data-id="', html)
        self.assertIn('>Duplicate part</button>', html)
        self.assertIn('>Delete part</button>', html)
        self.assertIn('id="sec-lifecycle"', html)   # the part keeps its dates there
        self.assertIn(f'data-ai-context="part:{part.id}" data-ai-reference="M8-NUT-BZP"', html)
        self.assertNotIn('🙋', html)
        self.assertNotIn('[Needs review]', html)  # one mark, from one place (ATTENTION_MARK)
        self.assertEqual(self.client.get(reverse('bom:library_parts')).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('bom:library_parts')).status_code, 302)
