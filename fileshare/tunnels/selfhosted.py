"""ADVANCED / OPTIONAL backend: your own relay on a public-IP server.

Zero third parties in the path. The app makes an OUTBOUND WebSocket connection
to a relay you run on a VPS with a public IP (a home/NAT machine cannot be the
endpoint — it isn't reachable from the internet). The relay accepts public HTTP
and forwards each request to this app over that WebSocket.

This is NOT the default and is never required. See README "optional: run your
own relay" and packaging/relay_server.py for the server side.

Requires the optional `websockets` and `httpx` packages:
    pip install -r requirements-selfhosted.txt
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional

from .base import TunnelBackend, TunnelState


class SelfHostedRelayBackend(TunnelBackend):
    name = "selfhosted"
    label = "Self-hosted relay (advanced)"
    description = "Your own VPS relay. No third parties. Stable URL you control."

    def __init__(self, local_url: str, opts: Optional[dict] = None):
        super().__init__(local_url, opts)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_evt: Optional[asyncio.Event] = None

    def start(self, timeout: float = 30.0) -> str:
        relay_url = self.opts.get("relay_url", "")
        token = self.opts.get("relay_token", "")
        if not relay_url:
            self._set_state(TunnelState.ERROR, "relay_url not configured")
            raise RuntimeError("selfhosted backend needs tunnel.selfhosted.relay_url")

        self._set_state(TunnelState.STARTING)
        ready = threading.Event()

        def run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._stop_evt = asyncio.Event()
            try:
                self._loop.run_until_complete(self._agent(relay_url, token, ready))
            except Exception as e:  # noqa: BLE001
                self._set_state(TunnelState.ERROR, str(e))
                ready.set()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        if not ready.wait(timeout):
            self._set_state(TunnelState.ERROR, "timed out connecting to relay")
            raise TimeoutError("relay did not assign a URL in time")
        st = self.status()
        if not st.public_url:
            raise RuntimeError(st.error or "relay connection failed")
        return st.public_url

    async def _agent(self, relay_url: str, token: str, ready: threading.Event) -> None:
        import httpx
        import websockets

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with websockets.connect(relay_url, additional_headers=headers,
                                      max_size=None, ping_interval=20) as ws:
            # First frame from relay tells us our public URL.
            hello = json.loads(await ws.recv())
            self._set_url(hello["public_url"])
            self._set_state(TunnelState.RUNNING)
            ready.set()

            async with httpx.AsyncClient(base_url=self.local_url, timeout=None) as client:
                stop_task = asyncio.ensure_future(self._stop_evt.wait())
                while True:
                    recv_task = asyncio.ensure_future(ws.recv())
                    done, _ = await asyncio.wait(
                        {recv_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if stop_task in done:
                        recv_task.cancel()
                        await ws.close()
                        return
                    msg = json.loads(recv_task.result())
                    asyncio.ensure_future(self._handle(ws, client, msg))

    async def _handle(self, ws, client, req) -> None:
        """Proxy one HTTP request described by the relay back to local server."""
        rid = req["id"]
        try:
            resp = await client.request(
                req["method"], req["path"],
                headers=req.get("headers", {}),
                content=bytes.fromhex(req["body"]) if req.get("body") else None,
            )
            body = await resp.aread()
            await ws.send(json.dumps({
                "id": rid, "status": resp.status_code,
                "headers": dict(resp.headers), "body": body.hex(),
            }))
        except Exception as e:  # noqa: BLE001
            await ws.send(json.dumps({"id": rid, "status": 502, "headers": {},
                                      "body": str(e).encode().hex()}))

    def stop(self) -> None:
        if self._loop and self._stop_evt:
            self._loop.call_soon_threadsafe(self._stop_evt.set)
        self._set_url(None)
        self._set_state(TunnelState.STOPPED)
