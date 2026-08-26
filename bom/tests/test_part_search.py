import time
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from bom.models import Part
from bom.tests.factories import PartFactory, TeamFactory

SEARCH_URL = '/api/parts/search/'


class PartSearchEndpointTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def _part(self, reference, name='', team=None):
        return PartFactory(reference=reference, name=name or reference, team=team or self.team, picture=None)

    def _refs(self, term):
        response = self.client.get(SEARCH_URL, {'search': term})
        self.assertEqual(response.status_code, 200)
        return [row['reference'] for row in response.json()]

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(SEARCH_URL, {'search': 'M8'}).status_code, 403)

    def test_only_returns_the_users_teams_parts(self):
        self._part('M8-NUT')
        self._part('M8-BOLT', team=TeamFactory())
        self.assertEqual(self._refs('M8'), ['M8-NUT'])

    def test_prefix_matches_win_over_contains_matches(self):
        self._part('BOLT-M8')
        self._part('M8-NUT')
        self._part('M8-BOLT')
        # Prefix hits only, ordered by reference.
        self.assertEqual(self._refs('m8'), ['M8-BOLT', 'M8-NUT'])

    def test_falls_back_to_contains_on_reference_or_name(self):
        self._part('BOLT-M8')
        self._part('HEX-NUT', name='Nut for M8 bolts')
        self._part('WASHER')
        self.assertEqual(self._refs('M8'), ['BOLT-M8', 'HEX-NUT'])

    def test_dot_syntax_matches_the_parent_reference(self):
        """ Typing `PARENT.SUFFIX` offers PARENT, so selecting it adds the parent part. """
        self._part('3D-PRINTED-CHASSIS')
        self._part('3D-PRINTED-LID')
        self.assertEqual(self._refs('3D-PRINTED-CHASSIS.TOP'), ['3D-PRINTED-CHASSIS'])
        self.assertEqual(self._refs('3d-printed-chassis.'), ['3D-PRINTED-CHASSIS'])

    def test_reference_containing_a_dot_still_matches_directly(self):
        self._part('V1.2-BRACKET')
        self._part('V1')
        self.assertEqual(self._refs('V1.2'), ['V1.2-BRACKET'])

    def test_empty_term_returns_first_page_alphabetically(self):
        for ref in ('C', 'A', 'B'):
            self._part(ref)
        self.assertEqual(self._refs(''), ['A', 'B', 'C'])

    def test_returns_only_slim_fields(self):
        part = self._part('M8-NUT', name='Hex nut')
        row = self.client.get(SEARCH_URL, {'search': 'M8'}).json()[0]
        self.assertEqual(set(row), {'id', 'reference', 'name', 'picture_url', 'deprecated', 'sale_code', 'review_notes'})
        self.assertEqual(row['id'], part.id)
        self.assertEqual(row['name'], 'Hex nut')
        self.assertIn('part_placeholder', row['picture_url'])

    def test_limit_and_constant_query_count_with_thousands_of_parts(self):
        Part.objects.bulk_create([
            Part(reference=f'M8-BOLT-{i:05d}', name=f'Bolt {i}', team=self.team) for i in range(3000)
        ])

        with CaptureQueriesContext(connection) as queries:
            started = time.perf_counter()
            response = self.client.get(SEARCH_URL, {'search': 'M8-BOLT-01'})
            elapsed = time.perf_counter() - started

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 20)
        self.assertEqual(response.json()[0]['reference'], 'M8-BOLT-01000')
        # Session/user lookups plus one search query - nothing per row.
        self.assertLessEqual(len(queries), 5, [q['sql'] for q in queries])
        # Generous ceiling; the aim is ~100ms in practice.
        self.assertLess(elapsed, 0.5)


class PartsCacheRemovedTests(TestCase):
    """ The per-user parts cache is gone: lists are always fresh and saving a part
    no longer touches every user's cache entry. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def test_list_reflects_new_parts_immediately(self):
        PartFactory(team=self.team, picture=None, reference='FIRST')
        self.assertEqual(len(self.client.get('/api/parts/').json()), 1)

        PartFactory(team=self.team, picture=None, reference='SECOND')
        self.assertEqual(len(self.client.get('/api/parts/').json()), 2)

    def test_saving_a_part_does_not_touch_the_cache(self):
        for _ in range(3):
            User.objects.create_user(username=f'u{_}', email=f'u{_}@example.com', password='x')
        part = PartFactory(team=self.team, picture=None)

        with mock.patch('django.core.cache.cache.delete') as delete, \
                mock.patch('django.core.cache.cache.set') as cache_set:
            part.name = 'renamed'
            part.save()
            part.delete()

        delete.assert_not_called()
        cache_set.assert_not_called()
