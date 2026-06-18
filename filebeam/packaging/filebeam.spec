# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FileBeam.

Bundles Python, all deps, the HTML/CSS/JS UI, the settings template, and the
cloudflared binary so the packaged app is truly zero-setup on first run.

Build:  pyinstaller filebeam/packaging/filebeam.spec
Output: dist/FileBeam.app (macOS) or dist/FileBeam/FileBeam.exe (Windows)
Run `python filebeam/packaging/fetch_cloudflared.py` first to populate bin/.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent.parent  # project root
PKG = ROOT / "filebeam"

is_win = sys.platform.startswith("win")
cf_name = "cloudflared.exe" if is_win else "cloudflared"

datas = [
    (str(PKG / "ui" / "templates"), "filebeam/ui/templates"),
    (str(PKG / "ui" / "static"), "filebeam/ui/static"),
    (str(ROOT / "settings.toml"), "."),
]
# CustomTkinter ships theme JSON + fonts that must travel with the app.
datas += collect_data_files("customtkinter")
binaries = []
cf_path = PKG / "packaging" / "bin" / cf_name
if cf_path.exists():
    binaries.append((str(cf_path), "filebeam/packaging/bin"))

hiddenimports = [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "argon2", "watchdog.observers", "pystray", "PIL",
    # Optional self-hosted relay backend (imported lazily in tunnels/selfhosted.py)
    "httpx", "websockets", "websockets.asyncio.client",
    # Desktop GUI
    "customtkinter",
]

a = Analysis(
    [str(PKG / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FileBeam",
    console=False,           # windowed app (tray); no console window
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FileBeam")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FileBeam.app",
        icon=None,
        bundle_identifier="com.filebeam.app",
        info_plist={
            "CFBundleName": "FileBeam",
            "NSHighResolutionCapable": True,
        },
    )
