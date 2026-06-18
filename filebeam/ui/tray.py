"""System-tray icon (pystray). Start/stop sharing, open admin, show live URL.

The tray must own the main thread on macOS, so main.py hands control here. If
pystray or a display isn't available we fall back to a console loop.
"""
from __future__ import annotations

import threading
import webbrowser

try:
    import pystray
    from PIL import Image, ImageDraw
    _HAVE_TRAY = True
except Exception:  # pragma: no cover
    _HAVE_TRAY = False


def _icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 18, 56, 52], radius=6, fill=(37, 99, 235, 255))
    d.polygon([(8, 24), (8, 18), (24, 18), (30, 24)], fill=(37, 99, 235, 255))
    return img


def run_tray(runtime) -> None:
    if not _HAVE_TRAY:
        run_console(runtime)
        return

    state = runtime.state

    def url_text(_=None):
        u = state.tunnel.public_url
        return f"Public URL: {u}" if u else "Public URL: (not sharing)"

    def open_admin(icon, item):
        webbrowser.open(runtime.admin_url)

    def copy_url(icon, item):
        u = state.tunnel.public_url
        if u:
            try:
                import pyperclip  # optional
                pyperclip.copy(u)
            except Exception:
                pass

    def start_sharing(icon, item):
        threading.Thread(target=lambda: _safe_start(state), daemon=True).start()

    def stop_sharing(icon, item):
        state.tunnel.stop()
        icon.update_menu()

    def is_running(_):
        return state.tunnel.public_url is not None

    def quit_app(icon, item):
        runtime.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(url_text, open_admin, default=True),
        pystray.MenuItem("Open admin page", open_admin),
        pystray.MenuItem("Copy public URL", copy_url, enabled=is_running),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start sharing", start_sharing, enabled=lambda i: not is_running(i)),
        pystray.MenuItem("Stop sharing", stop_sharing, enabled=is_running),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("FileBeam", _icon_image(), "FileBeam", menu)

    # Refresh tooltip/menu when the URL changes.
    state.tunnel.add_listener(lambda url: icon.update_menu())

    icon.run()


def _safe_start(state):
    try:
        state.tunnel.start()
    except Exception as e:  # noqa: BLE001
        print(f"[FileBeam] tunnel failed to start: {e}")


def run_console(runtime) -> None:
    """Headless fallback: print URLs and block until Ctrl-C."""
    import time

    print(f"[FileBeam] Admin page: {runtime.admin_url}")
    print("[FileBeam] Starting tunnel…")
    try:
        url = runtime.state.tunnel.start()
        print(f"[FileBeam] PUBLIC URL: {url}")
    except Exception as e:  # noqa: BLE001
        print(f"[FileBeam] Tunnel failed: {e}")
    last = runtime.state.tunnel.public_url
    try:
        while True:
            time.sleep(2)
            now = runtime.state.tunnel.public_url
            if now != last:
                if now:
                    print(f"[FileBeam] ⚠️  PUBLIC URL CHANGED -> {now}  (old links are dead)")
                last = now
    except KeyboardInterrupt:
        print("\n[FileBeam] Shutting down…")
        runtime.stop()
