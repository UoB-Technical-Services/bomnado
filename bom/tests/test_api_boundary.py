""" The API is the wall between teams: another team's user can neither see nor touch your records.

Every route the router registers is tried from outside the team: list, retrieve, change, delete,
and create-under-your-parent. The wall is `get_queryset` (filtered: unknown ids 404) plus
create-time checks; these tests are the proof it stays up.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from bom.models import Deal, DealLineItem, Part, PartSource, SubAssembly, SubAssemblyLineItem
from bom.tests.factories import (DealFactory, DealLineItemFactory, PartFactory, PartSourceFactory,
                                 SubAssemblyFactory, TeamFactory)


class ApiBoundaryTestCase(TestCase):
    """ Alice's team owns a part, a source, an assembly, a line item and a deal. Eve is on another team. """

    def setUp(self):
        self.alice = User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        self.team = TeamFactory(owner=self.alice)
        self.team.users.add(self.alice)
        self.part = PartFactory(team=self.team, reference='ALICE-PART', picture=None)
        self.source = PartSourceFactory(part=self.part)
        self.assembly = SubAssemblyFactory(team=self.team, reference='ALICE-ASSY', is_toplevel=True, picture=None)
        self.line = SubAssemblyLineItem.objects.create(subassembly=self.assembly, child_part=self.part, quantity=1)
        self.deal = DealFactory(team=self.team, project=self.assembly)
        self.deal_line = DealLineItemFactory(deal=self.deal, part=self.part)

        self.eve = User.objects.create_user(username='eve', email='eve@example.com', password='pw')
        self.eve_team = TeamFactory(owner=self.eve)
        self.eve_team.users.add(self.eve)
        self.client.force_login(self.eve)

    def rows(self):
        """ (route, alice's record id) for every registered route. """
        return [('parts', self.part.id), ('partsources', self.source.id), ('subassemblies', self.assembly.id),
                ('subassemblylineitems', self.line.id), ('deals', self.deal.id), ('deallineitems', self.deal_line.id)]


class ReadBoundaryTests(ApiBoundaryTestCase):

    def test_lists_never_contain_another_teams_records(self):
        for route, pk in self.rows():
            body = self.client.get(f'/api/{route}/', HTTP_ACCEPT='application/json').content.decode()
            self.assertNotIn('ALICE', body, route)
            self.assertNotIn(f'"id":{pk}', body.replace(' ', ''), route)

    def test_retrieving_another_teams_record_is_a_404(self):
        for route, pk in self.rows():
            response = self.client.get(f'/api/{route}/{pk}/', HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, 404, route)

    def test_search_and_available_stay_inside_the_team(self):
        body = self.client.get('/api/parts/search/?search=ALICE', HTTP_ACCEPT='application/json').content.decode()
        self.assertNotIn('ALICE-PART', body)
        response = self.client.get(f'/api/subassemblies/{self.assembly.id}/available', follow=True)
        self.assertIn(response.status_code, (403, 404))

    def test_the_api_needs_a_login(self):
        self.client.logout()
        for route, pk in self.rows():
            response = self.client.get(f'/api/{route}/', HTTP_ACCEPT='application/json')
            self.assertIn(response.status_code, (401, 403), route)


class WriteBoundaryTests(ApiBoundaryTestCase):

    def test_changing_another_teams_record_is_a_404(self):
        for route, pk in self.rows():
            response = self.client.patch(f'/api/{route}/{pk}/', data='{"name": "EVE-WAS-HERE"}',
                                         content_type='application/json')
            self.assertEqual(response.status_code, 404, route)
        self.part.refresh_from_db()
        self.assertEqual(self.part.reference, 'ALICE-PART')

    def test_deleting_another_teams_record_is_a_404(self):
        for route, pk in self.rows():
            response = self.client.delete(f'/api/{route}/{pk}/')
            self.assertEqual(response.status_code, 404, route)
        for model, pk in ((Part, self.part.pk), (PartSource, self.source.pk), (SubAssembly, self.assembly.pk),
                          (SubAssemblyLineItem, self.line.pk), (Deal, self.deal.pk), (DealLineItem, self.deal_line.pk)):
            self.assertTrue(model.objects.filter(pk=pk).exists(), model.__name__)

    def test_creating_under_another_teams_parent_is_refused(self):
        attempts = [
            ('partsources', {'part': self.part.id, 'supplier': 'EVE', 'rrp': 1}),
            ('subassemblylineitems', {'subassembly': self.assembly.id, 'child_part': self.part.id, 'quantity': 1}),
            ('deallineitems', {'deal': self.deal.id, 'part': self.part.id, 'quantity': 1}),
        ]
        for route, payload in attempts:
            response = self.client.post(f'/api/{route}/', payload)
            self.assertGreaterEqual(response.status_code, 400, route)
        self.assertEqual(self.part.sources.count(), 1)
        self.assertEqual(self.assembly.line_items.count(), 1)
        self.assertEqual(self.deal.deallineitem_set.count(), 1)

    def test_moving_your_own_record_under_another_teams_parent_is_refused(self):
        mine = SubAssemblyFactory(team=self.eve_team, reference='EVE-ASSY', is_toplevel=True, picture=None)
        my_part = PartFactory(team=self.eve_team, reference='EVE-PART', picture=None)
        line = SubAssemblyLineItem.objects.create(subassembly=mine, child_part=my_part, quantity=1)
        response = self.client.patch(f'/api/subassemblylineitems/{line.id}/',
                                     data=f'{{"subassembly": {self.assembly.id}}}', content_type='application/json')
        self.assertGreaterEqual(response.status_code, 400)
        line.refresh_from_db()
        self.assertEqual(line.subassembly, mine)                          # it did not move

    def test_collecting_another_teams_deal_is_refused(self):
        response = self.client.post(f'/api/deals/{self.deal.id}/collect/')
        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.deal.deallineitem_set.count(), 1)
