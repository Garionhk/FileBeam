"""FileBeam entry point.

Default: boots the public server + tunnel and opens the native desktop admin GUI
(dark theme, multi-language). Headless mode (--no-gui) skips the GUI and runs a
console loop, optionally serving the legacy web admin.
"""
from __future__ import annotations

import os
import sys

# Windowed PyInstaller builds on Windows have sys.stdout/sys.stderr == None.
# That crashes uvicorn's log formatter (calls .isatty() on the stream) and any
# print() call. Give them a sink before anything touches them. No effect on
# macOS / console builds, where the streams are real.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import argparse  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from filebeam.server.app import Runtime  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="filebeam", description="Dead-simple public file sharing")
    parser.add_argument("--no-gui", action="store_true", help="run headless (no desktop window)")
    parser.add_argument("--no-tunnel", action="store_true", help="don't auto-start the tunnel")
    parser.add_argument("--web-admin", action="store_true",
                        help="also serve the legacy web admin page at 127.0.0.1")
    args = parser.parse_args(argv)

    runtime = Runtime()

    if args.no_gui:
        runtime.start(start_admin_web=True)
        time.sleep(0.6)
        from filebeam.ui.tray import run_console
        if args.no_tunnel:
            _idle(runtime)
        else:
            run_console(runtime)
        return 0

    # GUI mode (default): web admin off; the window is the control panel.
    runtime.start(start_admin_web=args.web_admin)
    time.sleep(0.6)
    if not args.no_tunnel:
        threading.Thread(target=lambda: _try_start(runtime), daemon=True).start()

    from filebeam.ui.gui import run_gui
    run_gui(runtime)  # blocks on the Tk main loop until the window closes
    return 0


def _try_start(runtime) -> None:
    try:
        url = runtime.state.tunnel.start()
        print(f"[FileBeam] PUBLIC URL: {url}")
    except Exception as e:  # noqa: BLE001
        print(f"[FileBeam] Tunnel failed to start: {e}")


def _idle(runtime) -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        runtime.stop()


if __name__ == "__main__":
    sys.exit(main())
