#!/usr/bin/env bash
# Build the macOS .app bundle. Run from the project root:  ./filebeam/packaging/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${PYTHON:-python3}"
echo "==> Creating build venv"
"$PY" -m venv .build-venv
source .build-venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt -r requirements-selfhosted.txt pyinstaller >/dev/null

echo "==> Fetching cloudflared (bundled tunnel binary)"
python filebeam/packaging/fetch_cloudflared.py

echo "==> Running PyInstaller"
pyinstaller --noconfirm --clean filebeam/packaging/filebeam.spec

echo "==> Done. App at: dist/FileBeam.app"
echo "    Run it by double-clicking, or: open dist/FileBeam.app"
