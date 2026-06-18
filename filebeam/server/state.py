"""Process-wide application state shared by the admin + public servers.

Holds the DB, the signed-cookie signer, the active tunnel backend, the current
public URL (and a flag when it changes so the UI can warn), and the watchdog
observer for watched folders.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from ..config import Config, get_config
from ..tunnels.base import TunnelBackend, TunnelState, TunnelStatus
from ..tunnels.registry import make_backend
from .db import DB
from .session import Signer


class TunnelManager:
    """Owns the lifecycle of the selected TunnelBackend."""

    def __init__(self, config: Config):
        self.config = config
        self.backend: Optional[TunnelBackend] = None
        self.backend_name: Optional[str] = None
        self.public_url: Optional[str] = None
        self.previous_url: Optional[str] = None
        self.url_changed_at: float = 0.0       # when URL last changed while running
        self._lock = threading.Lock()
        self._url_listeners: list = []

    def add_listener(self, cb) -> None:
        self._url_listeners.append(cb)

    def _on_url(self, url: str) -> None:
        with self._lock:
            if self.public_url and url and url != self.public_url:
                self.previous_url = self.public_url
                self.url_changed_at = time.time()
            self.public_url = url
        for cb in list(self._url_listeners):
            try:
                cb(url)
            except Exception:
                pass

    @property
    def local_url(self) -> str:
        # Tunnels always connect over loopback even when the server also binds
        # to other interfaces (0.0.0.0 includes 127.0.0.1).
        return f"http://127.0.0.1:{self.config.share_port}"

    def start(self, name: Optional[str] = None) -> str:
        self.stop()
        name = name or self.config.backend_name
        opts = self.config.backend_opts(name)
        backend = make_backend(name, self.local_url, opts)
        backend.on_url_change(self._on_url)
        self.backend = backend
        self.backend_name = name
        url = backend.start()
        self._on_url(url)
        return url

    def stop(self) -> None:
        if self.backend:
            try:
                self.backend.stop()
            finally:
                self.backend = None
        with self._lock:
            self.public_url = None

    def status(self) -> TunnelStatus:
        if self.backend:
            return self.backend.status()
        return TunnelStatus(state=TunnelState.STOPPED)

    def ack_url_change(self) -> None:
        with self._lock:
            self.previous_url = None
            self.url_changed_at = 0.0


class AppState:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.db = DB(self.config.db_path)
        self.signer = Signer(self.config.data_dir)
        self.tunnel = TunnelManager(self.config)
        self._observer = None
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        # Ensure baseline groups exist so the admin has something to map.
        if not self.db.groups():
            for name in ("admin", "team", "guest"):
                self.db.create_group(name, None)

    # --- watched folders ---------------------------------------------------
    def start_watcher(self) -> None:
        """(Re)build the watchdog observer over all watched folders.

        Watching is purely informational here — files placed in a watched folder
        are already downloadable because the folder maps to a real directory.
        The observer lets the admin UI reflect new files without a manual scan.
        """
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except Exception:
            return
        self.stop_watcher()
        observer = Observer()

        class _Handler(FileSystemEventHandler):
            pass

        watched = self.db.watched_folders()
        if not watched:
            return
        handler = _Handler()
        for f in watched:
            p = Path(f["abs_path"])
            if p.is_dir():
                observer.schedule(handler, str(p), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer

    def stop_watcher(self) -> None:
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None


_state: Optional[AppState] = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state


def set_state(state: AppState) -> None:
    global _state
    _state = state
