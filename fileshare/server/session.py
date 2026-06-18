"""Tiny signed-cookie helper (stdlib only) for the public server's identity.

We persist a random secret in the data dir so cookies survive restarts. The
cookie just carries an identity (group id + originating link id); it never
carries permissions — those are always re-checked against the DB per request.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Optional

COOKIE_NAME = "fs_id"


def _load_secret(data_dir: Path) -> bytes:
    p = data_dir / "cookie_secret"
    if p.exists():
        return p.read_bytes()
    s = secrets.token_bytes(32)
    p.write_bytes(s)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return s


class Signer:
    def __init__(self, data_dir: Path):
        self._secret = _load_secret(data_dir)

    def sign(self, payload: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        mac = hmac.new(self._secret, raw.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{raw}.{mac}"

    def unsign(self, value: str) -> Optional[dict]:
        try:
            raw, mac = value.rsplit(".", 1)
        except ValueError:
            return None
        expected = hmac.new(self._secret, raw.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(mac, expected):
            return None
        try:
            return json.loads(base64.urlsafe_b64decode(raw.encode()))
        except Exception:
            return None
