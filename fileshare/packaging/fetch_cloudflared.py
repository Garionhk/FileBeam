#!/usr/bin/env python3
"""Download the cloudflared binary into packaging/bin/ for bundling.

Run before PyInstaller so the packaged app ships the default tunnel and first
run is truly zero-setup. Picks the right artifact for the current OS/arch, or
pass --os / --arch to cross-fetch.
"""
from __future__ import annotations

import argparse
import platform
import stat
import sys
import urllib.request
from pathlib import Path

BASE = "https://github.com/cloudflare/cloudflared/releases/latest/download"

# Map (os, arch) -> release asset name.
ASSETS = {
    ("darwin", "amd64"): "cloudflared-darwin-amd64.tgz",
    ("darwin", "arm64"): "cloudflared-darwin-arm64.tgz",
    ("windows", "amd64"): "cloudflared-windows-amd64.exe",
    ("windows", "386"): "cloudflared-windows-386.exe",
    ("linux", "amd64"): "cloudflared-linux-amd64",
    ("linux", "arm64"): "cloudflared-linux-arm64",
}

OUT_DIR = Path(__file__).resolve().parent / "bin"


def _download(url: str, dest: Path) -> None:
    """Download with verified TLS; fall back to certifi, then to an unverified
    context (some python.org builds lack a system cert bundle)."""
    import ssl

    contexts = [ssl.create_default_context()]
    try:
        import certifi

        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    contexts.append(ssl._create_unverified_context())  # last resort
    last = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(url, context=ctx, timeout=60) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            return
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"Failed to download {url}: {last}")


def _norm_arch(a: str) -> str:
    a = a.lower()
    if a in ("x86_64", "amd64"):
        return "amd64"
    if a in ("arm64", "aarch64"):
        return "arm64"
    if a in ("i386", "i686", "x86"):
        return "386"
    return a


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", default=sys.platform)
    ap.add_argument("--arch", default=platform.machine())
    args = ap.parse_args()

    osname = "darwin" if args.os == "darwin" else ("windows" if args.os.startswith("win") else "linux")
    arch = _norm_arch(args.arch)
    asset = ASSETS.get((osname, arch))
    if not asset:
        print(f"No cloudflared asset for {osname}/{arch}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/{asset}"
    print(f"Downloading {url}")
    tmp = OUT_DIR / asset
    _download(url, tmp)

    exe_name = "cloudflared.exe" if osname == "windows" else "cloudflared"
    dest = OUT_DIR / exe_name

    if asset.endswith(".tgz"):
        import tarfile

        with tarfile.open(tmp) as tf:
            member = next(m for m in tf.getmembers() if m.name.endswith("cloudflared"))
            with tf.extractfile(member) as src, open(dest, "wb") as out:
                out.write(src.read())
        tmp.unlink()
    else:
        tmp.rename(dest)

    if osname != "windows":
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Saved {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
