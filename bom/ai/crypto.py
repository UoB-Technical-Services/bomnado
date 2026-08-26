""" Encryption at rest for users' API keys.

Fernet (AES-128-CBC + HMAC) from `cryptography`, keyed by `BOMNADO_FERNET_KEY` when set,
otherwise by a key derived from `SECRET_KEY`. Set `BOMNADO_FERNET_KEY` in production so
rotating `SECRET_KEY` does not silently orphan every stored key.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = getattr(settings, 'BOMNADO_FERNET_KEY', '') or ''
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext):
    """ `str` -> opaque `str` safe to store. Empty in, empty out. """
    if not plaintext:
        return ''
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token):
    """ The inverse of `encrypt`. Anything that does not decrypt (wrong key, tampered) reads as ''. """
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ''
