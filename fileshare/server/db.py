"""SQLite schema + thin data-access helpers.

One connection per process, guarded by check_same_thread=False because uvicorn
serves from a threadpool. Writes are short and serialized by SQLite's own lock;
WAL mode keeps readers unblocked.
"""
from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id            INTEGER PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,
    passcode_hash TEXT,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS folders (
    id           INTEGER PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,
    abs_path     TEXT NOT NULL,
    access_level TEXT NOT NULL CHECK (access_level IN ('PUBLIC','GROUP')),
    quota_bytes  INTEGER,
    watched      INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS folder_grants (
    folder_id  INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    group_id   INTEGER NOT NULL REFERENCES groups(id)  ON DELETE CASCADE,
    permission TEXT NOT NULL CHECK (permission IN ('none','download','upload')),
    PRIMARY KEY (folder_id, group_id)
);

CREATE TABLE IF NOT EXISTS share_links (
    id             INTEGER PRIMARY KEY,
    token          TEXT UNIQUE NOT NULL,
    folder_id      INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    group_id       INTEGER REFERENCES groups(id)  ON DELETE CASCADE,
    expires_at     REAL,
    max_downloads  INTEGER,
    download_count INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL,
    revoked        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS download_log (
    id        INTEGER PRIMARY KEY,
    ip        TEXT,
    link_id   INTEGER,
    folder_id INTEGER,
    path      TEXT,
    bytes     INTEGER,
    ts        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_download_log_ts ON download_log(ts);
"""


class DB:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- low level ---------------------------------------------------------
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def x(self, sql: str, params: Iterable[Any] = ()) -> int:
        cur = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cur.lastrowid

    # --- groups ------------------------------------------------------------
    def create_group(self, name: str, passcode_hash: Optional[str]) -> int:
        return self.x(
            "INSERT INTO groups(name, passcode_hash, created_at) VALUES (?,?,?)",
            (name, passcode_hash, time.time()),
        )

    def groups(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM groups ORDER BY name")

    def group(self, group_id: int) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM groups WHERE id=?", (group_id,))

    def delete_group(self, group_id: int) -> None:
        self.x("DELETE FROM groups WHERE id=?", (group_id,))

    # --- folders -----------------------------------------------------------
    def create_folder(
        self, name: str, abs_path: str, access_level: str,
        quota_bytes: Optional[int] = None, watched: bool = False,
    ) -> int:
        return self.x(
            "INSERT INTO folders(name, abs_path, access_level, quota_bytes, watched, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (name, abs_path, access_level, quota_bytes, int(watched), time.time()),
        )

    def folders(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM folders ORDER BY name")

    def folder(self, folder_id: int) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM folders WHERE id=?", (folder_id,))

    def folder_by_name(self, name: str) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM folders WHERE name=?", (name,))

    def delete_folder(self, folder_id: int) -> None:
        self.x("DELETE FROM folders WHERE id=?", (folder_id,))

    def watched_folders(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM folders WHERE watched=1")

    # --- grants ------------------------------------------------------------
    def set_grant(self, folder_id: int, group_id: int, permission: str) -> None:
        self.x(
            "INSERT INTO folder_grants(folder_id, group_id, permission) VALUES (?,?,?)"
            " ON CONFLICT(folder_id, group_id) DO UPDATE SET permission=excluded.permission",
            (folder_id, group_id, permission),
        )

    def grants_for_folder(self, folder_id: int) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM folder_grants WHERE folder_id=?", (folder_id,))

    def grant(self, folder_id: int, group_id: int) -> Optional[sqlite3.Row]:
        return self.one(
            "SELECT * FROM folder_grants WHERE folder_id=? AND group_id=?",
            (folder_id, group_id),
        )

    # --- share links -------------------------------------------------------
    def create_link(
        self, folder_id: Optional[int], group_id: Optional[int],
        expires_at: Optional[float] = None, max_downloads: Optional[int] = None,
    ) -> tuple[int, str]:
        token = secrets.token_urlsafe(24)
        lid = self.x(
            "INSERT INTO share_links(token, folder_id, group_id, expires_at, max_downloads, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (token, folder_id, group_id, expires_at, max_downloads, time.time()),
        )
        return lid, token

    def link_by_token(self, token: str) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM share_links WHERE token=?", (token,))

    def links(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM share_links ORDER BY created_at DESC")

    def revoke_link(self, link_id: int) -> None:
        self.x("UPDATE share_links SET revoked=1 WHERE id=?", (link_id,))

    def bump_link_download(self, link_id: int) -> None:
        self.x(
            "UPDATE share_links SET download_count=download_count+1 WHERE id=?",
            (link_id,),
        )

    # --- logging -----------------------------------------------------------
    def log_download(self, ip, link_id, folder_id, path, nbytes) -> None:
        self.x(
            "INSERT INTO download_log(ip, link_id, folder_id, path, bytes, ts)"
            " VALUES (?,?,?,?,?,?)",
            (ip, link_id, folder_id, path, nbytes, time.time()),
        )
