import uuid

from django.test import TestCase

from bom.tests.factories import PartFactory, SubAssemblyFactory, SubAssemblyLineItemFactory
from bom.models import Part, SubAssembly, SubAssemblyLineItem
from bom.utils.reference_tools import ReferenceSearch

# Part
class TestPartRename(TestCase):
    def setUp(self):
        super(TestCase, self).setUp()

        self.part1 = PartFactory(reference="p1", spec=f'uses `{"p1"}`')
        self.part2 = PartFactory(spec=f'uses `{self.part1.reference}`')
        self.part3 = PartFactory(spec=f'uses `{self.part1.reference}` in `{self.part2.reference}`')
        self.part4 = PartFactory(spec=f'uses `{self.part2.reference}`')
        self.part5 = PartFactory(spec=f'uses `{self.part3.reference}`')

        self.sub_assembly1 = SubAssemblyFactory(
            instructions=f'attach `{self.part1.reference}` to `{self.part2.reference}`',
            is_toplevel=True
        )
        self.sub_assembly2 = SubAssemblyFactory(
            instructions=f'attach `{self.part1.reference}` to `{self.part3.reference}`',
            project=self.sub_assembly1
        )
        self.sub_assembly3 = SubAssemblyFactory(
            instructions=f'attach `{self.part1.reference}` to `{self.part1.reference}`',
            project=self.sub_assembly1
        )
        self.sub_assembly4 = SubAssemblyFactory(
            instructions=f'attach `{self.part2.reference}` to `{self.part4.reference}`',
            project=self.sub_assembly1
        )
        self.sub_assembly5 = SubAssemblyFactory(
            instructions=f'attach `{self.part2.reference}` to `{self.part3.reference}`',
            project=self.sub_assembly1
        )

        self.sub_assembly_line_item1 = SubAssemblyLineItemFactory()
        self.sub_assembly_line_item2 = SubAssemblyLineItemFactory(
            notes=f'`{self.part1.reference}`\n`{self.part1.reference}`'
        )
        self.sub_assembly_line_item3 = SubAssemblyLineItemFactory(
            notes=f'`{self.part2.reference}`\n`{self.part3.reference}`'
        )
        self.sub_assembly_line_item4 = SubAssemblyLineItemFactory(
            notes=f'`{self.part1.reference}`\n`{self.part2.reference}`'
        )
        self.sub_assembly_line_item5 = SubAssemblyLineItemFactory(
            notes=f'`{self.part1.reference}`\n`{self.part3.reference}`'
        )
        self.sub_assembly_line_item6 = SubAssemblyLineItemFactory(
            notes=f'`{self.part1.reference}`\n`{self.part4.reference}`'
        )

    def tearDown(self):
        super(TestCase, self).tearDown()

    def test_rename_part1(self):
        old_ref = self.part1.reference

        find_results = ReferenceSearch(old_ref)
        self.assertEqual(find_results.items[SubAssembly].count(), 3)
        self.assertEqual(find_results.items[SubAssemblyLineItem].count(), 4)
        self.assertEqual(find_results.items[Part].count(), 3)

        new_ref = str(uuid.uuid4())[:8].upper()
        self.part1.reference = new_ref
        self.part1.save()

        find_results = ReferenceSearch(old_ref)
        self.assertEqual(find_results.items[SubAssembly].count(), 0)
        self.assertEqual(find_results.items[SubAssemblyLineItem].count(), 0)
        self.assertEqual(find_results.items[Part].count(), 0)

        find_results = ReferenceSearch(new_ref)
        self.assertEqual(find_results.items[SubAssembly].count(), 3)
        self.assertEqual(find_results.items[SubAssemblyLineItem].count(), 4)
        self.assertEqual(find_results.items[Part].count(), 3)

        # parts
        self.assertNotEqual(Part.objects.get(pk=self.part2.pk).spec, f'uses `{old_ref}`')
        self.assertNotEqual(Part.objects.get(pk=self.part3.pk).spec, f'uses `{old_ref}` in `{self.part2.reference}`')
        self.assertEqual(Part.objects.get(pk=self.part3.pk).spec, f'uses `{new_ref}` in `{self.part2.reference}`')
        self.assertEqual(Part.objects.get(pk=self.part5.pk).spec, self.part5.spec)

        # sub_assembly
        self.assertNotEqual(SubAssembly.objects.get(pk=self.sub_assembly1.pk).instructions, f'attach `{old_ref}` to `{self.part2.reference}`')
        self.assertNotEqual(SubAssembly.objects.get(pk=self.sub_assembly3.pk).instructions, f'attach `{old_ref}` to `{old_ref}`')
        self.assertEqual(SubAssembly.objects.get(pk=self.sub_assembly1.pk).instructions, f'attach `{new_ref}` to `{self.part2.reference}`')
        self.assertEqual(SubAssembly.objects.get(pk=self.sub_assembly3.pk).instructions, f'attach `{new_ref}` to `{new_ref}`')
        self.assertEqual(SubAssembly.objects.get(pk=self.sub_assembly5.pk).instructions, self.sub_assembly5.instructions)

        # sub_assembly_line_items
        self.assertNotEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item2.pk).notes, f'`{old_ref}`\n`{old_ref}`')
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item2.pk).notes, f'`{new_ref}`\n`{new_ref}`')
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item3.pk).notes, self.sub_assembly_line_item3.notes)
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item4.pk).notes, f'`{new_ref}`\n`{self.part2.reference}`')
