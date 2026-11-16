"""Password hashing with scrypt from the standard library (ADR-031).

Stored format: ``scrypt$<n>$<r>$<p>$<salt base64>$<hash base64>``, so the cost
can be raised later without breaking existing hashes. The default cost
(n=2**15, r=8, p=3, about 32 MiB per hash) is an OWASP-listed scrypt setting.
At most a few hashes run at once, which bounds memory when many logins arrive.
Passwords are never logged.
"""

import base64
import hashlib
import hmac
import re
import secrets
import threading

SCRYPT_R = 8
SCRYPT_P = 3
DEFAULT_N = 2**15
MIN_PASSWORD_CHARS = 12
# Long inputs only cost CPU; nobody needs more.
MAX_PASSWORD_CHARS = 128
_SALT_BYTES = 16
_KEY_BYTES = 32
_HASH_SLOTS = threading.BoundedSemaphore(4)
_FORMAT = re.compile(r"scrypt\$(\d+)\$(\d+)\$(\d+)\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)")


class PasswordPolicyError(ValueError):
    """The password does not meet the policy; the message is safe to show."""


def check_password_policy(password: str, username: str) -> None:
    if not MIN_PASSWORD_CHARS <= len(password) <= MAX_PASSWORD_CHARS:
        raise PasswordPolicyError(
            f"The password must have {MIN_PASSWORD_CHARS}-{MAX_PASSWORD_CHARS} characters."
        )
    if username.lower() in password.lower():
        raise PasswordPolicyError("The password must not contain the username.")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    with _HASH_SLOTS:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=256 * r * n + 1024 * 1024,
            dklen=_KEY_BYTES,
        )


def hash_password(password: str, *, n: int = DEFAULT_N) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _derive(password, salt, n, SCRYPT_R, SCRYPT_P)
    encoded = [base64.b64encode(value).decode("ascii") for value in (salt, key)]
    return f"scrypt${n}${SCRYPT_R}${SCRYPT_P}${encoded[0]}${encoded[1]}"


def verify_password(password: str, stored: str) -> bool:
    """True if the password matches; False for any malformed stored value."""
    match = _FORMAT.fullmatch(stored)
    if match is None or len(password) > MAX_PASSWORD_CHARS:
        return False
    n, r, p = (int(match.group(i)) for i in (1, 2, 3))
    if n > 2**20 or r > 16 or p > 16:  # refuse costs nobody configured
        return False
    salt, expected = (base64.b64decode(match.group(i)) for i in (4, 5))
    return hmac.compare_digest(_derive(password, salt, n, r, p), expected)
