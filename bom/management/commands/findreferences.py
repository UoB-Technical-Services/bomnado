from django.core.management.base import BaseCommand
from bom.utils.reference_tools import ReferenceSearch


class Command(BaseCommand):
    """
    Find where a provided reference is used within instructions, specification and notes


    SAMPLE

        bom.Part.spec@BS-IT1 --> 1 times
        bom.PartSource.order_notes@PartSource object (1) --> 1 times
        bom.SubAssembly.instructions@Documentation for Main Product --> 2 times
        bom.SubAssembly.qc_steps@Documentation for Main Product --> 1 times
        bom.SubAssemblyLineItem.notes@1 * DOCWALLET-RED2 --> 1 times
    """
    help = 'Find where a provided reference is used within instructions, specification, and notes, etc.'

    def add_arguments(self, parser):
        parser.add_argument('reference', type=str)

    def handle(self, *args, **options):

        term = options['reference'].strip()
        print('Searching for:', term)

        search = ReferenceSearch(term)
        counter = search.count()

        for field in counter:
            print(field, '-->', counter[field], 'times')
