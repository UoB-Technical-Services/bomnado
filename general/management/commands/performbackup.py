from django.core.management.base import BaseCommand

from general.tasks import perform_full_backup


class Command(BaseCommand):
    help = "Perform a Backup of both media and database files"

    def handle(self, *args, **options):
        perform_full_backup()
