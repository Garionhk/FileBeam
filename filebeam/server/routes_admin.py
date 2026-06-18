"""Local admin UI routes. Bound to 127.0.0.1 only — never exposed by the tunnel.

Provides folder/group/link management, drag-and-drop upload, watched-folder
toggles, the tunnel backend selector, and a status endpoint the page polls so it
can show the live public URL and warn the moment it changes.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth.tokens import hash_passcode, verify_passcode
from ..tunnels.registry import backend_choices
from .streaming import safe_join

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "ui" / "templates"))
ADMIN_COOKIE = "fs_admin"


def build_admin_router(state) -> APIRouter:
    router = APIRouter()
    db = state.db
    tunnel = state.tunnel
    config = state.config

    def _authed(request: Request) -> bool:
        if not config.admin_passcode:
            return True
        return request.cookies.get(ADMIN_COOKIE) == _admin_cookie_value(state)

    def _require(request: Request):
        if not _authed(request):
            raise HTTPException(status_code=401, detail="admin locked")

    # --- auth gate (only when an admin passcode is configured) ------------
    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return TEMPLATES.TemplateResponse(request, "admin_login.html", {})

    @router.post("/login")
    def login(request: Request, passcode: str = Form(...)):
        if config.admin_passcode and passcode == config.admin_passcode:
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(ADMIN_COOKIE, _admin_cookie_value(state),
                            httponly=True, samesite="strict")
            return resp
        raise HTTPException(status_code=403, detail="wrong passcode")

    # --- dashboard ---------------------------------------------------------
    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        if not _authed(request):
            return RedirectResponse("/login", status_code=303)
        return TEMPLATES.TemplateResponse(
            request,
            "admin.html",
            {
                "folders": [dict(f) for f in db.folders()],
                "groups": [dict(g) for g in db.groups()],
                "links": [dict(l) for l in db.links()],
                "grants": _grants_map(db),
                "backends": backend_choices(),
                "backend_name": tunnel.backend_name or config.backend_name,
                "now": time.time(),
            },
        )

    # --- status (polled by the page) --------------------------------------
    @router.get("/status")
    def status(request: Request):
        _require(request)
        st = tunnel.status()
        return JSONResponse({
            "state": st.state.value,
            "public_url": tunnel.public_url,
            "previous_url": tunnel.previous_url,
            "url_changed_at": tunnel.url_changed_at,
            "error": st.error,
            "backend": tunnel.backend_name,
        })

    @router.post("/url/ack")
    def ack_url(request: Request):
        _require(request)
        tunnel.ack_url_change()
        return JSONResponse({"ok": True})

    # --- tunnel control ----------------------------------------------------
    @router.post("/tunnel/start")
    def tunnel_start(request: Request, backend: str = Form(...)):
        _require(request)
        try:
            url = tunnel.start(backend)
            return JSONResponse({"ok": True, "public_url": url})
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @router.post("/tunnel/stop")
    def tunnel_stop(request: Request):
        _require(request)
        tunnel.stop()
        return JSONResponse({"ok": True})

    # --- folders -----------------------------------------------------------
    @router.post("/folders")
    def add_folder(
        request: Request,
        name: str = Form(...), abs_path: str = Form(...),
        access_level: str = Form("PUBLIC"), watched: Optional[str] = Form(None),
        quota_mb: str = Form(""),
    ):
        _require(request)
        p = Path(abs_path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        quota = int(float(quota_mb) * 1024 * 1024) if quota_mb.strip() else None
        db.create_folder(name.strip(), str(p.resolve()),
                         "GROUP" if access_level == "GROUP" else "PUBLIC",
                         quota, watched is not None)
        state.start_watcher()
        return RedirectResponse("/", status_code=303)

    @router.post("/folders/{folder_id}/delete")
    def del_folder(request: Request, folder_id: int):
        _require(request)
        db.delete_folder(folder_id)
        state.start_watcher()
        return RedirectResponse("/", status_code=303)

    # --- groups ------------------------------------------------------------
    @router.post("/groups")
    def add_group(request: Request, name: str = Form(...), passcode: str = Form("")):
        _require(request)
        db.create_group(name.strip(), hash_passcode(passcode) if passcode else None)
        return RedirectResponse("/", status_code=303)

    @router.post("/groups/{group_id}/delete")
    def del_group(request: Request, group_id: int):
        _require(request)
        db.delete_group(group_id)
        return RedirectResponse("/", status_code=303)

    # --- grants ------------------------------------------------------------
    @router.post("/grants")
    def set_grant(request: Request, folder_id: int = Form(...),
                  group_id: int = Form(...), permission: str = Form(...)):
        _require(request)
        if permission not in ("none", "download", "upload"):
            raise HTTPException(status_code=400, detail="bad permission")
        db.set_grant(folder_id, group_id, permission)
        return RedirectResponse("/", status_code=303)

    # --- share links -------------------------------------------------------
    @router.post("/links")
    def add_link(request: Request, folder_id: str = Form(""), group_id: str = Form(""),
                 expires_hours: str = Form(""), max_downloads: str = Form("")):
        _require(request)
        fid = int(folder_id) if folder_id else None
        gid = int(group_id) if group_id else None
        exp = time.time() + float(expires_hours) * 3600 if expires_hours.strip() else None
        cap = int(max_downloads) if max_downloads.strip() else None
        db.create_link(fid, gid, exp, cap)
        return RedirectResponse("/", status_code=303)

    @router.post("/links/{link_id}/revoke")
    def revoke_link(request: Request, link_id: int):
        _require(request)
        db.revoke_link(link_id)
        return RedirectResponse("/", status_code=303)

    # --- drag-drop upload into a folder -----------------------------------
    @router.post("/folders/{folder_id}/upload")
    async def upload(request: Request, folder_id: int, file: UploadFile):
        _require(request)
        folder = db.folder(folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="no such folder")
        import os

        name = os.path.basename(file.filename or "upload.bin") or "upload.bin"
        dest = safe_join(folder["abs_path"], name)
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 512)
                if not chunk:
                    break
                out.write(chunk)
        return JSONResponse({"ok": True, "name": name})

    return router


def _grants_map(db) -> dict:
    """{folder_id: {group_id: permission}} for rendering the grant grid."""
    out: dict[int, dict[int, str]] = {}
    for f in db.folders():
        out[f["id"]] = {}
        for g in db.grants_for_folder(f["id"]):
            out[f["id"]][g["group_id"]] = g["permission"]
    return out


def _admin_cookie_value(state) -> str:
    # Deterministic per-secret token; not the passcode itself.
    return state.signer.sign({"admin": True}).split(".")[-1]
