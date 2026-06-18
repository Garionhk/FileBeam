"""Optional LAN-only backend: no tunnel, just expose on the local network.

Returns http://<lan-ip>:PORT. Reachable only by devices on the same network.
NOTE: the OS firewall may prompt once to allow incoming connections — this is
the single exception to the "no firewall changes" rule, and only for LAN mode.
"""
from __future__ import annotations

import socket
from typing import Optional
from urllib.parse import urlparse

from .base import TunnelBackend, TunnelState


def _lan_ip() -> str:
    """Best-effort primary LAN IP (no traffic actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class LanOnlyBackend(TunnelBackend):
    name = "lan"
    label = "LAN only (no tunnel)"
    description = "Same-network access only. May need a one-time firewall allow."

    def start(self) -> str:
        port = urlparse(self.local_url).port or 80
        url = f"http://{_lan_ip()}:{port}"
        self._set_url(url)
        self._set_state(TunnelState.RUNNING)
        return url

    def stop(self) -> None:
        self._set_url(None)
        self._set_state(TunnelState.STOPPED)
