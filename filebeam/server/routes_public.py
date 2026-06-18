"""Public-facing routes — this is what the tunnel exposes to the internet.

Everything here is written defensively: path-traversal is centralized in
streaming.safe_join, every download/upload re-checks permissions against the DB,
unauthorized folders are never listed, and auth/download attempts are rate
limited. Identity is carried in a signed cookie (see session.py) and confers no
permission by itself.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth.groups import Identity, can, effective_permission, resolve_group_by_passcode, visible_folders
from ..auth.ratelimit import limiter
from .session import COOKIE_NAME
from .streaming import file_response, list_dir, safe_join

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "ui" / "templates"))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _human_size(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def build_public_router(state) -> APIRouter:
    router = APIRouter()
    db = state.db
    signer = state.signer
    limits = state.config.limits

    def identity_from(request: Request) -> Identity:
        raw = request.cookies.get(COOKIE_NAME)
        if not raw:
            return Identity()
        data = signer.unsign(raw)
        if not data:
            return Identity()
        link_id = data.get("link_id")
        # Re-validate the link on every request: revocation/expiry/caps apply live.
        link_folder = None
        if link_id:
            link = db.one("SELECT * FROM share_links WHERE id=?", (link_id,))
            if not link or link["revoked"]:
                return Identity(group_id=data.get("group_id"))
            if link["expires_at"] and time.time() > link["expires_at"]:
                return Identity(group_id=data.get("group_id"))
            link_folder = link["folder_id"]
        return Identity(
            group_id=data.get("group_id"),
            link_id=link_id,
            link_folder_id=link_folder,
        )

    def _set_identity(resp, identity: Identity) -> None:
        payload = {"group_id": identity.group_id, "link_id": identity.link_id}
        resp.set_cookie(
            COOKIE_NAME, signer.sign(payload),
            httponly=True, samesite="lax", max_age=7 * 24 * 3600,
        )

    # --- browse root -------------------------------------------------------
    @router.get("/", response_class=HTMLResponse)
    def index(request: Request):
        identity = identity_from(request)
        folders = visible_folders(db, identity)
        return TEMPLATES.TemplateResponse(
            request,
            "public_browse.html",
            {
                "folders": folders, "current": None,
                "entries": None, "identity": identity, "human_size": _human_size,
                "can_upload": False,
            },
        )

    # --- apply a tokened link ---------------------------------------------
    @router.get("/l/{token}")
    def apply_link(request: Request, token: str):
        if not limiter.allow("auth", _client_ip(request), limits["auth_attempts_per_min"]):
            raise HTTPException(status_code=429, detail="Too many attempts")
        link = db.link_by_token(token)
        if not link or link["revoked"]:
            raise HTTPException(status_code=404, detail="Invalid or revoked link")
        if link["expires_at"] and time.time() > link["expires_at"]:
            raise HTTPException(status_code=410, detail="Link expired")
        identity = Identity(group_id=link["group_id"], link_id=link["id"],
                            link_folder_id=link["folder_id"])
        if link["folder_id"]:
            folder = db.folder(link["folder_id"])
            target = f"/f/{folder['name']}" if folder else "/"
        else:
            target = "/"
        resp = RedirectResponse(target, status_code=303)
        _set_identity(resp, identity)
        return resp

    # --- unlock with a group passcode -------------------------------------
    @router.post("/unlock")
    def unlock(request: Request, passcode: str = Form(...)):
        if not limiter.allow("auth", _client_ip(request), limits["auth_attempts_per_min"]):
            raise HTTPException(status_code=429, detail="Too many attempts")
        group_id = resolve_group_by_passcode(db, passcode)
        if group_id is None:
            raise HTTPException(status_code=403, detail="Incorrect passcode")
        resp = RedirectResponse("/", status_code=303)
        _set_identity(resp, Identity(group_id=group_id))
        return resp

    @router.get("/logout")
    def logout():
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    # --- browse / download within a folder --------------------------------
    @router.get("/f/{folder_name}", response_class=HTMLResponse)
    @router.get("/f/{folder_name}/{subpath:path}")
    def browse(request: Request, folder_name: str, subpath: str = ""):
        identity = identity_from(request)
        folder = db.folder_by_name(folder_name)
        # Never reveal whether a folder exists if access is denied.
        if not folder or not can(db, folder, identity, "download"):
            raise HTTPException(status_code=404, detail="Not found")

        target = safe_join(folder["abs_path"], *(_split(subpath)))
        if target.is_dir():
            if not limiter.allow("download", _client_ip(request), limits["downloads_per_min"]):
                raise HTTPException(status_code=429, detail="Slow down")
            entries = list_dir(target)
            return TEMPLATES.TemplateResponse(
                request,
                "public_browse.html",
                {
                    "folders": None, "current": folder,
                    "subpath": subpath, "entries": entries, "identity": identity,
                    "human_size": _human_size,
                    "can_upload": can(db, folder, identity, "upload"),
                },
            )
        if target.is_file():
            if not limiter.allow("download", _client_ip(request), limits["downloads_per_min"]):
                raise HTTPException(status_code=429, detail="Slow down")
            _enforce_link_caps(db, identity)
            resp = file_response(request, target)
            if identity.link_id:
                db.bump_link_download(identity.link_id)
            db.log_download(_client_ip(request), identity.link_id, folder["id"],
                           str(target), target.stat().st_size)
            return resp
        raise HTTPException(status_code=404, detail="Not found")

    # --- upload into a folder ---------------------------------------------
    @router.post("/f/{folder_name}/upload")
    async def upload(request: Request, folder_name: str, file: UploadFile):
        identity = identity_from(request)
        folder = db.folder_by_name(folder_name)
        if not folder or not can(db, folder, identity, "upload"):
            raise HTTPException(status_code=404, detail="Not found")
        dest = safe_join(folder["abs_path"], _safe_name(file.filename or "upload.bin"))
        max_mb = limits.get("max_upload_mb", 0)
        written = 0
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 512)
                if not chunk:
                    break
                written += len(chunk)
                if max_mb and written > max_mb * 1024 * 1024:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="File too large")
                out.write(chunk)
        return RedirectResponse(f"/f/{folder_name}", status_code=303)

    return router


def _split(subpath: str) -> list[str]:
    return [p for p in subpath.split("/") if p not in ("", ".", "..")]


def _safe_name(name: str) -> str:
    import os

    return os.path.basename(name).replace("\\", "_").replace("/", "_") or "upload.bin"


def _enforce_link_caps(db, identity: Identity) -> None:
    if not identity.link_id:
        return
    link = db.one("SELECT * FROM share_links WHERE id=?", (identity.link_id,))
    if not link:
        return
    if link["max_downloads"] is not None and link["download_count"] >= link["max_downloads"]:
        raise HTTPException(status_code=410, detail="Download limit reached for this link")
