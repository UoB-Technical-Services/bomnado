import os
import os.path

from django.http import HttpResponse
from django.conf import settings
from django.core.management import call_command
from django.views.decorators.http import require_http_methods
from django.db import close_old_connections

from general.utils import perform_backup, perform_restore


@require_http_methods(["POST"])
def reset_database(request):
    """
    Reset the database
    """

    if request.method == "POST":
        # Reset the database
        close_old_connections()

        if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
            # If the database is SQLite, delete the file
            os.remove(settings.DATABASES["default"]["NAME"])
        else:
            call_command("reset_db", "--noinput")

        call_command("migrate", "--noinput")
        return HttpResponse(status=204)


@require_http_methods(["POST"])
def backup_all(request):
    """
    Backup the database + media directory
    """

    if request.method == "POST":
        # Reset the database
        perform_backup()
        return HttpResponse(status=204)


@require_http_methods(["POST"])
def restore_all(request):
    """
    Restore the database + media directory
    """

    if request.method == "POST":
        # Reset the database
        perform_restore()
        return HttpResponse(status=204)
