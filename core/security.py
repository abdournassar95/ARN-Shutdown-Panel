"""
Password hashing helpers (PBKDF2-HMAC-SHA256).

Settings must never store the LAN password in plain text. The stored format is
self-describing so the iteration count can be raised later without breaking
existing files::

    pbkdf2_sha256$<iterations>$<salt-b64>$<hash-b64>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 240_000
_SALT_BYTES = 16


def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    """Returns a salted PBKDF2 hash for *password*."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            _ALGORITHM,
            str(int(iterations)),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def is_password_hash(value: Optional[str]) -> bool:
    """True when *value* looks like a hash produced by :func:`hash_password`."""
    if not isinstance(value, str):
        return False
    parts = value.split("$")
    return len(parts) == 4 and parts[0] == _ALGORITHM


def verify_password(password: str, stored: Optional[str]) -> bool:
    """Constant-time check of *password* against a stored hash.

    Returns False for empty input, malformed hashes, and legacy plain-text
    values (plain text must be migrated by the caller before it reaches here).
    """
    if not password or not stored or not is_password_hash(stored):
        return False
    try:
        _, iterations, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)
