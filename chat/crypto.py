"""Chat message text is encrypted at rest with Fernet (AES plus an HMAC,
from the `cryptography` package). Keys come from CHAT_ENCRYPTION_KEYS, never
from the repository or SECRET_KEY: the first key encrypts and every key
decrypts, so keys can be rotated (manage.py rotate_chat_keys). Losing every
key loses every message; there is no recovery."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Shown in place of a message that can't be decrypted (lost key, damage).
UNREADABLE = "This message can't be shown."


class ChatKeyMissing(ImproperlyConfigured):
    pass


@lru_cache(maxsize=8)
def _fernet(keys):
    return MultiFernet([Fernet(key) for key in keys])


def _current():
    keys = tuple(settings.CHAT_ENCRYPTION_KEYS)
    if not keys:
        raise ChatKeyMissing("Chat isn't set up: CHAT_ENCRYPTION_KEYS is not set.")
    return _fernet(keys)


def encrypt(text):
    return _current().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token):
    """The text, or None if no key can decrypt it (or none is set)."""
    try:
        return _current().decrypt(token.encode("ascii")).decode("utf-8")
    except (ChatKeyMissing, InvalidToken, UnicodeError, ValueError):
        return None


def rotate(token):
    """Re-encrypt with the first key. Raises InvalidToken if unreadable."""
    return _current().rotate(token.encode("ascii")).decode("ascii")
