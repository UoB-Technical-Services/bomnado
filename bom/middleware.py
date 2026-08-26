"""
Middleware for handling first-time setup
"""
import os
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponseRedirect
from django.urls import reverse, resolve
from django.utils.deprecation import MiddlewareMixin


""" Cache key set once setup is known to be complete, so the per-request migration
and superuser checks are skipped from then on. """
SETUP_COMPLETE_CACHE_KEY = 'bomnado_first_time_setup_complete'


def mark_setup_incomplete():
    """ Forget that setup was complete. Call after wiping the database. """
    cache.delete(SETUP_COMPLETE_CACHE_KEY)


class FirstTimeSetupMiddleware(MiddlewareMixin):
    """
    Middleware to redirect users to first-time setup if no superuser exists.

    Checking the migration plan on every request is expensive, so once the
    checks pass the result is latched in the cache (see `_needs_setup`).
    """

    def process_request(self, request):
        # Get current URL info
        try:
            current_url = resolve(request.path_info)
        except Exception:
            # If URL resolution fails, let it through
            return None

        # Always allow access to these URLs
        allowed_urls = [
            'first_time_setup',
            'first_time_setup_api',
            'first_time_setup_complete',
            'first_time_setup_demo',
            'admin:login',
            'admin:logout',
            'login',
            'logout',
        ]

        # Skip for static/media files and allowed URLs
        if (request.path_info.startswith('/static/')
                or request.path_info.startswith('/media/')
                or request.path_info.startswith('/favicon.ico')
                or current_url.url_name in allowed_urls):
            return None

        # Check if setup is needed
        if self._needs_setup():
            # Only redirect if we're not already on a setup page
            if current_url.url_name not in allowed_urls:
                return HttpResponseRedirect(reverse('bom:first_time_setup'))

        return None

    def _needs_setup(self):
        """
        Check if first-time setup is needed
        Database-agnostic version that works with SQLite, PostgreSQL, and other backends
        """
        try:
            # For SQLite, check if database file exists first. This is cheap and is
            # always done, so deleting the file is noticed even when the result below
            # has been latched.
            if hasattr(settings, 'DATABASES'):
                db_config = settings.DATABASES.get('default', {})
                if db_config.get('ENGINE') == 'django.db.backends.sqlite3':
                    db_path = db_config.get('NAME')
                    if db_path and not os.path.exists(db_path):
                        mark_setup_incomplete()
                        return True

            # Once setup has been seen to be complete, skip the expensive checks.
            if cache.get(SETUP_COMPLETE_CACHE_KEY):
                return False

            # Check if migrations need to be applied using Django's migration executor
            try:
                executor = MigrationExecutor(connection)
                plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
                if plan:
                    # There are unapplied migrations
                    return True
            except Exception:
                # Migration system issues or database connection problems
                return True

            # Check if any superusers exist
            try:
                if not User.objects.filter(is_superuser=True).exists():
                    return True
            except Exception:
                # If we can't query users, migrations probably haven't been applied
                return True

            cache.set(SETUP_COMPLETE_CACHE_KEY, True, None)
            return False

        except Exception:
            # If there's any database error, assume setup is needed
            return True