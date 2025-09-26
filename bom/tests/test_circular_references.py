from django.test import TestCase
from django.core.exceptions import ValidationError
from bom.models import SubAssembly, SubAssemblyLineItem
from bom.tests.factories import TeamFactory


class CircularReferenceTests(TestCase):
    def setUp(self):
        self.team = TeamFactory()

        # Create three test assemblies
        self.assembly_top = SubAssembly.objects.create(
            reference="TOP", name="Top Level Assembly", revision="1.0.0", is_toplevel=True, team=self.team
        )

        self.assembly_mid = SubAssembly.objects.create(
            reference="MID",
            name="Mid Level Assembly",
            revision="1.0.0",
            is_toplevel=False,
            team=self.team,
            project=self.assembly_top,
        )

        self.assembly_bottom = SubAssembly.objects.create(
            reference="BOTTOM",
            name="Bottom Level Assembly",
            revision="1.0.0",
            is_toplevel=False,
            team=self.team,
            project=self.assembly_top,
        )

    def test_direct_self_reference(self):
        """Test that an assembly cannot contain itself directly"""

        # Try to create a line item that references itself
        line_item = SubAssemblyLineItem(subassembly=self.assembly_top, child_subassembly=self.assembly_top, quantity=1)

        # Should raise ValidationError when cleaned
        with self.assertRaises(ValidationError):
            line_item.clean()

        # Should also raise ValidationError when saved
        with self.assertRaises(ValidationError):
            line_item.save()

    def test_simple_circular_reference(self):
        """Test that two assemblies cannot contain each other (A→B→A)"""

        # Create a valid reference: top → mid
        SubAssemblyLineItem.objects.create(
            subassembly=self.assembly_top, child_subassembly=self.assembly_mid, quantity=1
        )

        # Try to create a circular reference: mid → top
        line_item = SubAssemblyLineItem(subassembly=self.assembly_mid, child_subassembly=self.assembly_top, quantity=1)

        # Should raise ValidationError
        with self.assertRaises(ValidationError):
            line_item.clean()

        # Should also raise ValidationError when saved
        with self.assertRaises(ValidationError):
            line_item.save()

    def test_deep_circular_reference(self):
        """Test that a deep circular reference is prevented (A→B→C→A)"""

        # Create valid references: top → mid → bottom
        SubAssemblyLineItem.objects.create(
            subassembly=self.assembly_top, child_subassembly=self.assembly_mid, quantity=1
        )

        SubAssemblyLineItem.objects.create(
            subassembly=self.assembly_mid, child_subassembly=self.assembly_bottom, quantity=1
        )

        # Try to create a circular reference: bottom → top
        line_item = SubAssemblyLineItem(
            subassembly=self.assembly_bottom, child_subassembly=self.assembly_top, quantity=1
        )

        # Should raise ValidationError
        with self.assertRaises(ValidationError):
            line_item.clean()

        # Should also raise ValidationError when saved
        with self.assertRaises(ValidationError):
            line_item.save()

    def test_get_all_descendants(self):
        """Test that get_all_descendants correctly identifies descendant assemblies"""

        # Create a hierarchy: top → mid → bottom
        SubAssemblyLineItem.objects.create(
            subassembly=self.assembly_top, child_subassembly=self.assembly_mid, quantity=1
        )

        SubAssemblyLineItem.objects.create(
            subassembly=self.assembly_mid, child_subassembly=self.assembly_bottom, quantity=1
        )

        # Test descendant tracking
        descendants = self.assembly_top.get_all_descendants()
        self.assertIn(self.assembly_top.id, descendants)
        self.assertIn(self.assembly_mid.id, descendants)
        self.assertIn(self.assembly_bottom.id, descendants)

        descendants = self.assembly_mid.get_all_descendants()
        self.assertIn(self.assembly_mid.id, descendants)
        self.assertIn(self.assembly_bottom.id, descendants)
        self.assertNotIn(self.assembly_top.id, descendants)

        descendants = self.assembly_bottom.get_all_descendants()
        self.assertIn(self.assembly_bottom.id, descendants)
        self.assertNotIn(self.assembly_top.id, descendants)
        self.assertNotIn(self.assembly_mid.id, descendants)

    def test_valid_reference_still_works(self):
        """Test that valid hierarchical references still work"""

        # These should all succeed
        try:
            # top → mid
            SubAssemblyLineItem.objects.create(
                subassembly=self.assembly_top, child_subassembly=self.assembly_mid, quantity=1
            )

            # top → bottom
            SubAssemblyLineItem.objects.create(
                subassembly=self.assembly_top, child_subassembly=self.assembly_bottom, quantity=1
            )

            # mid → bottom
            SubAssemblyLineItem.objects.create(
                subassembly=self.assembly_mid, child_subassembly=self.assembly_bottom, quantity=1
            )

            # This passes the test
            self.assertTrue(True)
        except ValidationError:
            # If we get here, the test fails
            self.fail("Valid hierarchical assembly references raised ValidationError")

    def test_complex_hierarchy(self):
        """Test a more complex hierarchy with multiple branches"""
        # Create additional assemblies for a more complex tree
        assembly_a = SubAssembly.objects.create(
            reference="A", name="Assembly A", revision="1.0.0", team=self.team, project=self.assembly_top
        )

        assembly_b = SubAssembly.objects.create(
            reference="B", name="Assembly B", revision="1.0.0", team=self.team, project=self.assembly_top
        )

        assembly_c = SubAssembly.objects.create(
            reference="C", name="Assembly C", revision="1.0.0", team=self.team, project=self.assembly_top
        )

        # Create a valid complex hierarchy
        # top → [a, b]
        # a → c
        # b → c

        # top → a
        SubAssemblyLineItem.objects.create(subassembly=self.assembly_top, child_subassembly=assembly_a, quantity=1)

        # top → b
        SubAssemblyLineItem.objects.create(subassembly=self.assembly_top, child_subassembly=assembly_b, quantity=1)

        # a → c
        SubAssemblyLineItem.objects.create(subassembly=assembly_a, child_subassembly=assembly_c, quantity=1)

        # b → c
        SubAssemblyLineItem.objects.create(subassembly=assembly_b, child_subassembly=assembly_c, quantity=1)

        # The following should all fail with validation errors
        # c → top (would create cycle)
        line_item = SubAssemblyLineItem(subassembly=assembly_c, child_subassembly=self.assembly_top, quantity=1)
        with self.assertRaises(ValidationError):
            line_item.clean()

        # c → a (would create cycle)
        line_item = SubAssemblyLineItem(subassembly=assembly_c, child_subassembly=assembly_a, quantity=1)
        with self.assertRaises(ValidationError):
            line_item.clean()

        # c → b (would create cycle)
        line_item = SubAssemblyLineItem(subassembly=assembly_c, child_subassembly=assembly_b, quantity=1)
        with self.assertRaises(ValidationError):
            line_item.clean()
