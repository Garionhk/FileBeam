"""Optional no-account backend: localhost.run over SSH.

`ssh -R 80:localhost:PORT nokey@localhost.run` opens an outbound SSH reverse
tunnel and prints a random https://<id>.lhr.life URL. No account, no bundled
binary (uses the system ssh client present on macOS and Windows 10+).

This file doubles as the ~30-line template for adding a new backend.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from .base import TunnelBackend, TunnelState

_URL_RE = re.compile(r"https://\S+\.lhr\.life")


class LocalhostRunBackend(TunnelBackend):
    name = "localhost_run"
    label = "localhost.run (SSH, no account)"
    description = "No bundled binary; uses system ssh. Random URL each run."

    def __init__(self, local_url: str, opts: Optional[dict] = None):
        super().__init__(local_url, opts)
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()

    def start(self, timeout: float = 30.0) -> str:
        port = urlparse(self.local_url).port or 80
        host = self.opts.get("ssh_host", "localhost.run")
        self._stop.clear()
        self._set_state(TunnelState.STARTING)
        self._proc = subprocess.Popen(
            [
                "ssh", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ServerAliveInterval=30",
                "-R", f"80:localhost:{port}", f"nokey@{host}",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        threading.Thread(target=self._read_output, daemon=True).start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.status().public_url:
                self._set_state(TunnelState.RUNNING)
                return self.status().public_url
            if self._proc.poll() is not None:
                self._set_state(TunnelState.ERROR, "ssh exited early")
                raise RuntimeError("ssh tunnel exited before a URL was assigned")
            time.sleep(0.2)
        self._set_state(TunnelState.ERROR, "timed out waiting for URL")
        raise TimeoutError("localhost.run did not produce a URL in time")

    def _read_output(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            m = _URL_RE.search(line)
            if m:
                self._set_url(m.group(0))
                self._set_state(TunnelState.RUNNING)

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
