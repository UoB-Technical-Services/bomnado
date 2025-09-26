"""
Decorators for first-time setup functionality
"""
import os
from functools import wraps
from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect
from django.urls import reverse


def setup_required(view_func):
    """
    Decorator that redirects to first-time setup if the application hasn't been initialized.

    Checks:
    1. Database exists and is migrated
    2. At least one superuser exists

    Usage:
        @setup_required
        def my_view(request):
            # This view will only be accessible after setup is complete
            pass
    """
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        # Check if setup is needed
        if _needs_setup():
            return HttpResponseRedirect(reverse('bom:first_time_setup'))

        # Setup is complete, proceed with the original view
        return view_func(request, *args, **kwargs)

    return wrapped_view


def setup_complete_required(view_func):
    """
    Decorator that ensures setup is complete AND blocks access to setup pages after completion.

    This is useful for views that should only be accessible during initial setup.
    """
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        # If setup is complete, redirect away from setup pages
        if not _needs_setup():
            return HttpResponseRedirect(reverse('bom:start'))

        # Setup is needed, proceed with the setup view
        return view_func(request, *args, **kwargs)

    return wrapped_view


def _needs_setup():
    """
    Internal function to check if first-time setup is needed.
    Database-agnostic version that works with SQLite, PostgreSQL, and other backends

    Returns:
        bool: True if setup is needed, False if setup is complete
    """
    try:
        # Check if the database file exists (for SQLite)
        if hasattr(settings, 'DATABASES'):
            db_config = settings.DATABASES.get('default', {})
            if db_config.get('ENGINE') == 'django.db.backends.sqlite3':
                db_path = db_config.get('NAME')
                if db_path and not os.path.exists(db_path):
                    return True

        # Database-agnostic check: Try to access the User model
        # This will fail if tables don't exist (works for all database backends)
        try:
            # This query will raise an exception if the auth_user table doesn't exist
            User.objects.count()
        except Exception:
            # Tables don't exist or database connection issues
            return True

        # Check if any superusers exist
        if not User.objects.filter(is_superuser=True).exists():
            return True

        return False

    except Exception:
        # If there's any database error, assume setup is needed
        return True


def is_setup_complete():
    """
    Public function to check if setup is complete.

    Returns:
        bool: True if setup is complete, False if setup is needed
    """
    return not _needs_setup()