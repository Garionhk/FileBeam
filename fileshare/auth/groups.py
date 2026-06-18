"""Access resolution: which folders an identity may see and what it may do.

An *identity* is simply an optional group_id. Anonymous visitors (no group)
still get access to PUBLIC folders. A group is obtained either by following a
tokened link bound to a group, or by entering a group passcode.

Permission levels are ordered:  none < download < upload.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .tokens import verify_passcode

PERM_ORDER = {"none": 0, "download": 1, "upload": 2}


@dataclass
class Identity:
    group_id: Optional[int] = None          # None => anonymous public visitor
    link_id: Optional[int] = None           # share_link id, if arrived via link
    link_folder_id: Optional[int] = None    # folder a tokened link unlocks directly


def resolve_group_by_passcode(db, passcode: str) -> Optional[int]:
    """Return the id of the first group whose passcode matches, else None."""
    for g in db.groups():
        if g["passcode_hash"] and verify_passcode(passcode, g["passcode_hash"]):
            return g["id"]
    return None


def _grant_perm(db, folder_id: int, group_id: Optional[int]) -> str:
    if group_id is None:
        return "none"
    row = db.grant(folder_id, group_id)
    return row["permission"] if row else "none"


def effective_permission(db, folder, identity: Identity) -> str:
    """Highest permission the identity has on this folder.

    PUBLIC folders grant 'download' to everyone; a matching group grant can
    raise that to 'upload'. GROUP folders grant only what the group's grant says.
    """
    grant = _grant_perm(db, folder["id"], identity.group_id)
    # A tokened link pointed straight at this folder confers at least download.
    if identity.link_folder_id == folder["id"]:
        grant = grant if PERM_ORDER[grant] > PERM_ORDER["download"] else "download"
    if folder["access_level"] == "PUBLIC":
        base = "download"
        return grant if PERM_ORDER[grant] > PERM_ORDER[base] else base
    return grant


def can(db, folder, identity: Identity, action: str) -> bool:
    """action is 'download' or 'upload'."""
    return PERM_ORDER[effective_permission(db, folder, identity)] >= PERM_ORDER[action]


def visible_folders(db, identity: Identity) -> list:
    """Folders the identity is allowed to at least see (download or better).

    Folders with no access are omitted entirely — never listed, so their
    existence is not leaked.
    """
    out = []
    for f in db.folders():
        if PERM_ORDER[effective_permission(db, f, identity)] >= PERM_ORDER["download"]:
            out.append(f)
    return out
