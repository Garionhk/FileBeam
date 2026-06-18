"""Optional no-account backend: localhost.run over SSH.

`ssh -R 80:127.0.0.1:PORT nokey@localhost.run` opens an outbound SSH reverse
tunnel and prints a random https://<id>.lhr.life URL. No account, no bundled
binary (uses the system ssh client present on macOS and Windows 10+).

We forward to 127.0.0.1 (not "localhost") on purpose: on Windows "localhost"
resolves to IPv6 ::1 first, but the file server binds IPv4, so a localhost
forward would hit a dead address. The explicit IPv4 literal avoids that.

This file doubles as the ~30-line template for adding a new backend.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from .base import TunnelBackend, TunnelState, no_window_kwargs

_URL_RE = re.compile(r"https://\S+\.lhr\.life")


class LocalhostRunBackend(TunnelBackend):
    name = "localhost_run"
    label = "localhost.run (SSH, no account)"
    description = "No bundled binary; uses system ssh. Random URL each run."

    def __init__(self, local_url: str, opts: Optional[dict] = None):
        super().__init__(local_url, opts)
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._tail: list[str] = []  # recent output, for error messages

    def start(self, timeout: float = 30.0) -> str:
        port = urlparse(self.local_url).port or 80
        host = self.opts.get("ssh_host", "localhost.run")
        self._stop.clear()
        self._tail = []
        self._set_state(TunnelState.STARTING)
        try:
            self._proc = subprocess.Popen(
                [
                    "ssh", "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ServerAliveInterval=30",
                    # IPv4 literal (not "localhost") — see module docstring.
                    "-R", f"80:127.0.0.1:{port}", f"nokey@{host}",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                **no_window_kwargs(),
            )
        except FileNotFoundError:
            msg = "ssh not found. Install the OpenSSH client (Windows: Settings > Apps > Optional Features)."
            self._set_state(TunnelState.ERROR, msg)
            raise RuntimeError(msg)
        threading.Thread(target=self._read_output, daemon=True).start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.status().public_url:
                self._set_state(TunnelState.RUNNING)
                return self.status().public_url
            if self._proc.poll() is not None:
                detail = " ".join(self._tail[-3:]).strip() or "ssh exited early"
                self._set_state(TunnelState.ERROR, detail)
                raise RuntimeError(f"ssh tunnel exited before a URL was assigned: {detail}")
            time.sleep(0.2)
        self._set_state(TunnelState.ERROR, "timed out waiting for URL")
        raise TimeoutError("localhost.run did not produce a URL in time")

    def _read_output(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            self._tail.append(line.strip())
            self._tail = self._tail[-10:]
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
