"""
Helpers for creating user accounts.
"""
import re

from django.contrib.auth.models import User


def username_from_email(email):
    """ Derive a valid, unique username from an email address.

    Uses the lower-cased local part (``New.Person@example.com`` -> ``new.person``), dropping
    any characters Django's username validator rejects, and appends a number
    if that handle is already taken (``john`` -> ``john2``). People sign in with
    their email address; the username is only a short display handle, which
    they can change on their settings page.
    """
    local_part = email.split('@', 1)[0]
    base = re.sub(r'[^\w.@+-]', '', local_part).lower()[:140] or 'user'
    candidate, suffix = base, 2
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f'{base}{suffix}'
        suffix += 1
    return candidate
