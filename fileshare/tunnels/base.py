"""TunnelBackend interface.

Every remote-access mechanism implements this tiny surface. The core app only
ever calls start/stop/status/on_url_change — no vendor SDK leaks past here, so
backends can be swapped freely (see registry.py).

To add a backend: subclass TunnelBackend, implement the four methods, and
register it in registry.BACKENDS. ~30 lines, see localhost_run.py for a model.
"""
from __future__ import annotations

import enum
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional


class TunnelState(str, enum.Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


@dataclass
class TunnelStatus:
    state: TunnelState = TunnelState.STOPPED
    public_url: Optional[str] = None
    error: Optional[str] = None


class TunnelBackend(ABC):
    """Pluggable remote-access backend.

    Subclasses MUST call ``_set_url`` / ``_set_state`` so URL-change callbacks
    fire and status() stays accurate. Free no-account tunnels hand out a random
    URL that changes on reconnect — calling _set_url on every (re)connect is how
    the UI learns the old link died.
    """

    name = "base"
    label = "Base"
    description = ""

    def __init__(self, local_url: str, opts: Optional[dict] = None):
        self.local_url = local_url
        self.opts = opts or {}
        self._status = TunnelStatus()
        self._callbacks: list[Callable[[str], None]] = []
        self._lock = threading.Lock()

    # --- public interface --------------------------------------------------
    @abstractmethod
    def start(self) -> str:
        """Establish the tunnel and return the public URL (blocks until ready)."""

    @abstractmethod
    def stop(self) -> None:
        """Tear the tunnel down."""

    def status(self) -> TunnelStatus:
        with self._lock:
            return TunnelStatus(
                self._status.state, self._status.public_url, self._status.error
            )

    def on_url_change(self, cb: Callable[[str], None]) -> None:
        """Register a callback fired whenever the public URL appears or changes."""
        self._callbacks.append(cb)

    # --- helpers for subclasses -------------------------------------------
    def _set_state(self, state: TunnelState, error: Optional[str] = None) -> None:
        with self._lock:
            self._status.state = state
            if error is not None:
                self._status.error = error

    def _set_url(self, url: Optional[str]) -> None:
        changed = False
        with self._lock:
            if url != self._status.public_url:
                self._status.public_url = url
                changed = True
        if changed and url:
            for cb in list(self._callbacks):
                try:
                    cb(url)
                except Exception:
                    pass
