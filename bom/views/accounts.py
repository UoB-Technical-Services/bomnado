""" Signing in and asking for a password reset, rate-limited: a handful of tries, then a short wait.

The counters live in the cache (locmem in development, Redis in production), keyed by address:
no table, no cleanup, and a restart forgives everything.
"""
from django.contrib.auth import views as auth_views
from django.core.cache import cache
from django.http import HttpResponseRedirect


def allow(key, limit, window):
    """ Count a hit against `key`; True while `key` has been hit at most `limit` times in `window` seconds. """
    key = f'bomnado.throttle.{key}'
    if cache.add(key, 1, window):
        return True
    try:
        return cache.incr(key) <= limit
    except ValueError:          # expired between add and incr
        cache.add(key, 1, window)
        return True


def client_address(request):
    return request.META.get('REMOTE_ADDR', 'unknown')


class ThrottledLoginView(auth_views.LoginView):
    """ Ten sign-in attempts a minute per address; after that, a short wait. """

    def post(self, request, *args, **kwargs):
        if not allow(f'login.{client_address(request)}', limit=10, window=60):
            return self.render_to_response(self.get_context_data(form=self.get_form(), throttled=True))
        return super().post(request, *args, **kwargs)


class ThrottledPasswordResetView(auth_views.PasswordResetView):
    """ Five reset emails an hour per address. Over the limit it goes quietly to the done page,
    exactly as a successful request does, so the throttle gives nothing away. """

    def post(self, request, *args, **kwargs):
        if not allow(f'reset.{client_address(request)}', limit=5, window=3600):
            return HttpResponseRedirect(self.get_success_url())
        return super().post(request, *args, **kwargs)
