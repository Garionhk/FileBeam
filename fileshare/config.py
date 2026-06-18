"""Settings loading + app data paths.

Settings live in a TOML file. We resolve a per-user data directory for the
SQLite DB and any runtime state so a packaged (read-only) app still works.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


APP_NAME = "FileShare"


def _user_data_dir() -> Path:
    """Cross-platform per-user data directory."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundle_dir() -> Path:
    """Directory containing bundled resources (works under PyInstaller)."""
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _default_settings_path() -> Path:
    # Prefer a user-writable copy; fall back to the bundled template.
    user_copy = _user_data_dir() / "settings.toml"
    if user_copy.exists():
        return user_copy
    bundled = bundle_dir() / "settings.toml"
    if bundled.exists():
        return bundled
    return user_copy


DEFAULTS: dict[str, Any] = {
    "server": {
        "admin_host": "127.0.0.1",
        "admin_port": 8765,
        "share_host": "127.0.0.1",
        "share_port": 8766,
        "admin_passcode": "",
    },
    "tunnel": {
        "backend": "cloudflared",
        "cloudflared": {"binary": "auto"},
        "localhost_run": {"ssh_host": "localhost.run"},
        "selfhosted": {"relay_url": "", "relay_token": ""},
    },
    "limits": {
        "auth_attempts_per_min": 10,
        "downloads_per_min": 120,
        "max_upload_mb": 0,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or _default_settings_path()
        self.data = dict(DEFAULTS)
        if self.path.exists():
            with open(self.path, "rb") as f:
                self.data = _deep_merge(DEFAULTS, tomllib.load(f))
        self.data_dir = _user_data_dir()
        self.db_path = self.data_dir / "fileshare.db"
        self._prefs_path = self.data_dir / "ui_prefs.json"

    # --- UI preferences (persisted separately so we never rewrite TOML) -----
    def _load_prefs(self) -> dict:
        import json

        path = getattr(self, "_prefs_path", None)
        if not path:
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    @property
    def ui_language(self) -> str:
        return self._load_prefs().get("language", "en")

    def set_ui_language(self, lang: str) -> None:
        import json

        prefs = self._load_prefs()
        prefs["language"] = lang
        try:
            self._prefs_path.write_text(json.dumps(prefs))
        except Exception:
            pass

    # Convenience accessors -------------------------------------------------
    @property
    def admin_host(self) -> str:
        return self.data["server"]["admin_host"]

    @property
    def admin_port(self) -> int:
        return int(self.data["server"]["admin_port"])

    @property
    def share_host(self) -> str:
        return self.data["server"]["share_host"]

    @property
    def share_bind_host(self) -> str:
        """Address the public file server actually listens on.

        For LAN mode the browser hits us directly on the LAN IP, so we must bind
        to all interfaces; an explicit non-loopback share_host is always honored.
        Tunnel modes keep loopback-only binding (the tunnel connects locally),
        so the default needs no firewall change.
        """
        h = self.data["server"]["share_host"]
        if self.backend_name == "lan" and h in ("127.0.0.1", "localhost"):
            return "0.0.0.0"
        return h

    @property
    def share_port(self) -> int:
        return int(self.data["server"]["share_port"])

    @property
    def admin_passcode(self) -> str:
        return self.data["server"].get("admin_passcode", "")

    @property
    def backend_name(self) -> str:
        return self.data["tunnel"]["backend"]

    def backend_opts(self, name: str) -> dict[str, Any]:
        return self.data["tunnel"].get(name, {})

    @property
    def limits(self) -> dict[str, Any]:
        return self.data["limits"]


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
