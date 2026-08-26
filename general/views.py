import os
import os.path
from functools import wraps

from django.http import HttpResponse, HttpResponseForbidden
from django.conf import settings
from django.core.management import call_command
from django.views.decorators.http import require_http_methods
from django.db import close_old_connections

from general.utils import perform_backup, perform_restore


def superuser_required(view_func):
    """ Refuse with 403 unless the request comes from an authenticated superuser.

    These views destroy or replace the whole database, so a redirect to the login
    page (what `user_passes_test` would do) is not appropriate - they are only
    ever called programmatically.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated or not user.is_superuser:
            return HttpResponseForbidden('Administrator access required.')
        return view_func(request, *args, **kwargs)
    return _wrapped


@require_http_methods(["POST"])
@superuser_required
def reset_database(request):
    """
    Reset the database
    """
    close_old_connections()

    if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
        # If the database is SQLite, delete the file
        os.remove(settings.DATABASES["default"]["NAME"])
    else:
        call_command("reset_db", "--noinput")

    call_command("migrate", "--noinput")
    return HttpResponse(status=204)


@require_http_methods(["POST"])
@superuser_required
def backup_all(request):
    """
    Backup the database + media directory
    """
    perform_backup()
    return HttpResponse(status=204)


@require_http_methods(["POST"])
@superuser_required
def restore_all(request):
    """
    Restore the database + media directory
    """
    perform_restore()
    return HttpResponse(status=204)
