"""Instant "Stop" for the streaming answer, without Streamlit's rerun wedge.

A real Streamlit button cannot cut off a streaming answer: clicking any widget
while a script run is active makes Streamlit kill the run (1.64 behaviour, no
opt-out until 1.66), which also loses the partial answer. So the Stop control
is an HTML button inside a component iframe. It calls a tiny extra HTTP route
registered on the live Starlette server of this same process; the route drops
a flag file, and the streaming generator polls that flag after every token
and simply returns - the partial answer stays on screen, ChatGPT-style.

The same side channel keeps hands-free mode alive. The wake tick in app.py is
a self-rerun chain: miss one tick and the page never runs again, so a dictated
command would sit on disk unnoticed. A hidden heartbeat iframe pings
/_jarvis/tick every few seconds; while a command is waiting the route nudges
every idle session to rerun, which revives a dead chain within one heartbeat.
"""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path

STOP_FLAG = Path.home() / ".jarvis" / "stop_voice.flag"
STOP_ROUTE = "/_jarvis/stop"
TICK_ROUTE = "/_jarvis/tick"

_installed = False


def request_stop() -> None:
    STOP_FLAG.parent.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.write_text("stop", encoding="utf-8")


def clear_stop() -> None:
    try:
        STOP_FLAG.unlink()
    except OSError:
        pass


def stop_requested() -> bool:
    return STOP_FLAG.exists()


def _command_pending() -> bool:
    """True while a dictated command waits in ~/.jarvis/wake_command.json, or a
    WhatsApp Cloud API message is waiting to be shown."""
    root = os.environ.get("JARVIS_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".jarvis"
    try:
        data = json.loads((base / "wake_command.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if str(data.get("text", "")).strip():
        return True
    try:
        import whatsapp_cloud

        return whatsapp_cloud.has_events()
    except Exception:  # noqa: BLE001
        return False


def _live_starlette_app():
    """The Starlette app of this Streamlit process, or None."""
    try:
        from streamlit.web.server.starlette.starlette_server import UvicornServer
    except Exception:  # noqa: BLE001
        return None
    for obj in gc.get_objects():
        if type(obj) is not UvicornServer:
            continue
        server = getattr(obj, "_server", None)  # uvicorn.Server
        config = getattr(server, "config", None)  # uvicorn.Config
        app = getattr(config, "app", None)
        if app is not None and hasattr(app, "router"):
            return app
    return None


def _sessions():
    """Every session with a live client in this process (best effort).

    Connected sessions live in the session manager's active map, not in
    _session_storage (which only holds disconnected sessions for reconnect
    and expires them after two minutes).
    """
    try:
        from streamlit.runtime import get_instance

        infos = get_instance()._session_mgr.list_active_sessions()
        return [info.session for info in infos]
    except Exception:  # noqa: BLE001
        pass
    try:
        from streamlit.runtime.app_session import AppSession
    except Exception:  # noqa: BLE001
        return []
    return [obj for obj in gc.get_objects() if type(obj) is AppSession]


def nudge_reruns(apply: bool = True) -> tuple:
    """Ask every connected session that is not mid-script to rerun.

    Returns (nudged, seen, busy). A session whose _scriptrunner exists but is
    idle must still be nudged - the runner object lives for the whole session,
    so it is not a busy signal (AppSession._state is). A rerun request against
    a script that is actually running stops it (fastReruns), which would kill
    the in-flight answer, so those sessions are only counted.
    """
    nudged = seen = busy = 0
    for sess in _sessions():
        seen += 1
        try:
            if getattr(getattr(sess, "_state", None), "name", "") == "APP_IS_RUNNING":
                busy += 1
                continue
            if apply:
                sess.request_rerun(None)
                nudged += 1
        except Exception:  # noqa: BLE001
            continue
    return nudged, seen, busy


def ensure_routes() -> bool:
    """Register the stop + tick routes once. False when they cannot be installed."""
    global _installed
    if _installed:
        return True
    try:
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        app = _live_starlette_app()
        if app is None:
            return False

        async def _stop_endpoint(_request):
            request_stop()
            return PlainTextResponse(
                "stopped",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        async def _tick_endpoint(_request):
            pending = _command_pending()
            nudged, seen, busy = nudge_reruns(apply=pending)
            return PlainTextResponse(
                f"tick pending={int(pending)} nudged={nudged} sessions={seen} busy={busy}",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Insert first: Streamlit's static/SPA fallback routes otherwise
        # swallow unknown paths before they reach a route appended last.
        existing = {getattr(r, "path", None) for r in app.routes}
        if STOP_ROUTE not in existing:
            app.routes.insert(0, Route(STOP_ROUTE, _stop_endpoint, methods=["GET", "POST"]))
        if TICK_ROUTE not in existing:
            app.routes.insert(0, Route(TICK_ROUTE, _tick_endpoint, methods=["GET", "POST"]))
        _installed = True
        return True
    except Exception:  # noqa: BLE001
        return False
