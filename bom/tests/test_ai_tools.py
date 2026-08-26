""" The tool surface (`bom.ai.tools`): reads are bounded and private, writes act as the user. """
import io
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from PIL import Image

from bom.ai import actions, tools
from bom.ai.tools import Blocks, ToolContext
from bom.models import AIThread, Attachment, Feedback, NamedPiece, Part, PartSource, SubAssembly, SubAssemblyLineItem
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory


class ToolTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw', first_name='Alice')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.ctx = ToolContext(self.user, self.team, origin='Chat: make the bolt')
        self.nut = PartFactory(team=self.team, reference='M8-NUT-BZP', name='M8 nut, BZP', picture=None, spec='Zinc plated')

    def call(self, tool, **arguments):
        return tools.call(self.ctx, tool, arguments)


class ReadingTests(ToolTestCase):

    def test_every_tool_has_a_schema_the_api_accepts(self):
        for spec in tools.anthropic_tools():
            self.assertEqual(spec['input_schema']['type'], 'object')
            self.assertFalse(spec['input_schema']['additionalProperties'])
            self.assertTrue(spec['description'])

    def test_search_matches_every_word_and_only_my_teams(self):
        PartFactory(team=TeamFactory(), reference='M8-NUT-A2', name='M8 nut, stainless', picture=None)
        self.assertEqual([p['reference'] for p in self.call('search_parts', query='m8 NUT')], ['M8-NUT-BZP'])
        self.assertEqual(self.call('search_parts', query='m8 nut washer'), [])
        self.assertIn('error', self.call('get_part', part='M8-NUT-A2'))

    def test_get_part_by_reference_or_id(self):
        by_reference = self.call('get_part', part='m8-nut-bzp')
        by_id = self.call('get_part', part=str(self.nut.id))
        self.assertEqual(by_reference['id'], by_id['id'])
        self.assertEqual(by_reference['spec'], 'Zinc plated')
        self.assertEqual(by_reference['url'], f'/part/{self.nut.id}')

    def test_assembly_tree(self):
        top = SubAssemblyFactory(team=self.team, reference='BOX', is_toplevel=True, picture=None)
        inner = SubAssemblyFactory(team=self.team, reference='LID', picture=None)
        SubAssemblyLineItem.objects.create(subassembly=top, child_subassembly=inner, quantity=1)
        SubAssemblyLineItem.objects.create(subassembly=inner, child_part=self.nut, quantity=4)
        flat = self.call('get_assembly', assembly='BOX')
        self.assertEqual([li['item'] for li in flat['line_items']], [f'assembly:{inner.id}'])
        deep = self.call('get_assembly', assembly='BOX', depth=2)
        self.assertEqual(deep['line_items'][0]['children'][0]['reference'], 'M8-NUT-BZP')
        self.assertEqual(self.call('search_assemblies', query='box')[0]['is_toplevel'], True)

    def test_history_names_the_cause(self):
        self.call('update_part', part='M8-NUT-BZP', colour='Black')
        entries = self.call('get_history', record='M8-NUT-BZP', limit=5)
        self.assertEqual(entries[0]['reason'], 'Chat: make the bolt - Bomnado AI')
        self.assertEqual(entries[0]['changes'], [{'field': 'colour', 'from': self.nut.colour, 'to': 'Black'}])

    def test_fetch_page_is_text_or_a_pdf(self):
        page_html = (b'<html><head><meta property="product:price:amount" content="4.20">'
                     b'<script type="application/ld+json">{"@type": "Product", "sku": "B-8-20", "mpn": "912-8-20", '
                     b'"offers": {"@type": "Offer", "price": "4.20", "priceCurrency": "GBP", '
                     b'"availability": "https://schema.org/InStock"}}</script></head>'
                     b'<body><h1>Bolt</h1><p>Pack of 100: \xc2\xa34.20 ex VAT (\xc2\xa35.04 inc)</p>'
                     b'<img src="/a.jpg" alt="bolt"></body></html>')
        with mock.patch('bom.ai.tools.fetch_url', return_value=('https://x.example/p', 'text/html', page_html)):
            page = self.call('fetch_page', url='https://x.example/p')
        self.assertIn('Bolt', page['text'])
        self.assertEqual(page['pictures'][0]['url'], 'https://x.example/a.jpg')
        # What the visible text hides: the structured price, the seller's numbers, the amounts seen.
        self.assertEqual(page['prices'], ['4.20 GBP', '4.20'])
        self.assertEqual(page['part_numbers'], ['sku: B-8-20', 'mpn: 912-8-20'])
        self.assertEqual(page['availability'], ['InStock'])
        self.assertEqual(page['prices_in_text'], ['\xa34.20', '\xa35.04'])
        with mock.patch('bom.ai.tools.fetch_url', return_value=('https://x.example/d.pdf', 'application/pdf', b'%PDF-1.4 x')):
            pdf = self.call('fetch_page', url='https://x.example/d.pdf')
        self.assertIsInstance(pdf, Blocks)
        self.assertEqual(pdf.blocks[1]['type'], 'document')

    def test_unknown_tools_and_missing_arguments_are_errors_not_exceptions(self):
        self.assertEqual(self.call('teleport')['error'], 'Unknown tool teleport.')
        self.assertIn('needs part', self.call('get_part')['error'])
        self.assertIn('No part', self.call('get_part', part='NOPE')['error'])


class WritingTests(ToolTestCase):

    def test_create_part_is_validated_attributed_and_flagged(self):
        with mock.patch('bom.ai.actions.download_image', return_value=None):
            result = self.call('create_part', reference='m8-20mm-bolt-btn-bzp', name='M8 x 20 button bolt',
                               dimensions='20x13x8mm', qc_steps='- Thread gauge fits', kgs=0.004,
                               suppliers=[{'supplier': 'Shop4Fasteners', 'rrp': 0.12, 'minimum_order': 100}, {}],
                               picture_url='https://x.example/p.jpg')
        part = Part.objects.get(reference='M8-20MM-BOLT-BTN-BZP')
        self.assertEqual((part.dimensions, part.qc_steps, part.kgs), ('20 x 13 x 8', '- [ ] Thread gauge fits', 0.004))
        self.assertEqual([(s.supplier, s.rrp, s.minimum_order) for s in part.sources.all()], [('Shop4Fasteners', 0.12, 100)])
        self.assertEqual(part.history.first().history_change_reason, 'Chat: make the bolt - Bomnado AI')
        self.assertEqual(part.history.first().history_user, self.user)
        self.assertEqual(Feedback.objects.open_for(part).get().text, actions.REVIEW_TEXT)
        self.assertTrue(Part.objects.get(pk=part.pk).has_open_feedback)
        self.assertEqual(result['notes'], ['picture: that was not an image'])
        self.assertEqual(self.ctx.touched, [{'model': 'part', 'id': part.id, 'reference': part.reference, 'what': 'created'}])
        self.assertIn('already exists', self.call('create_part', reference='M8-20MM-BOLT-BTN-BZP', name='again')['error'])

    def test_validation_failures_are_reported_not_saved(self):
        self.assertIn('Not saved: reference', self.call('create_part', reference='has space', name='x')['error'])
        self.assertFalse(Part.objects.filter(name='x').exists())

    def test_update_changes_only_what_is_given_and_one_review_comment(self):
        self.call('update_part', part='M8-NUT-BZP', colour='BZP')
        self.call('update_part', part='M8-NUT-BZP', spec='Zinc plated, DIN 934')
        self.nut.refresh_from_db()
        self.assertEqual((self.nut.colour, self.nut.spec, self.nut.name), ('BZP', 'Zinc plated, DIN 934', 'M8 nut, BZP'))
        self.assertEqual(Feedback.objects.open_for(self.nut).count(), 1)

    def test_lead_time_and_shipping_are_estimated_from_the_same_supplier(self):
        for lead, ship in ((3, 4.95), (3, 4.95), (5, 6.0)):
            PartSource.objects.create(part=PartFactory(team=self.team, picture=None), supplier='Shop4Fasteners',
                                      url='https://shop4fasteners.co.uk/x', lead_time=lead, shipping=ship, rrp=0.1)
        added = self.call('add_supplier', part='M8-NUT-BZP', supplier='shop4fasteners', url='https://shop4fasteners.co.uk/m8')
        self.assertEqual((added['lead_time'], added['shipping']), (3, 4.95))
        self.assertIn('estimated from 3 other shop4fasteners rows', added['estimated']['lead_time'])
        self.assertIn('No price', added['warning'])
        # Given values win; an unknown supplier gets the defaults and no estimate.
        given = self.call('add_supplier', part='M8-NUT-BZP', supplier='Farnell', lead_time=2, rrp=0.2)
        self.assertEqual(given['lead_time'], 2)
        self.assertNotIn('estimated', given)
        self.assertNotIn('warning', given)
        # By site when the name is new but the URL is familiar.
        by_site = self.call('add_supplier', part='M8-NUT-BZP', url='https://www.shop4fasteners.co.uk/other', rrp=0.3)
        self.assertEqual(by_site['lead_time'], 3)

    def test_add_supplier_fills_a_blank_row_first(self):
        PartSource.objects.create(part=self.nut)  # the blank row a new part is born with
        self.call('add_supplier', part='M8-NUT-BZP', supplier='RS', url='https://rs.example/1', partcode='123', rrp=0.05)
        self.call('add_supplier', part='M8-NUT-BZP', supplier='Farnell', rrp=0.06)
        rows = list(self.nut.sources.order_by('pk').values_list('supplier', 'partcode', 'rrp'))
        self.assertEqual(rows, [('RS', '123', 0.05), ('Farnell', '', 0.06)])
        source = self.nut.sources.get(supplier='RS')
        self.call('update_supplier', supplier_id=source.id, lead_time=3)
        self.assertEqual(PartSource.objects.get(pk=source.pk).lead_time, 3)

    def test_named_pieces_feedback(self):
        self.assertEqual(self.call('add_named_piece', part='M8-NUT-BZP', suffix='flange', note='the wide bit')['reference'],
                         'M8-NUT-BZP>FLANGE')
        self.assertIn('already exists', self.call('add_named_piece', part='M8-NUT-BZP', suffix='FLANGE')['error'])
        self.assertEqual(NamedPiece.objects.get().history.first().history_change_reason, 'Chat: make the bolt - Bomnado AI')
        self.call('add_feedback', record='part:%d' % self.nut.id, text='Is this still stocked?')
        self.assertEqual(Feedback.objects.for_object(self.nut).filter(text='Is this still stocked?').get().author, self.user)

    def test_assemblies_and_line_items(self):
        created = self.call('create_assembly', reference='box', name='A box', is_toplevel=True,
                            line_items=[{'item': 'M8-NUT-BZP', 'quantity': 4}, {'item': 'NOPE'}])
        self.assertEqual(created['line_items'][0]['quantity'], 4)
        self.assertEqual(created['problems'], ["NOPE: No part or assembly called 'NOPE'."])
        box = SubAssembly.objects.get(reference='BOX')
        self.assertEqual(box.revision, '0.1.0')
        self.assertEqual(Feedback.objects.open_for(box).count(), 1)
        self.call('set_line_item', assembly='BOX', item=f'part:{self.nut.id}', quantity=6, notes='plus spares')
        self.assertEqual(list(box.line_items.values_list('quantity', 'notes')), [(6, 'plus spares')])
        self.assertIn('cannot contain itself', self.call('set_line_item', assembly='BOX', item='assembly:%d' % box.id)['error'])
        self.assertEqual(self.call('set_line_item', assembly='BOX', item='M8-NUT-BZP', quantity=0)['removed'], True)
        self.assertEqual(box.line_items.count(), 0)
        self.call('update_assembly', assembly='BOX', production_phase='Pilot')
        self.assertEqual(SubAssembly.objects.get(pk=box.pk).production_phase, 'Pilot')

    def test_files_from_the_conversation(self):
        thread = AIThread.objects.create(user=self.user, team=self.team)
        photo = Attachment(content_object=thread)
        with io.BytesIO() as buffer:
            Image.new('RGB', (8, 8), 'red').save(buffer, format='PNG')
            photo.attachment_file.save('Loom Photo.png', ContentFile(buffer.getvalue()))
        sheet = Attachment(content_object=thread)
        sheet.attachment_file.save('loom.pdf', ContentFile(b'%PDF-1.4 x'))
        self.ctx.attachments = {a.filename: a for a in Attachment.objects.attachments_for_object(thread)}

        created = self.call('create_part', reference='LOOM', name='Loom', files=['loom photo.png', 'loom.pdf', 'nope.txt'])
        loom = Part.objects.get(reference='LOOM')
        self.assertEqual(sorted(created['attached']), sorted([photo.filename, sheet.filename]))
        self.assertTrue(loom.picture)
        self.assertEqual(Attachment.objects.attachments_for_object(loom).count(), 2)

        self.assertEqual(self.call('attach_file', record='M8-NUT-BZP', filename='loom.pdf')['attached'], [sheet.filename])
        self.assertIn('No file called', self.call('attach_file', record='M8-NUT-BZP', filename='x.txt')['error'])
        self.assertEqual(self.call('set_picture', record='M8-NUT-BZP', source=photo.filename)['picture'], 'ok')
        self.assertTrue(Part.objects.get(pk=self.nut.pk).picture)
        read = self.call('read_attachment', attachment_id=photo.id)
        self.assertEqual(read.blocks[1]['type'], 'image')

    def test_other_teams_are_off_limits(self):
        other = PartFactory(team=TeamFactory(), reference='THEIRS', picture=None)
        self.assertIn('access', self.call('update_part', part=str(other.id), name='mine now')['error'])
        self.assertEqual(Part.objects.get(pk=other.pk).name, other.name)
        self.ctx.team = TeamFactory()  # a team the user is not in
        self.assertIn('team', self.call('create_part', reference='X', name='x')['error'])
