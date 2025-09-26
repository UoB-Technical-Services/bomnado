from django.test import TestCase

from bom import models
from bom.tests import factories


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

