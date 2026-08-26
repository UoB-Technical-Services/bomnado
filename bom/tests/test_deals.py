from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bom.models import Deal
from bom.tests.factories import SubAssemblyFactory, TeamFactory


class ToolDealCreateViewTests(TestCase):
    """ Deals can only be created for teams the user belongs to. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.project = SubAssemblyFactory(team=self.team, is_toplevel=True, picture=None)
        self.other_team = TeamFactory()
        self.other_project = SubAssemblyFactory(team=self.other_team, is_toplevel=True, picture=None)
        self.url = reverse('bom:tools_deals_create', kwargs={'pk': self.project.id})
        self.client.force_login(self.user)

    def _deal_data(self, team, project):
        return {
            'name': 'Bulk bolts',
            'rrp': '1.50',
            'shipping': '5.00',
            'lead_time': '3',
            'url': 'https://supplier.example.com/bolts',
            'team': team.id,
            'project': project.id,
            'order_notes': 'Ask for trade price.',
        }

    def test_member_can_create_deal_for_own_team(self):
        response = self.client.post(self.url, self._deal_data(self.team, self.project))
        self.assertRedirects(response, reverse('bom:tools_deals', kwargs={'pk': self.project.id}),
                             fetch_redirect_response=False)
        deal = Deal.objects.get(name='Bulk bolts')
        self.assertEqual(deal.team, self.team)

    def test_cannot_create_deal_for_other_team(self):
        response = self.client.post(self.url, self._deal_data(self.other_team, self.other_project))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Deal.objects.exists())

    def test_invalid_form_creates_nothing(self):
        data = self._deal_data(self.team, self.project)
        data['name'] = ''
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Deal.objects.exists())

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(self.url, self._deal_data(self.team, self.project))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertFalse(Deal.objects.exists())
