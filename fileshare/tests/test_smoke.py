"""Smoke tests covering the security-critical paths and access model.

These use FastAPI's TestClient against the public + admin apps with a temp DB,
so no real tunnel or network is involved.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from fileshare.auth.tokens import hash_passcode, verify_passcode
from fileshare.config import Config
from fileshare.server.app import build_admin_app, build_public_app
from fileshare.server.state import AppState
from fileshare.server.streaming import safe_join
from fastapi import HTTPException


@pytest.fixture()
def state(tmp_path, monkeypatch):
    # Point config at a temp data dir / settings.
    cfg = Config.__new__(Config)
    cfg.path = tmp_path / "settings.toml"
    from fileshare.config import DEFAULTS
    cfg.data = dict(DEFAULTS)
    cfg.data_dir = tmp_path
    cfg.db_path = tmp_path / "test.db"
    st = AppState(config=cfg)
    return st


@pytest.fixture()
def public(state):
    return TestClient(build_public_app(state))


@pytest.fixture()
def admin(state):
    return TestClient(build_admin_app(state))


# --- path traversal -------------------------------------------------------
def test_safe_join_blocks_traversal(tmp_path):
    base = tmp_path / "share"
    base.mkdir()
    (base / "ok.txt").write_text("hi")
    assert safe_join(base, "ok.txt").name == "ok.txt"
    with pytest.raises(HTTPException):
        safe_join(base, "..", "secret")
    with pytest.raises(HTTPException):
        safe_join(base, "../../etc/passwd")


# --- passcode hashing -----------------------------------------------------
def test_passcode_roundtrip():
    h = hash_passcode("hunter2")
    assert h and verify_passcode("hunter2", h)
    assert not verify_passcode("wrong", h)
    assert not verify_passcode("anything", "")


# --- PUBLIC folder: anyone downloads, no passcode -------------------------
def test_public_folder_download(state, public, tmp_path):
    d = tmp_path / "pub"
    d.mkdir()
    (d / "hello.txt").write_text("public data")
    state.db.create_folder("pub", str(d), "PUBLIC")
    # Listed on the index without any auth.
    r = public.get("/")
    assert "pub" in r.text
    # Direct download works tokenless.
    r = public.get("/f/pub/hello.txt")
    assert r.status_code == 200 and r.content == b"public data"


# --- GROUP folder hidden + gated -----------------------------------------
def test_group_folder_hidden_until_unlocked(state, public, tmp_path):
    d = tmp_path / "secret"
    d.mkdir()
    (d / "plan.txt").write_text("top secret")
    fid = state.db.create_folder("secret", str(d), "GROUP")
    gid = state.db.create_group("alpha", hash_passcode("letmein"))
    state.db.set_grant(fid, gid, "download")

    # Anonymous: not listed, and a direct hit 404s (no existence leak).
    assert "secret" not in public.get("/").text
    assert public.get("/f/secret/plan.txt").status_code == 404

    # Unlock with passcode, then it works.
    r = public.post("/unlock", data={"passcode": "letmein"}, follow_redirects=False)
    assert r.status_code == 303
    assert "secret" in public.get("/").text
    r = public.get("/f/secret/plan.txt")
    assert r.status_code == 200 and r.content == b"top secret"


# --- tokened link grants folder access -----------------------------------
def test_token_link_grants_access(state, public, tmp_path):
    d = tmp_path / "drop"
    d.mkdir()
    (d / "f.bin").write_bytes(b"x" * 10)
    fid = state.db.create_folder("drop", str(d), "GROUP")
    _, token = state.db.create_link(fid, None)

    assert public.get("/f/drop/f.bin").status_code == 404  # no link yet
    r = public.get(f"/l/{token}", follow_redirects=False)
    assert r.status_code == 303
    assert public.get("/f/drop/f.bin").status_code == 200


# --- range requests / resumable downloads --------------------------------
def test_range_request(state, public, tmp_path):
    d = tmp_path / "pub"
    d.mkdir()
    (d / "big.bin").write_bytes(bytes(range(256)) * 8)  # 2048 bytes
    state.db.create_folder("pub", str(d), "PUBLIC")
    r = public.get("/f/pub/big.bin", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.headers["Content-Range"] == "bytes 10-19/2048"
    assert len(r.content) == 10
    assert r.headers["Accept-Ranges"] == "bytes"


# --- upload requires upload permission ------------------------------------
def test_upload_permission_enforced(state, public, tmp_path):
    d = tmp_path / "up"
    d.mkdir()
    fid = state.db.create_folder("up", str(d), "PUBLIC")  # public => download only
    # Public visitor can't upload (only download by default).
    r = public.post("/f/up/upload", files={"file": ("a.txt", b"data")})
    assert r.status_code == 404
    # Grant upload to a group and unlock.
    gid = state.db.create_group("ed", hash_passcode("pw"))
    state.db.set_grant(fid, gid, "upload")
    public.post("/unlock", data={"passcode": "pw"})
    r = public.post("/f/up/upload", files={"file": ("a.txt", b"data")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert (d / "a.txt").read_bytes() == b"data"


# --- admin dashboard renders ---------------------------------------------
def test_admin_dashboard(state, admin):
    r = admin.get("/")
    assert r.status_code == 200
    assert "FileShare" in r.text
    # status endpoint reports stopped tunnel
    s = admin.get("/status").json()
    assert s["state"] == "STOPPED"


# --- i18n: english + traditional chinese ----------------------------------
def test_i18n_languages():
    from fileshare.ui.i18n import LANGUAGES, I18n

    assert set(LANGUAGES) == {"en", "zh-Hant"}
    i = I18n("en")
    assert i.t("start_sharing") == "▶  Start sharing"
    i.set_language("zh-Hant")
    assert i.t("add_folder") == "新增資料夾"
    # unknown key falls back to the key itself; missing translation falls back to EN
    assert i.t("nonexistent_key") == "nonexistent_key"
    assert i.code_for_name("繁體中文") == "zh-Hant"
    assert i.code_for_name("English") == "en"


# --- backend registry is pluggable ----------------------------------------
def test_backend_registry():
    from fileshare.tunnels.registry import BACKENDS, DEFAULT_BACKEND, make_backend
    assert DEFAULT_BACKEND == "cloudflared"
    assert set(["cloudflared", "localhost_run", "selfhosted", "lan"]) <= set(BACKENDS)
    b = make_backend("lan", "http://127.0.0.1:8766")
    assert b.name == "lan"
