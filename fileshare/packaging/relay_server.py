"""OPTIONAL self-hosted relay — run this on a public-IP VPS, not the host PC.

It accepts public HTTP on :PORT and forwards every request, over a WebSocket, to
a FileShare app that connected outward using the `selfhosted` backend. This is
the "no third parties in the path" upgrade; it is never required for normal use.

A home/NAT machine cannot run this usefully — the relay itself must be reachable
from the internet (public IP / open port on the VPS).

Run:
    pip install fastapi uvicorn websockets
    RELAY_TOKEN=yoursecret RELAY_PUBLIC_URL=https://share.example.com \\
        python relay_server.py --port 8080

Then on the host set in settings.toml:
    [tunnel]            backend = "selfhosted"
    [tunnel.selfhosted] relay_url = "wss://share.example.com/_relay/ws"
                        relay_token = "yoursecret"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
import uvicorn

app = FastAPI()

TOKEN = os.environ.get("RELAY_TOKEN", "")
PUBLIC_URL = os.environ.get("RELAY_PUBLIC_URL", "http://localhost:8080")

# Single active agent (one FileShare host per relay). Extendable to many.
_agent: WebSocket | None = None
_pending: dict[str, asyncio.Future] = {}


@app.websocket("/_relay/ws")
async def relay_ws(ws: WebSocket):
    global _agent
    if TOKEN:
        auth = ws.headers.get("authorization", "")
        if auth != f"Bearer {TOKEN}":
            await ws.close(code=4401)
            return
    await ws.accept()
    _agent = ws
    await ws.send_text(json.dumps({"public_url": PUBLIC_URL}))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            fut = _pending.pop(msg["id"], None)
            if fut and not fut.done():
                fut.set_result(msg)
    except WebSocketDisconnect:
        pass
    finally:
        if _agent is ws:
            _agent = None


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD"])
async def proxy(path: str, request: Request):
    if _agent is None:
        return Response("FileShare host not connected", status_code=503)
    rid = uuid.uuid4().hex
    body = await request.body()
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending[rid] = fut
    await _agent.send_text(json.dumps({
        "id": rid, "method": request.method,
        "path": "/" + path + (("?" + request.url.query) if request.url.query else ""),
        "headers": dict(request.headers), "body": body.hex() if body else "",
    }))
    try:
        msg = await asyncio.wait_for(fut, timeout=120)
    except asyncio.TimeoutError:
        _pending.pop(rid, None)
        return Response("Upstream timeout", status_code=504)
    headers = {k: v for k, v in msg["headers"].items()
               if k.lower() not in ("content-length", "transfer-encoding")}
    return Response(content=bytes.fromhex(msg["body"]), status_code=msg["status"],
                    headers=headers)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
