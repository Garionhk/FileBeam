"""Safe file resolution + streamed responses with HTTP range support.

Path-traversal protection is centralized in ``safe_join``: every public path
operation must go through it. Large files are streamed in chunks; we never read
a whole file into memory, and we honour a single Range header for resumable
downloads.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

CHUNK = 1024 * 256  # 256 KiB
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def safe_join(base: str | Path, *parts: str) -> Path:
    """Join user-supplied parts under base, rejecting any escape.

    Resolves symlinks and verifies the result stays within base. Raises 404 on
    any traversal attempt so we never confirm whether a sibling path exists.
    """
    base_resolved = Path(base).resolve()
    candidate = base_resolved.joinpath(*parts)
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="Not found")
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise HTTPException(status_code=404, detail="Not found")
    return resolved


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    """Yield bytes [start, end] inclusive."""
    remaining = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            data = f.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _guess_type(path: Path) -> str:
    import mimetypes

    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def file_response(
    request: Request, path: Path, download_name: Optional[str] = None
) -> StreamingResponse:
    """Stream a file, honouring a Range header for resumable downloads."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    start, end = 0, file_size - 1
    status_code = 200

    if range_header:
        m = _RANGE_RE.match(range_header.strip())
        if m:
            g0, g1 = m.group(1), m.group(2)
            if g0 == "" and g1 != "":          # suffix range: last N bytes
                length = min(int(g1), file_size)
                start = file_size - length
                end = file_size - 1
            else:
                start = int(g0)
                end = int(g1) if g1 else file_size - 1
            if start > end or start >= file_size:
                raise HTTPException(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}"},
                    detail="Range not satisfiable",
                )
            end = min(end, file_size - 1)
            status_code = 206

    content_length = end - start + 1
    name = download_name or path.name
    headers = {
        "Content-Length": str(content_length),
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{_sanitize_filename(name)}"',
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=status_code,
        media_type=_guess_type(path),
        headers=headers,
    )


def _sanitize_filename(name: str) -> str:
    # Strip characters that could break the header or smuggle a path.
    name = os.path.basename(name)
    return name.replace('"', "").replace("\r", "").replace("\n", "") or "download"


def list_dir(path: Path) -> list[dict]:
    """Return a sorted listing (dirs first) of a directory's immediate children."""
    entries = []
    for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": stat.st_size if child.is_file() else None,
            }
        )
    return entries
