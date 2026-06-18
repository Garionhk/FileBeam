# Build the Windows .exe. Run from the project root:
#   powershell -ExecutionPolicy Bypass -File fileshare\packaging\build_win.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")

$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Write-Host "==> Creating build venv"
& $py -m venv .build-venv
& .\.build-venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.build-venv\Scripts\pip.exe install -r requirements.txt -r requirements-selfhosted.txt pyinstaller | Out-Null

Write-Host "==> Fetching cloudflared (bundled tunnel binary)"
& .\.build-venv\Scripts\python.exe fileshare\packaging\fetch_cloudflared.py

Write-Host "==> Running PyInstaller"
& .\.build-venv\Scripts\pyinstaller.exe --noconfirm --clean fileshare\packaging\fileshare.spec

Write-Host "==> Done. App at: dist\FileShare\FileShare.exe"
