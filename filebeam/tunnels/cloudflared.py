"""Default zero-setup backend: Cloudflare Quick Tunnel (TryCloudflare).

`cloudflared tunnel --url http://localhost:PORT` opens an OUTBOUND connection to
Cloudflare's edge and prints a random https://<words>.trycloudflare.com URL.
No account, no token, no config, no inbound ports. We bundle the binary so first
run is truly zero-setup.

The URL is random and changes on every (re)connect; we watch cloudflared's
stderr for the URL line and call _set_url each time, so the UI can warn that the
previous link is now dead.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from ..config import bundle_dir
from .base import TunnelBackend, TunnelState, no_window_kwargs

# cloudflared prints e.g.  https://random-words-here.trycloudflare.com
_URL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")


def _bundled_binary() -> Optional[Path]:
    exe = "cloudflared.exe" if sys.platform.startswith("win") else "cloudflared"
    candidates = [
        # Source layout: filebeam/packaging/bin/
        Path(__file__).resolve().parent.parent / "packaging" / "bin" / exe,
        # Bundle root variants (PyInstaller add-data target)
        bundle_dir() / "packaging" / "bin" / exe,
        bundle_dir() / "filebeam" / "packaging" / "bin" / exe,
        # PyInstaller onefile lays resources flat in _MEIPASS
        bundle_dir() / exe,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def resolve_binary(opt: str = "auto") -> Optional[str]:
    if opt and opt != "auto":
        return opt
    b = _bundled_binary()
    if b:
        return str(b)
    return shutil.which("cloudflared")


class CloudflaredBackend(TunnelBackend):
    name = "cloudflared"
    label = "Cloudflare Quick Tunnel (no account)"
    description = "Zero-setup default. Free, no signup. Random URL each run."

    def __init__(self, local_url: str, opts: Optional[dict] = None):
        super().__init__(local_url, opts)
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self, timeout: float = 30.0) -> str:
        binary = resolve_binary(self.opts.get("binary", "auto"))
        if not binary:
            self._set_state(TunnelState.ERROR, "cloudflared binary not found")
            raise RuntimeError(
                "cloudflared not found. Bundle it under packaging/bin/ or install it "
                "(https://github.com/cloudflare/cloudflared)."
            )

        self._stop.clear()
        self._set_state(TunnelState.STARTING)
        self._proc = subprocess.Popen(
            [
                binary, "tunnel", "--no-autoupdate",
                "--url", self.local_url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **no_window_kwargs(),
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.status()
            if st.public_url:
                self._set_state(TunnelState.RUNNING)
                return st.public_url
            if self._proc.poll() is not None:
                self._set_state(TunnelState.ERROR, "cloudflared exited early")
                raise RuntimeError("cloudflared exited before a URL was assigned")
            time.sleep(0.2)
        self._set_state(TunnelState.ERROR, "timed out waiting for URL")
        raise TimeoutError("cloudflared did not produce a URL in time")

    def _read_output(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            m = _URL_RE.search(line)
            if m:
                # A new URL line after we were already running means a reconnect.
                if self.status().state == TunnelState.RUNNING:
                    self._set_state(TunnelState.RECONNECTING)
                self._set_url(m.group(0))
                self._set_state(TunnelState.RUNNING)
        # process ended
        if not self._stop.is_set():
            self._set_state(TunnelState.ERROR, "cloudflared process ended")
            self._set_url(None)

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._set_url(None)
        self._set_state(TunnelState.STOPPED)
