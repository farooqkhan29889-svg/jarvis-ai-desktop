"""J.A.R.V.I.S. desktop window.

Runs the Streamlit app as a local server and opens it in a native PyWebView
window, so JARVIS launches as its own desktop app instead of a browser tab.

Run with:  python desktop.py     (or double-click run_desktop.bat)
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request

import webview

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
HOST = "127.0.0.1"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) != 0


def _pick_port(start: int = 8501) -> int:
    for p in range(start, start + 20):
        if _port_free(p):
            return p
    return start


def _wait_ready(url: str, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    health = url.rstrip("/") + "/_stcore/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=2) as resp:
                if resp.read().decode().strip() == "ok":
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


def main() -> int:
    port = _pick_port()
    url = f"http://{HOST}:{port}"

    print(f"[JARVIS] Starting local server on {url} ...")
    env = dict(os.environ, JARVIS_SYSTEM_CONTROL="1")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", APP,
            "--server.headless", "true",
            "--server.port", str(port),
            "--server.address", HOST,
            "--browser.gatherUsageStats", "false",
        ],
        cwd=HERE,
        env=env,
    )

    try:
        if not _wait_ready(url):
            print("[JARVIS] Server did not become ready in time.")
            return 1

        print("[JARVIS] Opening desktop window ...")
        window = webview.create_window(
            title="J.A.R.V.I.S.",
            url=url,
            width=1280,
            height=880,
            min_size=(900, 600),
            background_color="#04070d",
            text_select=True,
        )
        # WebView2 (Windows) needs this so the mic can be used for voice input.
        webview.start(private_mode=False, debug=False)
        return 0
    finally:
        print("[JARVIS] Shutting down ...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
