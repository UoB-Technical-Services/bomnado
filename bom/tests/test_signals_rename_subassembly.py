import uuid
from django.test import TestCase
from bom.tests.factories import PartFactory, SubAssemblyFactory, SubAssemblyLineItemFactory
from bom.models import Part, SubAssembly, SubAssemblyLineItem
from bom.utils.reference_tools import ReferenceSearch
# SubAssembly
class TestSubAssemblyRename(TestCase):
    def setUp(self):
        super(TestCase, self).setUp()
        self.sub_assembly1 = SubAssemblyFactory(
            reference="sub1",
            instructions=f'attach `{"sub1"}` to `{"sub1"}`',
            is_toplevel=True
        )
        self.sub_assembly2 = SubAssemblyFactory(
            instructions=f'attach `{self.sub_assembly1.reference}` to `{self.sub_assembly1.reference}`',
            project=self.sub_assembly1
        )
        self.sub_assembly3 = SubAssemblyFactory(
            instructions=f'attach `{self.sub_assembly1.reference}` to `{self.sub_assembly2.reference}`',
            project=self.sub_assembly1
        )
        self.sub_assembly4 = SubAssemblyFactory(
            instructions=f'attach `{self.sub_assembly1.reference}` to `{self.sub_assembly3.reference}`',
            project=self.sub_assembly1
        )
        self.sub_assembly5 = SubAssemblyFactory(
            instructions=f'attach `{self.sub_assembly2.reference}` to `{self.sub_assembly4.reference}`',
            project=self.sub_assembly1
        )
        self.part1 = PartFactory()
        self.part2 = PartFactory(spec=f'uses `{self.sub_assembly1.reference}`')
        self.part3 = PartFactory(spec=f'uses `{self.sub_assembly1.reference}` in `{self.sub_assembly2.reference}`')
        self.part4 = PartFactory(spec=f'uses `{self.sub_assembly2.reference}`')
        self.part5 = PartFactory(spec=f'uses `{self.sub_assembly3.reference}`')
        self.sub_assembly_line_item1 = SubAssemblyLineItemFactory()
        self.sub_assembly_line_item2 = SubAssemblyLineItemFactory(
            notes=f'`{self.sub_assembly1.reference}`\n`{self.sub_assembly1.reference}`',
        )
        self.sub_assembly_line_item3 = SubAssemblyLineItemFactory(
            notes=f'`{self.sub_assembly2.reference}`\n`{self.sub_assembly3.reference}`'
        )
        self.sub_assembly_line_item4 = SubAssemblyLineItemFactory(
            notes=f'`{self.sub_assembly1.reference}`\n`{self.sub_assembly2.reference}`'
        )
        self.sub_assembly_line_item5 = SubAssemblyLineItemFactory(
            notes=f'`{self.sub_assembly1.reference}`\n`{self.sub_assembly3.reference}`'
        )
        self.sub_assembly_line_item6 = SubAssemblyLineItemFactory(
            notes=f'`{self.sub_assembly1.reference}`\n`{self.sub_assembly4.reference}`'
        )
    def tearDown(self):
        super(TestCase, self).tearDown()
    def test_rename_part1(self):
        old_ref = self.sub_assembly1.reference
        find_results = ReferenceSearch(old_ref)
        self.assertEqual(find_results.items[SubAssembly].count(), 4)
        self.assertEqual(find_results.items[SubAssemblyLineItem].count(), 4)
        self.assertEqual(find_results.items[Part].count(), 2)
        new_ref = str(uuid.uuid4())[:8].upper()
        self.sub_assembly1.reference = new_ref
        self.sub_assembly1.save()
        find_results = ReferenceSearch(old_ref)
        self.assertEqual(find_results.items[SubAssembly].count(), 0)
        self.assertEqual(find_results.items[SubAssemblyLineItem].count(), 0)
        self.assertEqual(find_results.items[Part].count(), 0)
        find_results = ReferenceSearch(new_ref)
        self.assertEqual(find_results.items[SubAssembly].count(), 4)
        self.assertEqual(find_results.items[SubAssemblyLineItem].count(), 4)
        self.assertEqual(find_results.items[Part].count(), 2)
        # parts
        self.assertNotEqual(Part.objects.get(pk=self.part2.pk).spec, f'uses `{old_ref}`')
        self.assertNotEqual(Part.objects.get(pk=self.part3.pk).spec, f'uses `{old_ref}` in `{self.sub_assembly2.reference}`')
        self.assertEqual(Part.objects.get(pk=self.part3.pk).spec, f'uses `{new_ref}` in `{self.sub_assembly2.reference}`')
        self.assertEqual(Part.objects.get(pk=self.part5.pk).spec, self.part5.spec)
        # sub_assembly
        self.assertNotEqual(SubAssembly.objects.get(pk=self.sub_assembly4.pk).instructions, f'attach `{old_ref}` to `{self.sub_assembly3.reference}`')
        self.assertNotEqual(SubAssembly.objects.get(pk=self.sub_assembly3.pk).instructions, f'attach `{old_ref}` to `{old_ref}`')
        self.assertEqual(SubAssembly.objects.get(pk=self.sub_assembly4.pk).instructions, f'attach `{new_ref}` to `{self.sub_assembly3.reference}`')
        self.assertEqual(SubAssembly.objects.get(pk=self.sub_assembly2.pk).instructions, f'attach `{new_ref}` to `{new_ref}`')
        self.assertEqual(SubAssembly.objects.get(pk=self.sub_assembly5.pk).instructions, self.sub_assembly5.instructions)
        # sub_assembly_line_items
        self.assertNotEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item2.pk).notes, f'`{old_ref}`\n`{old_ref}`')
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item2.pk).notes, f'`{new_ref}`\n`{new_ref}`')
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item3.pk).notes, self.sub_assembly_line_item3.notes)
        self.assertEqual(SubAssemblyLineItem.objects.get(pk=self.sub_assembly_line_item4.pk).notes, f'`{new_ref}`\n`{self.sub_assembly2.reference}`')
