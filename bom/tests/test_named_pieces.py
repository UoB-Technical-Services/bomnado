""" Named pieces: `PARENT>SUFFIX` named_pieces of a part that instructions can reference,
but that are not BOM items. """
import io
import zipfile
from collections import Counter

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bom.models import Attachment, Part, PartSource, SubAssembly, SubAssemblyLineItem, NamedPiece
from bom.templatetags.markdown_render import as_markdown
from bom.tests.factories import (PartFactory, PartSourceFactory, SubAssemblyFactory, SubAssemblyLineItemFactory,
                                 NamedPieceFactory, TeamFactory)
from bom.utils.export.excel import export_database_to_excel, export_purchasing_spreadsheet
from bom.utils.reference_tools import ReferenceSearch


def _part(reference, **kwargs):
    kwargs.setdefault('picture', None)
    kwargs.setdefault('name', reference)
    return PartFactory(reference=reference, **kwargs)


class NamedPieceModelTests(TestCase):

    def test_reference_joins_parent_and_suffix(self):
        chassis = _part('3D-PRINTED-CHASSIS')
        top = NamedPieceFactory(part=chassis, suffix='TOP', note='Top half')
        self.assertEqual(top.reference, '3D-PRINTED-CHASSIS>TOP')
        self.assertEqual(str(top), '3D-PRINTED-CHASSIS>TOP')

    def test_split_and_find_by_reference(self):
        chassis = _part('CHASSIS')
        top = NamedPieceFactory(part=chassis, suffix='TOP')

        self.assertEqual(NamedPiece.split_reference('CHASSIS>TOP'), ('CHASSIS', 'TOP'))
        for not_piece_syntax in ('CHASSIS', '>TOP', 'CHASSIS>', '', None):
            self.assertIsNone(NamedPiece.split_reference(not_piece_syntax), not_piece_syntax)

        self.assertEqual(NamedPiece.find_by_reference('CHASSIS>TOP'), top)
        self.assertIsNone(NamedPiece.find_by_reference('CHASSIS>BOTTOM'))
        self.assertIsNone(NamedPiece.find_by_reference('OTHER>TOP'))
        self.assertIsNone(NamedPiece.find_by_reference('CHASSIS'))

    def test_suffix_must_look_like_a_reference(self):
        chassis = _part('CHASSIS')
        for bad in ('top', 'TOP HALF', 'TOP>A', '.TOP', 'TOP.', ''):
            with self.subTest(suffix=bad):
                with self.assertRaises(ValidationError):
                    NamedPiece(part=chassis, suffix=bad).full_clean()
        NamedPiece(part=chassis, suffix='TOP-2').full_clean()
        NamedPiece(part=chassis, suffix='V1.2').full_clean()  # dots are fine in the middle

    def test_suffix_is_unique_per_part_only(self):
        chassis, lid = _part('CHASSIS'), _part('LID')
        NamedPieceFactory(part=chassis, suffix='TOP')

        with self.assertRaises(ValidationError):
            NamedPiece(part=chassis, suffix='TOP').full_clean()
        NamedPiece(part=lid, suffix='TOP').full_clean()  # a different parent may reuse the suffix

    def test_picture_falls_back_to_the_part(self):
        chassis = PartFactory(reference='CHASSIS')  # the factory gives it a picture
        top = NamedPieceFactory(part=chassis, suffix='TOP')
        self.assertEqual(top.picture_url, chassis.picture_url)

        bare = _part('BARE')
        self.assertIn('part_placeholder', NamedPieceFactory(part=bare, suffix='X').picture_url)

    def test_pieces_follow_their_part(self):
        user = User.objects.create_user(username='alice', email='alice@example.com', password='x')
        team = TeamFactory()
        team.users.add(user)
        chassis = _part('CHASSIS', team=team)
        top = NamedPieceFactory(part=chassis, suffix='TOP')

        self.assertTrue(top.can_access(user))
        self.assertFalse(top.can_access(User.objects.create_user(username='bob', email='bob@example.com', password='x')))

        chassis.delete()
        self.assertFalse(NamedPiece.objects.filter(pk=top.pk).exists())


class NamedPieceRenameTests(TestCase):
    """ `PARENT>SUFFIX` references follow renames of either half, exactly like part references do. """

    def setUp(self):
        self.team = TeamFactory()
        self.chassis = _part('CHASSIS', team=self.team,
                             spec='Print `CHASSIS` then glue `CHASSIS>TOP` to `CHASSIS>BOTTOM`.',
                             qc_steps='Check `CHASSIS>TOP` for warping.')
        self.top = NamedPieceFactory(part=self.chassis, suffix='TOP', note='Mates with `CHASSIS>BOTTOM`')
        self.bottom = NamedPieceFactory(part=self.chassis, suffix='BOTTOM', note='Under `CHASSIS>TOP`')

        # Something else with the same suffix, and a part whose reference merely starts the same.
        self.other = _part('OTHER', team=self.team)
        self.other_top = NamedPieceFactory(part=self.other, suffix='TOP')
        self.lookalike = _part('CHASSIS-TOP', team=self.team)

        self.project = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True,
                                          instructions='Fit `CHASSIS>TOP`, not `OTHER>TOP` or `CHASSIS-TOP`. Use `CHASSIS`.')
        self.line = SubAssemblyLineItemFactory(subassembly=self.project, child_part=self.chassis, child_subassembly=None,
                                               notes='Drill `CHASSIS>BOTTOM`')
        self.source = PartSourceFactory(part=self.chassis, order_notes='Ask for `CHASSIS>TOP` separately')
        self.user_part = _part('USER', team=self.team, spec='See `CHASSIS>TOP` and `CHASSIS`')

    def test_renaming_the_parent_rewrites_every_piece_reference(self):
        self.chassis.reference = 'FRAME'
        self.chassis.save()

        self.chassis.refresh_from_db()
        self.assertEqual(self.chassis.spec, 'Print `FRAME` then glue `FRAME>TOP` to `FRAME>BOTTOM`.')
        self.assertEqual(self.chassis.qc_steps, 'Check `FRAME>TOP` for warping.')
        self.assertEqual(NamedPiece.objects.get(pk=self.top.pk).note, 'Mates with `FRAME>BOTTOM`')
        self.assertEqual(NamedPiece.objects.get(pk=self.bottom.pk).note, 'Under `FRAME>TOP`')
        self.assertEqual(SubAssembly.objects.get(pk=self.project.pk).instructions,
                         'Fit `FRAME>TOP`, not `OTHER>TOP` or `CHASSIS-TOP`. Use `FRAME`.')
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.line.pk).notes, 'Drill `FRAME>BOTTOM`')
        self.assertEqual(PartSource.objects.get(pk=self.source.pk).order_notes, 'Ask for `FRAME>TOP` separately')
        self.assertEqual(Part.objects.get(pk=self.user_part.pk).spec, 'See `FRAME>TOP` and `FRAME`')

        # The named_pieces themselves now resolve under the new name and not the old.
        self.assertEqual(NamedPiece.find_by_reference('FRAME>TOP'), self.top)
        self.assertIsNone(NamedPiece.find_by_reference('CHASSIS>TOP'))
        self.assertEqual(sum(ReferenceSearch('CHASSIS>TOP').count().values()), 0)

    def test_renaming_the_suffix_rewrites_only_that_piece(self):
        self.top.suffix = 'UPPER'
        self.top.save()

        self.assertEqual(Part.objects.get(pk=self.chassis.pk).spec,
                         'Print `CHASSIS` then glue `CHASSIS>UPPER` to `CHASSIS>BOTTOM`.')
        self.assertEqual(Part.objects.get(pk=self.chassis.pk).qc_steps, 'Check `CHASSIS>UPPER` for warping.')
        self.assertEqual(NamedPiece.objects.get(pk=self.bottom.pk).note, 'Under `CHASSIS>UPPER`')
        self.assertEqual(NamedPiece.objects.get(pk=self.top.pk).note, 'Mates with `CHASSIS>BOTTOM`')
        self.assertEqual(SubAssembly.objects.get(pk=self.project.pk).instructions,
                         'Fit `CHASSIS>UPPER`, not `OTHER>TOP` or `CHASSIS-TOP`. Use `CHASSIS`.')
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.line.pk).notes, 'Drill `CHASSIS>BOTTOM`')
        self.assertEqual(PartSource.objects.get(pk=self.source.pk).order_notes, 'Ask for `CHASSIS>UPPER` separately')
        self.assertEqual(Part.objects.get(pk=self.user_part.pk).spec, 'See `CHASSIS>UPPER` and `CHASSIS`')
        self.assertEqual(NamedPiece.objects.get(pk=self.other_top.pk).suffix, 'TOP')

    def test_saving_without_a_rename_changes_nothing(self):
        self.top.note = 'Top half'
        self.top.save()
        self.chassis.name = 'Chassis, printed'
        self.chassis.save()

        self.assertEqual(Part.objects.get(pk=self.chassis.pk).spec,
                         'Print `CHASSIS` then glue `CHASSIS>TOP` to `CHASSIS>BOTTOM`.')
        self.assertEqual(SubAssembly.objects.get(pk=self.project.pk).instructions,
                         'Fit `CHASSIS>TOP`, not `OTHER>TOP` or `CHASSIS-TOP`. Use `CHASSIS`.')

    def test_moving_a_piece_to_another_part_rewrites_its_references(self):
        self.top.part = self.lookalike
        self.top.save()

        self.assertEqual(SubAssembly.objects.get(pk=self.project.pk).instructions,
                         'Fit `CHASSIS-TOP>TOP`, not `OTHER>TOP` or `CHASSIS-TOP`. Use `CHASSIS`.')
        self.assertEqual(Part.objects.get(pk=self.chassis.pk).spec,
                         'Print `CHASSIS` then glue `CHASSIS-TOP>TOP` to `CHASSIS>BOTTOM`.')

    def test_findreferences_counts_piece_references(self):
        counter = ReferenceSearch('CHASSIS>TOP').count()
        self.assertEqual(counter[f'bom.SubAssembly.instructions@{self.project}'], 1)
        self.assertEqual(counter[f'bom.Part.spec@{self.chassis}'], 1)
        self.assertEqual(counter[f'bom.NamedPiece.note@{self.bottom}'], 1)


class NamedPieceMarkdownTests(TestCase):

    def test_piece_reference_links_to_the_parent_editor(self):
        chassis = _part('CHASSIS')
        NamedPieceFactory(part=chassis, suffix='TOP', note='')
        html = as_markdown('Glue `CHASSIS>TOP` to `CHASSIS`.', None)

        url = reverse('bom:part_editor_update', kwargs={'pk': chassis.id})
        self.assertIn(f'<a class="bn-ref is-part bomlink part piece" href="{url}#named_pieces">CHASSIS&gt;TOP</a>', html)
        self.assertIn(f'class="bn-ref is-part bomlink part" href="{url}"', html)

    def test_piece_link_carries_note_and_picture_for_hover_preview(self):
        chassis = PartFactory(reference='CHASSIS')  # has a picture
        top = NamedPieceFactory(part=chassis, suffix='TOP', note='Top "half" <glued>')
        html = as_markdown('Glue `CHASSIS>TOP`.', None)

        self.assertIn('title="Top &quot;half&quot; &lt;glued&gt;"', html)
        self.assertIn(f'data-picture-preview="{top.picture_url}"', html)  # inherits the part picture
        self.assertNotIn('<glued>', html)

        # No picture anywhere: no preview attribute at all.
        bare = _part('BARE')
        NamedPieceFactory(part=bare, suffix='X', note='')
        self.assertNotIn('data-picture-preview', as_markdown('See `BARE>X`.', None))

    def test_unknown_dotted_reference_stays_as_code(self):
        _part('CHASSIS')
        html = as_markdown('Glue `CHASSIS>NOPE`.', None)
        self.assertIn('<code>CHASSIS&gt;NOPE</code>', html)
        self.assertNotIn('bomlink', html)


class PartEditorNamedPieceTests(TestCase):
    """ The quick-add table on the part editor. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)
        self.chassis = _part('CHASSIS', team=self.team, kgs=1.0, nature='S', spec='')
        self.url = reverse('bom:part_editor_update', kwargs={'pk': self.chassis.id})

    def _post(self, rows, initial=0, **overrides):
        """ Submit the part form with `rows` of piece fields (a list of dicts). """
        data = {
            'reference': self.chassis.reference, 'name': self.chassis.name, 'manufacturer': '', 'kgs': '1',
            'dimensions': '', 'colour': '', 'nature': 'S', 'spec': '', 'qc_steps': '', 'sale_code': '',
            'hs_code': '', 'end_of_life': '', 'deprecated': '', 'review_notes': '',
            'sources-TOTAL_FORMS': '0', 'sources-INITIAL_FORMS': '0',
            'deallineitem_set-TOTAL_FORMS': '0', 'deallineitem_set-INITIAL_FORMS': '0',
            'named_pieces-TOTAL_FORMS': str(len(rows)), 'named_pieces-INITIAL_FORMS': str(initial),
        }
        for index, row in enumerate(rows):
            for field, value in row.items():
                data[f'named_pieces-{index}-{field}'] = value
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_editor_shows_pieces_a_blank_row_and_a_row_template(self):
        NamedPieceFactory(part=self.chassis, suffix='TOP', note='Glue to `CHASSIS>BOTTOM`')
        html = self.client.get(self.url).content.decode()

        self.assertIn('id="named_pieces"', html)
        self.assertIn('name="named_pieces-TOTAL_FORMS"', html)
        self.assertIn('value="TOP"', html)
        self.assertIn('value="Glue to `CHASSIS&gt;BOTTOM`"', html)
        self.assertEqual(html.count('<div class="input-group-text">CHASSIS&gt;</div>'), 3)  # saved, blank, template
        self.assertEqual(html.count('class="input-group bomnado-savechanges-note input-group-sm bomnado-piece-reference"'), 3)
        self.assertIn('pattern="[0-9A-Z]([0-9A-Z.-]*[0-9A-Z-])?"', html)
        self.assertIn('name="named_pieces-__prefix__-suffix"', html)
        self.assertIn('id="pieceRowTemplate"', html)
        self.assertIn('name="named_pieces-0-DELETE"', html)
        self.assertNotIn('name="named_pieces-1-DELETE"', html)  # the blank row has a remove button instead
        self.assertIn('bomnado-piece-remove', html)
        # The compact picture widget, showing the placeholder glyph (not the parent's picture) when unset.
        self.assertEqual(html.count('class="bomnado-tinypicture-widget-button"'), 3)
        self.assertNotIn('bomnado-pastepicture-widget-browse', html.split('id="named_pieces"')[1])

    def test_quick_add_creates_pieces(self):
        response = self._post([
            {'suffix': 'TOP', 'note': 'Glue to `CHASSIS>BOTTOM`'},
            {'suffix': 'BOTTOM', 'note': ''},
            {'suffix': '', 'note': ''},  # the untouched blank row
        ])
        self.assertRedirects(response, self.url)
        self.assertEqual(list(self.chassis.named_pieces.values_list('suffix', 'note')), [
            ('BOTTOM', ''), ('TOP', 'Glue to `CHASSIS>BOTTOM`')])

    def test_quick_add_accepts_a_picture(self):
        picture = SimpleUploadedFile('top.png', _png(), content_type='image/png')
        response = self._post([{'suffix': 'TOP', 'note': ''}], **{'named_pieces-0-picture': picture})
        self.assertRedirects(response, self.url)
        top = self.chassis.named_pieces.get(suffix='TOP')
        self.assertTrue(top.picture)
        self.assertIn(f'named_pieces/{self.chassis.id}_TOP', top.picture.name)
        self.assertEqual(top.picture_url, top.picture.url)

        # The editor now shows the picture in the thumbnail button, and hovering previews it.
        html = self.client.get(self.url).content.decode()
        self.assertIn('class="bomnado-tinypicture-widget-button has-picture"', html)
        self.assertIn(f"background-image: url('{top.picture.url}')", html)
        self.assertIn(f'data-picture-preview="{top.picture.url}"', html)
        self.assertEqual(html.count('app/picture_preview.js'), 1)

    def test_duplicate_or_invalid_suffix_is_reported_inline(self):
        NamedPieceFactory(part=self.chassis, suffix='TOP')
        response = self._post([{'suffix': 'TOP', 'note': ''}, {'suffix': 'bad one', 'note': ''}])
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('already exists', html)
        self.assertIn('Only uppercase letters, numbers, dashes and dots are allowed (a dot only in the middle).', html)
        self.assertEqual(self.chassis.named_pieces.count(), 1)

    def test_two_new_rows_with_the_same_suffix_are_both_flagged(self):
        response = self._post([{'suffix': 'TOP', 'note': ''}, {'suffix': 'TOP', 'note': ''}])
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('Please correct the duplicate data for suffix.', html)
        self.assertEqual(html.count('Please correct the duplicate values below.'), 2)
        self.assertEqual(html.count('bomnado-piece-row table-danger'), 2)
        self.assertEqual(self.chassis.named_pieces.count(), 0)

    def test_renaming_onto_a_sibling_suffix_is_rejected(self):
        top = NamedPieceFactory(part=self.chassis, suffix='TOP')
        bottom = NamedPieceFactory(part=self.chassis, suffix='BOTTOM')
        response = self._post([
            {'id': top.id, 'suffix': 'TOP', 'note': ''},
            {'id': bottom.id, 'suffix': 'TOP', 'note': ''},
        ], initial=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(self.chassis.named_pieces.values_list('suffix', flat=True)), ['BOTTOM', 'TOP'])

    def test_page_flags_duplicate_suffixes_before_submitting(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-page="part-editor"', html)  # the behaviour lives in app/pages/part_editor.js
        with open('bom/static/app/pages/part_editor.js', encoding='utf-8') as script:
            self.assertIn('flagDuplicateSuffixes()', script.read())
        with open('bom/static/app/pages/part_editor.js', encoding='utf-8') as script:
            self.assertIn('is already used on this part', script.read())

    def test_delete_flag_removes_a_piece(self):
        top = NamedPieceFactory(part=self.chassis, suffix='TOP')
        bottom = NamedPieceFactory(part=self.chassis, suffix='BOTTOM')
        response = self._post([
            {'id': bottom.id, 'suffix': 'BOTTOM', 'note': '', 'DELETE': 'on'},
            {'id': top.id, 'suffix': 'TOP', 'note': 'Renamed top'},
        ], initial=2)
        self.assertRedirects(response, self.url)
        self.assertEqual(list(self.chassis.named_pieces.values_list('suffix', 'note')), [('TOP', 'Renamed top')])

    def test_renaming_a_suffix_through_the_editor_rewrites_references(self):
        top = NamedPieceFactory(part=self.chassis, suffix='TOP')
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, instructions='Fit `CHASSIS>TOP`')
        response = self._post([{'id': top.id, 'suffix': 'UPPER', 'note': ''}], initial=1)
        self.assertRedirects(response, self.url)
        self.assertEqual(SubAssembly.objects.get(pk=assembly.pk).instructions, 'Fit `CHASSIS>UPPER`')

    def test_other_teams_cannot_see_the_editor(self):
        other = _part('THEIRS', team=TeamFactory())
        NamedPieceFactory(part=other, suffix='TOP')
        self.assertEqual(self.client.get(reverse('bom:part_editor_update', kwargs={'pk': other.id})).status_code, 403)

    def test_duplicating_a_part_copies_its_pieces(self):
        NamedPieceFactory(part=self.chassis, suffix='TOP', note='Top half')
        response = self.client.post(reverse('bom:part_duplicate'), {'source_id': self.chassis.id})
        copy = Part.objects.get(reference='CHASSIS-COPY')
        self.assertRedirects(response, reverse('bom:part_editor_update', kwargs={'pk': copy.id}))
        self.assertEqual(list(copy.named_pieces.values_list('suffix', 'note')), [('TOP', 'Top half')])
        self.assertEqual(self.chassis.named_pieces.count(), 1)


class NamedPieceSearchTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def test_search_rows_carry_the_parts_pieces(self):
        chassis = _part('CHASSIS', team=self.team)
        top = NamedPieceFactory(part=chassis, suffix='TOP', note='Top half')
        bottom = NamedPieceFactory(part=chassis, suffix='BOTTOM', note='')
        _part('LID', team=self.team)

        rows = self.client.get('/api/parts/search/', {'search': 'CHASSIS>T'}).json()
        self.assertEqual([row['reference'] for row in rows], ['CHASSIS'])  # dot syntax offers the parent
        self.assertEqual(rows[0]['named_pieces'], [
            {'id': bottom.id, 'suffix': 'BOTTOM', 'reference': 'CHASSIS>BOTTOM', 'note': ''},
            {'id': top.id, 'suffix': 'TOP', 'reference': 'CHASSIS>TOP', 'note': 'Top half'},
        ])

    def test_pieces_do_not_cost_a_query_per_row(self):
        for i in range(30):
            part = _part(f'PART-{i:02d}', team=self.team)
            NamedPieceFactory(part=part, suffix='A')
            NamedPieceFactory(part=part, suffix='B')

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/parts/search/', {'search': 'PART'})

        self.assertEqual(len(response.json()), 20)
        self.assertEqual(len(response.json()[0]['named_pieces']), 2)
        self.assertLessEqual(len(queries), 5, [q['sql'] for q in queries])


class NamedPieceAttachmentTests(TestCase):
    """ Attachments use the generic `Attachment` model, so named_pieces get them for free. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def _attach(self, piece):
        url = reverse('bom:attachment_attach', kwargs={'model_name': 'NamedPiece', 'model_pk': piece.id})
        return self.client.post(url, {'attachment_file': SimpleUploadedFile('notes.txt', b'hello')})

    def test_attach_to_a_piece(self):
        top = NamedPieceFactory(part=_part('CHASSIS', team=self.team), suffix='TOP')
        response = self._attach(top)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Attachment.objects.attachments_for_object(top).count(), 1)
        self.assertEqual(Attachment.objects.get().content_type, ContentType.objects.get_for_model(NamedPiece))

    def test_cannot_attach_to_another_teams_piece(self):
        top = NamedPieceFactory(part=_part('CHASSIS', team=TeamFactory()), suffix='TOP')
        self.assertEqual(self._attach(top).status_code, 403)
        self.assertEqual(Attachment.objects.count(), 0)


class NamedPiecesAreNotBomItemsTests(TestCase):
    """ Named pieces have no quantity, sources or line items: counting, costing, exports
    and the orphan tools do not see them. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

        self.project = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True, reference='PROJECT')
        self.chassis = _part('CHASSIS', team=self.team, sale_code='')
        PartSourceFactory(part=self.chassis, rrp=10.0, shipping=0.0, minimum_order=1, url='https://shop.example.com/c')
        SubAssemblyLineItemFactory(subassembly=self.project, child_part=self.chassis, child_subassembly=None, quantity=3)
        self.orphan = _part('ORPHAN', team=self.team)

    def _add_pieces(self):
        NamedPieceFactory(part=self.chassis, suffix='TOP', note='Top half')
        NamedPieceFactory(part=self.chassis, suffix='BOTTOM')
        NamedPieceFactory(part=self.orphan, suffix='LEG')

    def _workbook_shape(self, exporter):
        """ Row count per worksheet and the shared strings of an exported workbook. """
        with io.BytesIO() as output:
            exporter(output).close()
            with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
                names = archive.namelist()
                rows = {n: archive.read(n).decode().count('<row ') for n in names if n.startswith('xl/worksheets/')}
                strings = archive.read('xl/sharedStrings.xml').decode() if 'xl/sharedStrings.xml' in names else ''
        return rows, strings

    def test_counting_and_orphans_ignore_pieces(self):
        self._add_pieces()

        parts, assemblies = Counter(), Counter()
        self.project.collect_and_count_parts(parts, assemblies)
        self.assertEqual(parts, Counter({self.chassis: 3}))
        self.assertEqual(self.chassis.count_usage(), 3)
        self.assertFalse(self.chassis.is_orphan)
        self.assertTrue(self.orphan.is_orphan)

        html = self.client.get(reverse('bom:tools_orphan_finder', kwargs={'pk': self.project.id})).content.decode()
        self.assertIn('>ORPHAN<', html)
        self.assertNotIn('ORPHAN>LEG', html)
        self.assertIn('1 orphan part.', html)

    def test_exports_are_unchanged_by_pieces(self):
        exporters = {
            'bom': lambda output: export_database_to_excel(self.project, output),
            'purchasing': lambda output: export_purchasing_spreadsheet(self.project, output, self.user),
        }
        before = {name: self._workbook_shape(exporter) for name, exporter in exporters.items()}
        self._add_pieces()
        after = {name: self._workbook_shape(exporter) for name, exporter in exporters.items()}

        for name in exporters:
            with self.subTest(export=name):
                self.assertEqual(before[name][0], after[name][0])  # same number of rows on every sheet
                self.assertNotIn('CHASSIS>TOP', after[name][1])
                self.assertNotIn('ORPHAN>LEG', after[name][1])

    def test_piece_references_in_notes_do_not_make_line_items(self):
        self._add_pieces()
        self.project.instructions = 'Glue `CHASSIS>TOP` to `CHASSIS>BOTTOM`'
        self.project.save()
        self.assertEqual(SubAssemblyLineItem.objects.filter(subassembly=self.project).count(), 1)
        self.assertEqual(self.project.kgs, self.chassis.kgs * 3)


def _png():
    """ A 1x1 PNG. """
    import base64
    return base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
