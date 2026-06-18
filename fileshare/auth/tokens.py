"""Passcode hashing + constant-time verification.

Uses argon2 when available; falls back to a salted PBKDF2-SHA256 from stdlib so
the app still runs if the optional native wheel isn't installed.
"""
from __future__ import annotations

import hashlib
import hmac
import os

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _ph = PasswordHasher()
    _HAVE_ARGON2 = True
except Exception:  # pragma: no cover
    _ph = None
    _HAVE_ARGON2 = False


_PBKDF2_ROUNDS = 200_000


def hash_passcode(passcode: str) -> str:
    if not passcode:
        return ""
    if _HAVE_ARGON2:
        return _ph.hash(passcode)
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", passcode.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_passcode(passcode: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2$"):
        try:
            _, rounds_s, salt_hex, dk_hex = stored_hash.split("$")
            dk = hashlib.pbkdf2_hmac(
                "sha256", passcode.encode(), bytes.fromhex(salt_hex), int(rounds_s)
            )
            return hmac.compare_digest(dk.hex(), dk_hex)
        except Exception:
            return False
    if _HAVE_ARGON2:
        try:
            return _ph.verify(stored_hash, passcode)
        except VerifyMismatchError:
            return False
        except Exception:
            return False
    return False
