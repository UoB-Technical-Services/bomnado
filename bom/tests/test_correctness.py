from collections import Counter

from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bom.models import Part, PartSource, SubAssembly, SubAssemblyLineItem
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory
from bom.views import redirect_back_with_message


class PartSourceRankTests(TestCase):

    def test_rank_is_cheapest_per_unit_first(self):
        part = PartFactory(picture=None)
        dear = PartSource.objects.create(part=part, partcode='dear', rrp=10.0, shipping=0, minimum_order=1, lead_time=1)
        cheap = PartSource.objects.create(part=part, partcode='cheap', rrp=1.0, shipping=0, minimum_order=1, lead_time=1)
        middle = PartSource.objects.create(part=part, partcode='mid', rrp=5.0, shipping=0, minimum_order=1, lead_time=1)

        ranked = PartSource.rank([dear, cheap, middle], quantity=10, include_shipping=False)
        self.assertEqual([s.partcode for s in ranked], ['cheap', 'mid', 'dear'])

    def test_rank_amortises_shipping_over_the_quantity(self):
        part = PartFactory(picture=None)
        cheap_unit = PartSource.objects.create(part=part, partcode='cheap-unit', rrp=2.0, shipping=10.0,
                                               minimum_order=1, lead_time=1)
        free_ship = PartSource.objects.create(part=part, partcode='free-ship', rrp=3.0, shipping=0,
                                              minimum_order=1, lead_time=1)

        # For one unit the 10.00 shipping dominates (12.00 vs 3.00)...
        self.assertEqual(PartSource.rank([cheap_unit, free_ship], 1, include_shipping=True)[0], free_ship)
        # ...over 100 units it is amortised (2.10 vs 3.00 per unit)...
        self.assertEqual(PartSource.rank([cheap_unit, free_ship], 100, include_shipping=True)[0], cheap_unit)
        # ...and ignoring shipping the cheaper unit price wins outright.
        self.assertEqual(PartSource.rank([cheap_unit, free_ship], 1, include_shipping=False)[0], cheap_unit)


class PartCreateFromUrlTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)
        self.url = reverse('bom:part_editor_create')

    def test_a_url_starts_a_part_with_a_supplier_row(self):
        response = self.client.post(self.url, {'url': 'https://any-supplier.example/item/1', 'team': self.team.id})

        part = Part.objects.get()
        self.assertRedirects(response, reverse('bom:part_editor_update', kwargs={'pk': part.id}),
                             fetch_redirect_response=False)
        self.assertEqual(part.team, self.team)
        self.assertEqual(part.spec, '')                       # the link lives on the source, not in the spec
        self.assertEqual(part.nature, Part.NATURE_STANDARD)
        self.assertEqual(list(part.sources.values_list('url', flat=True)), ['https://any-supplier.example/item/1'])

    def test_the_same_url_twice_lands_on_the_same_part(self):
        self.client.post(self.url, {'url': 'https://any-supplier.example/item/1', 'team': self.team.id})
        response = self.client.post(self.url, {'url': 'HTTPS://any-supplier.example/ITEM/1'.lower(), 'team': self.team.id})
        part = Part.objects.get()
        self.assertRedirects(response, reverse('bom:part_editor_update', kwargs={'pk': part.id}),
                             fetch_redirect_response=False)


class RedirectBackWithMessageTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, referer):
        request = self.factory.post('/part/new', HTTP_REFERER=referer)
        request.session = {}
        return request

    def test_unresolvable_referer_falls_back_to_default(self):
        request = self._request('https://example.com/no/such/page/')
        url = redirect_back_with_message(request, 'oops', default_url='/fallback/')
        self.assertEqual(str(url), '/fallback/')
        self.assertEqual(request.session['error_message'], 'oops')

    def test_garbage_referer_falls_back_to_default(self):
        request = self._request('not even a url')
        self.assertEqual(str(redirect_back_with_message(request, 'oops', default_url='/fallback/')), '/fallback/')

    def test_known_referer_is_used(self):
        part = PartFactory(picture=None)
        request = self._request(f'http://testserver/part/{part.id}')
        url = redirect_back_with_message(request, 'oops', default_url='/fallback/')
        self.assertEqual(str(url), reverse('bom:part_editor_update', kwargs={'pk': part.id}))


class CollectAndCountPartsTests(TestCase):
    """ Quantities multiply down the tree; the tree is walked once, not once per unit. """

    def _build(self, sub_qty, inner_qty):
        team = TeamFactory()
        root = SubAssemblyFactory(team=team, picture=None, is_toplevel=True)
        a = SubAssemblyFactory(team=team, picture=None, is_toplevel=False, project=root)
        b = SubAssemblyFactory(team=team, picture=None, is_toplevel=False, project=root)
        p = PartFactory(team=team, picture=None)
        q = PartFactory(team=team, picture=None)

        SubAssemblyLineItem.objects.create(subassembly=root, child_subassembly=a, quantity=sub_qty)
        SubAssemblyLineItem.objects.create(subassembly=a, child_part=p, quantity=2)
        SubAssemblyLineItem.objects.create(subassembly=a, child_subassembly=b, quantity=inner_qty)
        SubAssemblyLineItem.objects.create(subassembly=b, child_part=q, quantity=5)
        return root, a, b, p, q

    def test_counts_multiply_through_nested_assemblies(self):
        root, a, b, p, q = self._build(sub_qty=3, inner_qty=4)
        parts, assemblies = Counter(), Counter()

        root.collect_and_count_parts(parts, assemblies)

        self.assertEqual(parts, Counter({p: 3 * 2, q: 3 * 4 * 5}))
        self.assertEqual(assemblies, Counter({a: 3, b: 3 * 4}))

    def test_query_count_is_independent_of_quantities(self):
        small, *_ = self._build(sub_qty=1, inner_qty=1)
        large, *_ = self._build(sub_qty=500, inner_qty=500)

        with CaptureQueriesContext(connection) as small_queries:
            small.collect_and_count_parts(Counter(), Counter())
        with CaptureQueriesContext(connection) as large_queries:
            large.collect_and_count_parts(Counter(), Counter())

        self.assertEqual(len(small_queries), len(large_queries))


class AssemblyEditorTreeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def _project(self, team, depth=3):
        root = SubAssemblyFactory(team=team, picture=None, is_toplevel=True)
        parent = root
        for _ in range(depth):
            child = SubAssemblyFactory(team=team, picture=None, is_toplevel=False, project=root)
            SubAssemblyLineItem.objects.create(subassembly=parent, child_subassembly=child, quantity=1)
            parent = child
        return root

    def _editor(self, assembly):
        return reverse('bom:assembly_editor_update', kwargs={'pk': assembly.id})

    def _tree_references(self, node):
        refs = {node['assembly'].reference}
        for child in node['children']:
            refs |= self._tree_references(child)
        return refs

    def test_tree_only_contains_this_teams_assemblies(self):
        mine = self._project(self.team)
        other = self._project(TeamFactory())

        response = self.client.get(self._editor(mine))

        self.assertEqual(response.status_code, 200)
        refs = self._tree_references(response.context['tree'])
        self.assertIn(mine.reference, refs)
        self.assertEqual(len(refs), 4)
        self.assertNotIn(other.reference, refs)
        self.assertFalse(any(other.reference in self._tree_references(o) for o in response.context['orphans']))

    def test_query_count_does_not_grow_with_other_teams_data(self):
        mine = self._project(self.team)

        with CaptureQueriesContext(connection) as before:
            self.client.get(self._editor(mine))

        for _ in range(5):
            self._project(TeamFactory(), depth=10)

        with CaptureQueriesContext(connection) as after:
            self.client.get(self._editor(mine))

        self.assertEqual(len(before), len(after))

    def test_query_count_does_not_grow_with_tree_depth(self):
        shallow = self._project(self.team, depth=1)
        deep = self._project(self.team, depth=12)

        with CaptureQueriesContext(connection) as shallow_queries:
            self.client.get(self._editor(shallow))
        with CaptureQueriesContext(connection) as deep_queries:
            self.client.get(self._editor(deep))

        # The tree itself is built from one query; the rest of the page is constant.
        self.assertEqual(len(shallow_queries), len(deep_queries))

    def test_orphaned_subassembly_without_project_renders(self):
        orphan = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=False, project=None)
        part = PartFactory(team=self.team, picture=None)
        SubAssemblyLineItem.objects.create(subassembly=orphan, child_part=part, quantity=2)

        response = self.client.get(self._editor(orphan))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tree']['assembly'], orphan)
        self.assertTrue(response.context['tree']['selected'])
        self.assertEqual(response.context['orphans'], [])

    def test_unused_subassemblies_listed_as_orphans(self):
        root = self._project(self.team, depth=1)
        loose = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=False, project=root)

        response = self.client.get(self._editor(root))

        self.assertEqual([o['assembly'] for o in response.context['orphans']], [loose])
        self.assertIsNotNone(SubAssembly.objects.get(pk=loose.pk).project)

