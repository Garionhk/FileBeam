# FileBeam

Dead-simple, cross-platform (Windows + macOS) file sharing. You run **one** app
and drop files into shared folders. **Anyone on the internet** can download them
in a plain browser via a public URL — no account, no client install, nothing on
the downloader's end, and **nothing for you to set up**: no firewall changes, no
router port-forwarding.

It works by making an **outbound** connection from your machine to a free public
tunnel, so your computer is reachable from the internet without opening any port.

---

## Quick start

### Option A — download the app (recommended)
1. Download **FileBeam.app** (macOS) or **FileBeam.exe** (Windows).
2. Double-click it. A **desktop control window** opens (dark theme) and a public
   tunnel starts automatically.
3. The **public URL** is shown prominently at the top of the window. Click
   **Copy URL** and share it. Done.

The control panel is a **native desktop app** — no browser needed to manage
sharing. You can switch the interface language (**English / 繁體中文**) from the
dropdown in the top-right; the choice is remembered.

The default tunnel is **Cloudflare Quick Tunnel (TryCloudflare)** — free, no
account, no signup. The `cloudflared` binary is bundled, so first run is truly
zero-setup.

**Building the binaries yourself:**
- **macOS:** `./filebeam/packaging/build_mac.sh` → `dist/FileBeam.app`
- **Windows:** `powershell -ExecutionPolicy Bypass -File filebeam\packaging\build_win.ps1` → `dist\FileBeam\FileBeam.exe`
- **Both at once (no machines to set up):** push this repo to GitHub and run the
  **Build apps** workflow (`.github/workflows/build.yml`) from the Actions tab — it
  produces `FileBeam-macOS.zip` and `FileBeam-Windows.zip` as artifacts.

> A Windows `.exe` can only be built on Windows (PyInstaller does not
> cross-compile); use the Windows build script or the GitHub Actions workflow.
> Unsigned builds trip Gatekeeper/SmartScreen on first launch — see *Quick start*.

### Option B — run from source
```bash
pip install -r requirements.txt
python filebeam/packaging/fetch_cloudflared.py   # grab the bundled tunnel binary
python run.py
```
Headless / server mode (no desktop window): `python run.py --no-gui`. Add
`--web-admin` to also serve the legacy browser admin page at `http://127.0.0.1:8765`.

---

## Share a folder publicly
1. In the **Folders** tab, fill the **Add folder** form: a display name, pick the
   folder with **Browse…**, leave access as **PUBLIC**, click **Save**.
2. Click **＋ Add files** on the folder to copy files in, or enable **Watch for
   new files** and just drop files into that folder in Finder/Explorer.
3. Anyone who opens your **public URL** sees the folder and can download. No
   passcode required for PUBLIC folders.

### Restrict a folder to a group
1. When adding the folder, set access to **GROUP**.
2. In the **Groups & Access** tab, create a **group** (e.g. `team`) with a passcode.
3. In the permission grid, set that group to `download` or `upload` on the folder.
4. Share either the **group passcode** or a **tokened link** (**Share Links** tab →
   Create link → Copy link). Visitors never see folders their group can't access.

Tokened links can carry an **expiry** and a **download cap**, and can be **revoked**
at any time from the admin page.

---

## ⚠️ The public URL changes

Free no-account tunnels hand out a **random URL that changes every time the tunnel
restarts or reconnects**. The admin page always shows the live URL and pops a clear
warning the moment it changes — **previously shared links stop working**. Re-copy
and re-share the new URL when that happens. (Want a stable URL? See *Run your own
relay* below.)

---

## Swap the tunnel backend

Remote access lives behind a tiny `TunnelBackend` interface
(`start() -> public_url`, `stop()`, `status()`, `on_url_change()`), so the backend
is fully pluggable. Choose one in `settings.toml` or the admin dropdown:

| Backend         | Account? | Bundled binary | Notes |
|-----------------|----------|----------------|-------|
| `cloudflared`   | **No**   | Yes            | **Default.** Random URL each run. |
| `localhost_run` | No       | No (system ssh)| SSH reverse tunnel, random URL. |
| `selfhosted`    | —        | No             | **Advanced.** Your own VPS relay, stable URL. |
| `lan`           | —        | No             | LAN only, no tunnel. May need a one-time firewall allow. |

```toml
# settings.toml
[tunnel]
backend = "cloudflared"   # or localhost_run / selfhosted / lan
```

### Add your own backend in ~30 lines
1. Subclass `TunnelBackend` (copy `filebeam/tunnels/localhost_run.py` as a template).
2. Implement `start`/`stop`; call `self._set_url(url)` whenever the URL appears or
   changes so the UI stays live.
3. Register it: add one line to `BACKENDS` in `filebeam/tunnels/registry.py`.

The settings file and the admin dropdown pick it up automatically.

---

## Optional: run your own relay (advanced, not required)

For zero third parties in the path, run the included relay on a server **with a
public IP** (e.g. a small VPS — a home/NAT machine will not work, because the relay
itself must be reachable from the internet).

On the VPS:
```bash
pip install fastapi "uvicorn[standard]" websockets
RELAY_TOKEN=choose-a-secret RELAY_PUBLIC_URL=https://share.example.com \
  python filebeam/packaging/relay_server.py --port 8080
# put it behind your TLS reverse proxy / give it a domain
```
On your host (`settings.toml`):
```toml
[tunnel]
backend = "selfhosted"
[tunnel.selfhosted]
relay_url   = "wss://share.example.com/_relay/ws"
relay_token = "choose-a-secret"
```
Install the host-side extras once: `pip install -r requirements-selfhosted.txt`.
Your app connects **outward** to the relay; the relay accepts public HTTP and
forwards it to you. You get a **stable URL you control**.

---

## Security

This app exposes files to the public internet, so it is built defensively:

- **Path-traversal protection** centralized in `safe_join` — every public file
  operation goes through it; `../` escapes return 404.
- **Permission re-checked per request** against the DB; unauthorized folders are
  never listed (no existence leak — denied access returns 404, not 403).
- **Group gating** via hashed passcodes (argon2, PBKDF2 fallback) and unguessable
  `secrets`-based tokens. Links support expiry, download caps, and revocation.
- **Rate limiting** on auth attempts and downloads (per IP, sliding window).
- **Streaming** downloads (never loads a whole file into memory) with **HTTP range
  requests** for resumable transfers.
- Optional **per-folder quota** and **max upload size**.
- The **control panel is a local desktop app** (no network port by default), so
  there is no admin surface for the tunnel to expose. The legacy web admin
  (`--web-admin`) stays bound to `127.0.0.1` and is a separate app from the public
  server, so it can never be reached through the tunnel either.

---

## Project layout

```
filebeam/
  config.py            settings + data paths
  main.py              entry point (servers + tray)
  server/              FastAPI apps, routing, DB, streaming, sessions
  tunnels/             TunnelBackend interface + implementations + registry
  auth/                groups/permissions, passcode hashing, rate limiting
  ui/                  desktop GUI (gui.py), i18n (i18n.py), legacy web admin assets, tray
  packaging/           PyInstaller spec, build scripts, cloudflared fetch, relay
  tests/               smoke tests
settings.toml          configuration
requirements.txt       runtime + test deps
requirements-selfhosted.txt   extras for the optional relay backend
run.py                 convenience launcher
```

## Run the tests
```bash
pip install -r requirements.txt
pytest filebeam/tests/ -q
```

## License
Provided as-is for the requested project.
