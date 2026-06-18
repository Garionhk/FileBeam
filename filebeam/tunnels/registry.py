"""Backend registry — the single place that knows all TunnelBackend names.

Add a new backend in ~30 lines:
    1. Write a subclass of TunnelBackend (see localhost_run.py as a template).
    2. Import it here and add one entry to BACKENDS.
That's it — the settings file and the UI dropdown pick it up automatically.
"""
from __future__ import annotations

from .base import TunnelBackend
from .cloudflared import CloudflaredBackend
from .lan import LanOnlyBackend
from .localhost_run import LocalhostRunBackend
from .selfhosted import SelfHostedRelayBackend

BACKENDS: dict[str, type[TunnelBackend]] = {
    CloudflaredBackend.name: CloudflaredBackend,
    LocalhostRunBackend.name: LocalhostRunBackend,
    SelfHostedRelayBackend.name: SelfHostedRelayBackend,
    LanOnlyBackend.name: LanOnlyBackend,
}

DEFAULT_BACKEND = CloudflaredBackend.name


def make_backend(name: str, local_url: str, opts: dict | None = None) -> TunnelBackend:
    cls = BACKENDS.get(name)
    if cls is None:
        raise KeyError(f"Unknown tunnel backend: {name!r}. Known: {list(BACKENDS)}")
    return cls(local_url, opts)


def backend_choices() -> list[dict]:
    """Metadata for the UI dropdown."""
    return [
        {"name": c.name, "label": c.label, "description": c.description}
        for c in BACKENDS.values()
    ]
