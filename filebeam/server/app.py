"""App factories + a runtime that serves the admin and public apps together.

Two separate FastAPI apps on two loopback ports:
  * admin app  (127.0.0.1)         — local control panel, never tunnelled
  * public app (127.0.0.1)         — the tunnel points here; faces the internet

Keeping them as distinct apps guarantees admin routes can never be reached
through the public tunnel.
"""
from __future__ import annotations

import threading

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes_admin import build_admin_router
from .routes_public import build_public_router
from .state import AppState

_STATIC = Path(__file__).resolve().parent.parent / "ui" / "static"


def build_admin_app(state: AppState) -> FastAPI:
    app = FastAPI(title="FileBeam Admin", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
    app.include_router(build_admin_router(state))
    return app


def build_public_app(state: AppState) -> FastAPI:
    app = FastAPI(title="FileBeam", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    app.include_router(build_public_router(state))
    return app


class _Server:
    """A uvicorn server running in its own daemon thread."""

    def __init__(self, app, host, port):
        # log_config=None skips uvicorn's dictConfig (its colourized formatter
        # touches sys.stdout.isatty(), which breaks in windowed/no-console builds).
        cfg = uvicorn.Config(app, host=host, port=port, log_level="warning",
                             access_log=False, log_config=None)
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.should_exit = True


class Runtime:
    """Owns both HTTP servers and the shared state for the lifetime of the app."""

    def __init__(self, state: AppState | None = None):
        self.state = state or AppState()
        self.admin_server = _Server(
            build_admin_app(self.state),
            self.state.config.admin_host, self.state.config.admin_port,
        )
        self.public_server = _Server(
            build_public_app(self.state),
            self.state.config.share_bind_host, self.state.config.share_port,
        )

    @property
    def admin_url(self) -> str:
        return f"http://{self.state.config.admin_host}:{self.state.config.admin_port}"

    def start(self, start_admin_web: bool = True) -> None:
        """Start the public server (always) and, optionally, the legacy web admin.

        The native GUI talks to the state directly, so GUI mode leaves the web
        admin off. Headless mode can turn it back on with start_admin_web=True.
        """
        self.public_server.start()
        if start_admin_web:
            self.admin_server.start()
        self.state.start_watcher()

    def stop(self) -> None:
        self.state.tunnel.stop()
        self.state.stop_watcher()
        self.admin_server.stop()
        self.public_server.stop()
