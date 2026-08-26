from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse_lazy

from bom import models
from bom.tests import factories
from bom.templatetags.markdown_render import as_markdown


class ModelTests(TestCase):

    def test_models(self):
        team = models.Team.objects.create(name="Test Team")

        # Parts
        # ID / Primary Key
        # Reference (ie. M8-BOLT-20MM-BZP)
        # Name (ie. M8 20MM BZP Bolt)
        # Classification (dropdown of type of part, fixing, ordered, ordered and reworked, more to be added)
        # Description (255 char text string)
        # Created Timestamp
        # Updated Timestamp
        # Part Sources [1-n]
        part = models.Part.objects.create(reference="P1", name="Part 1", spec="This is a test part", team=team)
        self.assertIsNotNone(part)
        self.assertGreater(models.Part.objects.all().count(), 0)

        # Part Source
        # Primary Key
        # Part ID
        # URL
        # Lead Time
        # Created Timestamp
        # Updated Timestamp
        # Single Unit RRP (ex VAT)
        # minimum_order Quantity
        partsource = models.PartSource.objects.create(part=part, url="https://example.com", lead_time=7,
                                                      rrp=1.00, minimum_order=10)
        self.assertIsNotNone(partsource)
        self.assertEqual(partsource.part, part)
        self.assertGreater(models.PartSource.objects.all().count(), 0)

        # Sub Assembly
        # Name
        # Description
        # Revision (e.g. semver 1.2.3)
        # Explosion Date (e.g 2010)
        # Is Top Level
        # Created Timestamp
        # Updated Timestamp
        # List of Sub Assembly Line Item
        subassembly = models.SubAssembly.objects.create(reference="MAIN", name="Main Product Assembly",
                                                        revision="1.0", is_toplevel=True, team=team)
        subassembly2 = models.SubAssembly.objects.create(reference="LEG", name="Leg of Main Product", revision="1.0",
                                                         is_toplevel=False, team=team, project=subassembly)
        subassembly3 = models.SubAssembly.objects.create(reference="SHELF", name="Shelf of Main Product", revision="1.0",
                                                         is_toplevel=False, team=team, project=subassembly)
        self.assertIsNotNone(subassembly)
        self.assertGreater(models.SubAssembly.objects.all().count(), 0)

        # Sub Assembly Line Item
        # Part OR Sub Assembly Reference
        # Quantity
        # Notes
        subline = models.SubAssemblyLineItem.objects.create(child_part=part, subassembly=subassembly, quantity=10,
                                                            notes="We need a lot of these")
        subline2 = models.SubAssemblyLineItem.objects.create(child_subassembly=subassembly2, subassembly=subassembly,
                                                             quantity=3, notes="For stability")
        subline3 = models.SubAssemblyLineItem.objects.create(child_part=part, subassembly=subassembly2, quantity=10,
                                                            notes="We need a lot of legs")
        subline4 = models.SubAssemblyLineItem.objects.create(child_subassembly=subassembly2, subassembly=subassembly3,
                                                             quantity=3, notes="For stability")

        self.assertIn(subline, subassembly.line_items.all())
        self.assertIn(subline2, subassembly.line_items.all())
        self.assertIn(subline3, subassembly2.line_items.all())
        self.assertIn(subline4, subassembly3.line_items.all())

        self.assertIn(subline2, subassembly2.child_subassembly.all())
        self.assertIn(subline4, subassembly2.child_subassembly.all())

        self.assertIn(subassembly, part.find_using_assemblies())
        self.assertIn(subassembly2, part.find_using_assemblies())

        self.assertEqual(models.SubAssemblyLineItem.objects.all().count(), 4)

        # Create some parts and add them to a deal
        ps = [factories.PartFactory() for x in range(5)]
        deal = factories.DealFactory()

        for p in ps:
            factories.DealLineItemFactory(part=p, deal=deal)

        # Check the data makes sense
        self.assertEqual(deal.parts.count(), len(ps))
        for dl in deal.deallineitem_set.all():
            self.assertIn(dl.part, ps)
            self.assertGreater(dl.quantity, 0)


class SubAssemblyForkTests(TestCase):
    def setUp(self):
        self.team = models.Team.objects.create(name='Fork Team')
        self.part = models.Part.objects.create(reference='PART-FORK-1', name='Part Fork 1', team=self.team)

        self.root = models.SubAssembly.objects.create(
            reference='PROJECT-A', name='Project A', revision='1.0.0', is_toplevel=True, team=self.team
        )
        self.branch_a = models.SubAssembly.objects.create(
            reference='BRANCH-A', name='Branch A', revision='1.0.0', is_toplevel=False, team=self.team, project=self.root
        )
        self.branch_b = models.SubAssembly.objects.create(
            reference='BRANCH-B', name='Branch B', revision='1.0.0', is_toplevel=False, team=self.team, project=self.root
        )
        self.shared = models.SubAssembly.objects.create(
            reference='SHARED-1', name='Shared 1', revision='1.0.0', is_toplevel=False, team=self.team, project=self.root
        )

        models.SubAssemblyLineItem.objects.create(subassembly=self.root, child_subassembly=self.branch_a, quantity=1)
        models.SubAssemblyLineItem.objects.create(subassembly=self.root, child_subassembly=self.branch_b, quantity=1)
        models.SubAssemblyLineItem.objects.create(subassembly=self.branch_a, child_subassembly=self.shared, quantity=2)
        models.SubAssemblyLineItem.objects.create(subassembly=self.branch_b, child_subassembly=self.shared, quantity=3)
        models.SubAssemblyLineItem.objects.create(subassembly=self.shared, child_part=self.part, quantity=4)

        models.Attachment.objects.create(
            content_object=self.root,
            attachment_file=SimpleUploadedFile('root-note.txt', b'root-note-content', content_type='text/plain')
        )
        models.Attachment.objects.create(
            content_object=self.shared,
            attachment_file=SimpleUploadedFile('shared-note.txt', b'shared-note-content', content_type='text/plain')
        )

    def test_copy_tree_copies_project_graph(self):
        copied_root = self.root.copy_tree()

        self.assertNotEqual(copied_root.id, self.root.id)
        self.assertEqual(copied_root.reference, self.root.reference)
        self.assertTrue(copied_root.is_toplevel)
        self.assertEqual(copied_root.project_id, copied_root.id)
        self.assertEqual(copied_root.original_id, self.root.id)

        copied_nodes = models.SubAssembly.objects.filter(project=copied_root)
        self.assertEqual(copied_nodes.count(), 4)

        copied_shared = models.SubAssembly.objects.filter(project=copied_root, original=self.shared)
        self.assertEqual(copied_shared.count(), 1)

        copied_branch_a = models.SubAssembly.objects.get(project=copied_root, original=self.branch_a)
        copied_branch_b = models.SubAssembly.objects.get(project=copied_root, original=self.branch_b)
        copied_shared_node = copied_shared.first()

        self.assertEqual(
            models.SubAssemblyLineItem.objects.filter(
                subassembly=copied_branch_a,
                child_subassembly=copied_shared_node,
                quantity=2
            ).count(),
            1
        )
        self.assertEqual(
            models.SubAssemblyLineItem.objects.filter(
                subassembly=copied_branch_b,
                child_subassembly=copied_shared_node,
                quantity=3
            ).count(),
            1
        )

    def test_copy_tree_uses_target_reference_for_fork_root(self):
        copied_root = self.root.copy_tree(new_reference='PROJECT-A-FORK')

        self.assertEqual(copied_root.reference, 'PROJECT-A-FORK')
        self.assertEqual(copied_root.forked, self.root)

        copied_branch = models.SubAssembly.objects.get(project=copied_root, original=self.branch_a)
        self.assertEqual(copied_branch.forked, self.branch_a)

    def test_copy_tree_copies_attachments(self):
        copied_root = self.root.copy_tree()
        copied_shared = models.SubAssembly.objects.get(project=copied_root, original=self.shared)

        copied_root_attachments = list(models.Attachment.objects.attachments_for_object(copied_root))
        copied_shared_attachments = list(models.Attachment.objects.attachments_for_object(copied_shared))

        self.assertEqual(len(copied_root_attachments), 1)
        self.assertEqual(len(copied_shared_attachments), 1)

        self.assertNotEqual(copied_root_attachments[0].pk, models.Attachment.objects.attachments_for_object(self.root).first().pk)
        self.assertNotEqual(copied_shared_attachments[0].pk, models.Attachment.objects.attachments_for_object(self.shared).first().pk)

        with copied_root_attachments[0].attachment_file.open('rb') as fh:
            self.assertEqual(fh.read(), b'root-note-content')
        with copied_shared_attachments[0].attachment_file.open('rb') as fh:
            self.assertEqual(fh.read(), b'shared-note-content')

    def test_markdown_reference_lookup_is_project_scoped(self):
        project_b = models.SubAssembly.objects.create(
            reference='PROJECT-B', name='Project B', revision='1.0.0', is_toplevel=True, team=self.team
        )
        shared_other_project = models.SubAssembly.objects.create(
            reference='SHARED-1',
            name='Shared Outside Project',
            revision='1.0.0',
            is_toplevel=False,
            team=self.team,
            project=project_b,
        )

        rendered = as_markdown('Use `SHARED-1` here', self.root)
        expected_url = str(reverse_lazy('bom:assembly_editor_update', kwargs={'pk': self.shared.id}))
        unexpected_url = str(reverse_lazy('bom:assembly_editor_update', kwargs={'pk': shared_other_project.id}))

        self.assertIn(expected_url, rendered)
        self.assertNotIn(unexpected_url, rendered)

