"""Frozen-app entry point for the single-file JARVIS .exe.

Threading model (Windows):
- PyWebView's GUI loop MUST run on the MAIN thread.
- Streamlit's `bootstrap.run` installs signal handlers and therefore also needs
  the main thread, so we instead drive the lower-level `Server` (which installs
  no signal handlers) on a background asyncio thread.

Result: native window on the main thread, Streamlit server on a worker thread.
If the window cannot start (or JARVIS_NO_GUI=1), fall back to the browser.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
# Bind the server to all interfaces so a phone on the same Wi-Fi can reach
# JARVIS and drive the PC-control tools; the native window uses localhost.
BIND = "0.0.0.0"


def base_path() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def pick_port(start: int = 8501) -> int:
    for p in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, p)) != 0:
                return p
    return start


def main() -> int:
    base = base_path()
    script = os.path.join(base, "app.py")
    if not os.path.exists(script):
        print("[JARVIS] app.py not found next to executable.")
        return 1

    # This is the user's own machine, so the PC-control tools are available.
    os.environ.setdefault("JARVIS_SYSTEM_CONTROL", "1")

    port = pick_port()
    url = f"http://{HOST}:{port}"
    no_gui = os.environ.get("JARVIS_NO_GUI") == "1"

    from streamlit import config as st_config

    st_config.set_option("server.headless", True)
    st_config.set_option("server.port", port)
    st_config.set_option("server.address", BIND)
    st_config.set_option("browser.gatherUsageStats", False)
    st_config.set_option("global.developmentMode", False)

    ready = threading.Event()
    holder = {}

    def serve_thread():
        import asyncio

        from streamlit.web import bootstrap
        from streamlit.web.server import Server

        bootstrap._fix_sys_path(script)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server = Server(script, is_hello=False)
        holder["server"] = server

        async def _run():
            await server.start()
            ready.set()
            await server.stopped

        try:
            loop.run_until_complete(_run())
        except Exception as exc:  # noqa: BLE001
            print(f"[JARVIS] Server error: {exc}")
            ready.set()

    threading.Thread(target=serve_thread, daemon=True).start()

    if not ready.wait(timeout=120):
        print("[JARVIS] Server did not become ready in time.")
        return 1
    print(f"[JARVIS] Server ready on {url}")

    def stop_server():
        srv = holder.get("server")
        if srv:
            try:
                srv.stop()
            except Exception:  # noqa: BLE001
                pass

    if no_gui:
        print("[JARVIS] JARVIS_NO_GUI set - opening default browser.")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_server()
        return 0

    window_ok = threading.Event()
    gui_error = {}

    def on_loaded():
        window_ok.set()

    try:
        import webview

        window = webview.create_window(
            title="J.A.R.V.I.S.",
            url=url,
            width=1280,
            height=880,
            min_size=(900, 600),
            background_color="#04070d",
            text_select=True,
        )
        window.events.loaded += on_loaded
    except Exception as exc:  # noqa: BLE001
        gui_error["e"] = exc
        window = None

    if window is None:
        print(f"[JARVIS] Native window unavailable ({gui_error.get('e')}); using browser.")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_server()
        return 0

    # Main thread drives the GUI loop; closing the window returns from start().
    webview.start(private_mode=False)
    stop_server()
    print("[JARVIS] Window closed. Shutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
