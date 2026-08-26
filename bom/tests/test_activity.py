""" Comments and activity: history of a part / assembly and its children, feedback, revert. """
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bom.models import Feedback, NamedPiece, Part, PartSource, SubAssembly, SubAssemblyLineItem
from bom.templatetags.utils import stylised_part
from bom.tests.factories import (NamedPieceFactory, PartFactory, PartSourceFactory, SubAssemblyFactory,
                                 SubAssemblyLineItemFactory, TeamFactory)
from bom.utils.activity import PAGE_SIZE, activity, revert


class ActivityTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)
        self.part = PartFactory(reference='CHASSIS', name='Chassis', team=self.team, picture=None, kgs=1.0,
                                nature='S', spec='', qc_steps='', dimensions='', colour='', sale_code='', hs_code='',
                                end_of_life=None)
        self.url = reverse('bom:part_editor_update', kwargs={'pk': self.part.id})

    def post_part(self, **overrides):
        """ Save the part form as the editor would. """
        data = {
            'reference': self.part.reference, 'name': self.part.name, 'manufacturer': '', 'kgs': '1',
            'dimensions': '', 'colour': '', 'nature': 'S', 'spec': '', 'qc_steps': '', 'sale_code': '',
            'hs_code': '', 'end_of_life': '', 'deprecated': '',
            'sources-TOTAL_FORMS': '0', 'sources-INITIAL_FORMS': '0',
            'deallineitem_set-TOTAL_FORMS': '0', 'deallineitem_set-INITIAL_FORMS': '0',
            'named_pieces-TOTAL_FORMS': '0', 'named_pieces-INITIAL_FORMS': '0',
        }
        data.update(overrides)
        response = self.client.post(self.url, data)
        self.assertRedirects(response, self.url)
        self.part.refresh_from_db()
        return response

    def entries(self, obj=None, offset=0):
        return activity(obj or self.part, offset)[0]


class HistoryRecordingTests(ActivityTestCase):

    def test_every_save_is_kept_with_the_user_who_made_it(self):
        self.post_part(name='Chassis, printed')
        versions = self.part.history.all()
        self.assertEqual(versions.count(), 2)  # factory create + the edit
        self.assertEqual(versions.first().name, 'Chassis, printed')
        self.assertEqual(versions.first().history_user, self.user)
        self.assertEqual(versions.first().history_type, '~')

    def test_children_are_tracked_too(self):
        source = PartSourceFactory(part=self.part, rrp=1.0)
        piece = NamedPieceFactory(part=self.part, suffix='TOP')
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True)
        line = SubAssemblyLineItemFactory(subassembly=assembly, child_part=self.part, child_subassembly=None, quantity=2)
        for obj in (source, piece, line):
            self.assertEqual(obj.history.count(), 1, obj)
        # A top-level assembly is saved twice on creation: once created, once linked to itself as project.
        self.assertEqual(assembly.history.count(), 2)

    def test_the_feedback_flag_is_not_part_of_history(self):
        Feedback.objects.create(content_object=self.part, text='Look at this', author=self.user)
        self.part.refresh_from_db()
        self.assertTrue(self.part.has_open_feedback)
        self.assertEqual(self.part.history.count(), 1)  # the flag flip made no version
        self.assertFalse(hasattr(self.part.history.first(), 'has_open_feedback'))


class ActivityEntriesTests(ActivityTestCase):

    def test_an_edit_lists_what_changed(self):
        self.post_part(name='Chassis, printed', dimensions='120 x 80 x 20')
        entry = self.entries()[0]
        self.assertEqual(entry.kind, 'edited')
        self.assertTrue(entry.is_self)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.verb, 'changed')
        self.assertEqual(entry.summary, 'Name, Dimensions')
        self.assertEqual([(c.label, c.old, c.new) for c in entry.changes],
                         [('Name', 'Chassis', 'Chassis, printed'), ('Dimensions', '', '120 x 80 x 20')])
        self.assertIsNotNone(entry.revert)

    def test_long_text_shows_as_a_diff(self):
        self.post_part(spec='# Spec\n\nPrint at 0.2mm.\nUse PETG.')
        self.post_part(spec='# Spec\n\nPrint at 0.2mm.\nUse PLA.')
        change = self.entries()[0].changes[0]
        self.assertEqual(change.label, 'Specification')
        self.assertIn('-Use PETG.', change.diff)
        self.assertIn('+Use PLA.', change.diff)
        self.assertNotIn('---', change.diff)  # the file headers are dropped

    def test_a_save_that_changes_nothing_makes_no_entry(self):
        self.post_part()
        kinds = [e.kind for e in self.entries()]
        self.assertEqual(kinds, ['created'])
        self.assertEqual(self.entries()[0].verb, 'created')
        self.assertIsNone(self.entries()[0].revert)  # cannot remove the part from its own page

    def test_children_appear_by_name(self):
        source = PartSourceFactory(part=self.part, url='https://www.rs-online.com/p/1', partcode='RS-1', rrp=1.0)
        source.rrp = 2.5
        source.save()
        piece = NamedPieceFactory(part=self.part, suffix='TOP', note='')
        piece.delete()

        entries = self.entries()
        self.assertEqual([(e.kind, e.target) for e in entries[:4]], [
            ('deleted', 'named piece CHASSIS>TOP'),
            ('created', 'named piece CHASSIS>TOP'),
            ('edited', 'supplier rs-online.com'),
            ('created', 'supplier rs-online.com'),
        ])
        self.assertEqual(entries[2].verb, 'changed')
        self.assertEqual(entries[2].summary, 'Unit Cost')
        self.assertEqual(entries[3].verb, 'added')
        self.assertEqual(entries[0].verb, 'removed')

    def test_assembly_line_items_appear_with_their_item(self):
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, instructions='')
        line = SubAssemblyLineItemFactory(subassembly=assembly, child_part=self.part, child_subassembly=None, quantity=2,
                                          notes='')
        line.quantity = 4
        line.save()
        entries = self.entries(assembly)
        self.assertEqual([(e.kind, e.target, e.summary) for e in entries[:2]], [
            ('edited', 'line item 4 × CHASSIS', 'Quantity'),
            ('created', 'line item 2 × CHASSIS', ''),
        ])
        self.assertEqual(entries[0].changes[0].new, '4')

    def test_reference_rename_sweep_says_why(self):
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, instructions='Fit `CHASSIS`')
        self.post_part(reference='FRAME')
        entry = self.entries(assembly)[0]
        self.assertEqual(entry.summary, 'Instructions')
        self.assertEqual(entry.reason, 'reference `CHASSIS` renamed to `FRAME`')

    def test_pages_of_ten_newest_first(self):
        for i in range(PAGE_SIZE * 2 + 3):
            self.part.name = f'Name {i}'
            self.part.save()

        page1, more1 = activity(self.part, 0)
        page3, more3 = activity(self.part, PAGE_SIZE * 2)
        self.assertEqual(len(page1), PAGE_SIZE)
        self.assertTrue(more1)
        self.assertEqual(page1[0].changes[0].new, f'Name {PAGE_SIZE * 2 + 2}')
        self.assertEqual(len(page3), 4)  # 3 edits + the creation
        self.assertFalse(more3)
        self.assertEqual(page3[-1].kind, 'created')

    def test_a_page_costs_a_bounded_number_of_queries(self):
        for i in range(15):
            PartSourceFactory(part=self.part, rrp=float(i))
        for i in range(5):
            self.part.name = f'Name {i}'
            self.part.save()
        with CaptureQueriesContext(connection) as queries:
            entries, has_more = activity(self.part, 0)
        self.assertEqual(len(entries), PAGE_SIZE)
        self.assertTrue(has_more)
        # One query per source model + feedback, plus a predecessor lookup for edits whose
        # previous version fell outside the page. Never one per row of the table.
        self.assertLessEqual(len(queries), 20, [q['sql'] for q in queries])


class ActivityPageTests(ActivityTestCase):

    def test_people_are_named_not_usernamed(self):
        self.post_part(name='Chassis, printed')
        html = self.client.get(self.url).content.decode()
        self.assertIn('href="mailto:alice@example.com"', html)
        self.assertIn('>alice@example.com</a></strong>', html)  # no first name: the email
        self.assertNotIn('<strong>alice</strong>', html)

        self.user.first_name, self.user.last_name = 'Alice', 'Smith'
        self.user.save()
        html = self.client.get(self.url).content.decode()
        self.assertIn('>Alice Smith</a></strong>', html)

    def test_editors_show_the_strip_instead_of_the_notes_box(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('id="activity"', html)
        self.assertIn('Feedback and history', html)
        self.assertLess(html.index('id="sec-usage"'), html.index('Feedback and history'))
        self.assertIn('created this part', html)
        self.assertIn('bomnado-activity-svg', html)
        self.assertNotIn('review_notes', html)
        self.assertNotIn('Open feedback', html)

        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True)
        html = self.client.get(reverse('bom:assembly_editor_update', kwargs={'pk': assembly.id})).content.decode()
        self.assertIn('id="activity"', html)
        self.assertIn('created this assembly', html)

    def test_show_more_fetches_the_next_page(self):
        for i in range(PAGE_SIZE + 2):
            self.part.name = f'Name {i}'
            self.part.save()
        html = self.client.get(self.url).content.decode()
        self.assertIn('Show more', html)
        self.assertEqual(html.count('<li class="bomnado-activity-entry'), PAGE_SIZE)

        url = reverse('bom:activity_entries', kwargs={'model_name': 'part', 'pk': self.part.id})
        html = self.client.get(url, {'offset': PAGE_SIZE}).content.decode()
        self.assertEqual(html.count('<li class="bomnado-activity-entry'), 3)  # 2 edits + created
        self.assertNotIn('Show more', html)
        self.assertNotIn('id="activity"', html)  # entries only

    def test_other_teams_get_403(self):
        other = PartFactory(team=TeamFactory(), picture=None)
        url = reverse('bom:activity_entries', kwargs={'model_name': 'part', 'pk': other.id})
        self.assertEqual(self.client.get(url).status_code, 403)
        url = reverse('bom:activity_entries', kwargs={'model_name': 'deal', 'pk': other.id})
        self.assertEqual(self.client.get(url).status_code, 404)


class FeedbackTests(ActivityTestCase):

    def add(self, text, obj=None):
        obj = obj or self.part
        url = reverse('bom:feedback_add', kwargs={'model_name': 'part' if isinstance(obj, Part) else 'subassembly',
                                                  'pk': obj.id})
        return self.client.post(url, {'text': text})

    def test_adding_feedback_flags_the_record_and_shows_in_the_strip(self):
        response = self.add('Check the `CHASSIS` wall thickness')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="activity"', html)
        self.assertIn('Resolve', html)
        self.assertIn('wall thickness', html)
        self.assertIn('bomlink part', html)  # references in feedback render as links

        self.part.refresh_from_db()
        self.assertTrue(self.part.has_open_feedback)
        item = Feedback.objects.get()
        self.assertEqual(item.author, self.user)
        self.assertEqual(item.content_object, self.part)
        self.assertIn('bn-mark is-bad', stylised_part(self.part))  # the red dot: open feedback
        self.assertIn('Open feedback', self.client.get(self.url).content.decode())
        row = self.client.get('/api/parts/search/', {'search': 'CHASSIS'}).json()[0]
        self.assertTrue(row['has_open_feedback'])

    def test_resolve_and_reopen(self):
        self.add('Look at this')
        item = Feedback.objects.get()
        response = self.client.post(reverse('bom:feedback_resolve', kwargs={'feedback_id': item.id}))
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.part.refresh_from_db()
        self.assertFalse(item.is_open)
        self.assertEqual(item.resolved_by, self.user)
        self.assertFalse(self.part.has_open_feedback)
        kinds = [e.kind for e in self.entries()]
        self.assertEqual(kinds, ['resolved', 'feedback', 'created'])
        html = response.content.decode()
        self.assertIn('resolved by <a class="bomnado-person" href="mailto:alice@example.com"', html)  # on the comment row
        self.assertIn('Reopen', html)              # its action
        self.assertIn('</strong> resolved <span', html)  # the marker row, with no actions
        self.assertNotIn('Resolve<', html)

        self.client.post(reverse('bom:feedback_reopen', kwargs={'feedback_id': item.id}))
        self.part.refresh_from_db()
        self.assertTrue(self.part.has_open_feedback)

    def test_blank_feedback_is_ignored(self):
        self.add('   ')
        self.assertEqual(Feedback.objects.count(), 0)

    def test_feedback_on_assemblies(self):
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True)
        self.add('Needs a picture', assembly)
        assembly.refresh_from_db()
        self.assertTrue(assembly.has_open_feedback)
        self.assertEqual(Feedback.objects.open_for(assembly).count(), 1)
        self.assertEqual(Feedback.objects.open_for(self.part).count(), 0)

    def test_other_teams_cannot_comment_or_resolve(self):
        other = PartFactory(team=TeamFactory(), picture=None)
        self.assertEqual(self.add('Hi', other).status_code, 403)
        item = Feedback.objects.create(content_object=other, text='x')
        self.assertEqual(self.client.post(reverse('bom:feedback_resolve', kwargs={'feedback_id': item.id})).status_code,
                         403)


class RevertTests(ActivityTestCase):

    def revert_url(self, entry, obj=None):
        obj = obj or self.part
        return reverse('bom:activity_revert', kwargs={
            'model_name': 'part' if isinstance(obj, Part) else 'subassembly', 'pk': obj.id,
            'historical_model': entry.revert[0], 'history_id': entry.revert[1]})

    def test_reverting_an_edit_restores_the_old_values_as_a_new_version(self):
        self.post_part(name='Chassis, printed', dimensions='1 x 2 x 3')
        self.post_part(dimensions='1 x 2 x 3', colour='Black')
        edit = self.entries()[1]  # the name/dimensions edit, under the colour edit
        self.assertEqual(edit.summary, 'Name, Dimensions')

        response = self.client.post(self.revert_url(edit))
        self.assertRedirects(response, f'{self.url}#activity', fetch_redirect_response=False)

        self.part.refresh_from_db()
        self.assertEqual((self.part.name, self.part.dimensions, self.part.colour), ('Chassis', '', 'Black'))
        self.assertEqual(self.part.history.count(), 4)  # nothing deleted: the revert is a version too
        latest = self.entries()[0]
        self.assertEqual(latest.summary, 'Name, Dimensions')
        self.assertTrue(latest.reason.startswith('Reverted the change on'))
        self.assertEqual(latest.user, self.user)
        self.assertEqual((latest.icon, latest.verb), ('revert', 'reverted a change to'))
        html = self.client.get(self.url).content.decode()
        self.assertIn('reverted a change to this part: Name, Dimensions', html)

    def test_reverting_a_reference_change_renames_references_back(self):
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, instructions='Fit `CHASSIS`')
        self.post_part(reference='FRAME')
        self.assertEqual(SubAssembly.objects.get(pk=assembly.pk).instructions, 'Fit `FRAME`')
        self.client.post(self.revert_url(self.entries()[0]))
        self.part.refresh_from_db()
        self.assertEqual(self.part.reference, 'CHASSIS')
        self.assertEqual(SubAssembly.objects.get(pk=assembly.pk).instructions, 'Fit `CHASSIS`')

    def test_reverting_a_removal_brings_the_child_back(self):
        source = PartSourceFactory(part=self.part, partcode='RS-1', url='https://rs-online.com/1', rrp=3.0)
        source_id = source.id
        source.delete()
        removal = self.entries()[0]
        self.assertEqual(removal.kind, 'deleted')
        self.client.post(self.revert_url(removal))
        restored = PartSource.objects.get(pk=source_id)
        self.assertEqual((restored.partcode, restored.rrp, restored.part), ('RS-1', 3.0, self.part))
        self.assertEqual((self.entries()[0].icon, self.entries()[0].verb), ('revert', 'restored'))

    def test_reverting_an_addition_removes_the_child(self):
        piece = NamedPieceFactory(part=self.part, suffix='TOP')
        addition = self.entries()[0]
        self.assertEqual(addition.kind, 'created')
        self.client.post(self.revert_url(addition))
        self.assertFalse(NamedPiece.objects.filter(pk=piece.pk).exists())
        self.assertEqual(self.entries()[0].kind, 'deleted')
        self.assertTrue(self.entries()[0].reason.startswith('Reverted the addition on'))
        self.assertEqual(self.entries()[0].verb, 'reverted the addition of')

    def test_reverting_a_line_item_edit(self):
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, instructions='')
        line = SubAssemblyLineItemFactory(subassembly=assembly, child_part=self.part, child_subassembly=None, quantity=2,
                                          notes='')
        line.quantity = 9
        line.save()
        self.client.post(self.revert_url(self.entries(assembly)[0], assembly))
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=line.pk).quantity, 2)

    def test_cannot_revert_across_records_or_teams(self):
        other = PartFactory(team=self.team, picture=None)
        other.name = 'changed'
        other.save()
        foreign = self.entries(other)[0]
        # A valid entry of another part, presented as if it belonged to this one: not found.
        self.assertEqual(self.client.post(self.revert_url(foreign, self.part)).status_code, 404)
        # Another team's part: forbidden.
        theirs = PartFactory(team=TeamFactory(), picture=None)
        theirs.name = 'changed'
        theirs.save()
        self.assertEqual(self.client.post(self.revert_url(self.entries(theirs)[0], theirs)).status_code, 403)
        # Bogus history model: not found.
        url = reverse('bom:activity_revert', kwargs={'model_name': 'part', 'pk': self.part.id,
                                                    'historical_model': 'HistoricalDeal', 'history_id': 1})
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_revert_helper_refuses_to_remove_the_page_record(self):
        created = [e for e in self.part.history.all()][-1]
        with self.assertRaises(Exception):
            revert(self.part, 'HistoricalPart', created.history_id)
        self.assertTrue(Part.objects.filter(pk=self.part.pk).exists())
