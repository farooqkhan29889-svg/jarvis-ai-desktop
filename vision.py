"""Vision for J.A.R.V.I.S. - JARVIS sees images and the screen (Gemini).

Uses the user's own free Google AI Studio (Gemini) key over plain REST. Two
entry points:
- the sidebar's "Show JARVIS an image" upload (works anywhere), and
- the agent tools look_at_image / look_at_screen (the screen tool exists on
  desktop builds only, like the rest of the PC control).

Security notes: the key is never echoed back or written anywhere except the
local .env; images are read-only; on non-desktop builds only files under the
user's home folder can be looked at.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

GEMINI_BASE = "https://generativelanguage.googleapis.com"

# Preferred Gemini models, best first; the live model list settles the choice.
VISION_PREFERENCES = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest")

UPLOAD_DIR = Path.home() / ".jarvis" / "uploads"
SHOTS_DIR = Path.home() / ".jarvis" / "shots"

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

_MAX_IMAGE_BYTES = 8 * 1024 * 1024

_model_cache: dict = {}

# --------------------------------------------------------------------------- #
# Key handling
# --------------------------------------------------------------------------- #


def from_env() -> str:
    """The Gemini key from the environment / .env, else Streamlit Secrets."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        try:
            import streamlit as st

            key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:  # noqa: BLE001
            key = ""
    return key


def _env_candidates() -> list:
    out = [Path.cwd()]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        out += [exe_dir, exe_dir.parent, exe_dir.parent.parent]
    return out


def save_key(key: str) -> str:
    """Persist the Gemini key into the local .env. Returns the file path.

    Mirrors the lookup order app.py uses to find .env (cwd, then next to the
    frozen exe and its parents), so the key lands in the same file the app
    reads at boot. Returns "" when there is nowhere sensible to write.
    """
    target = next(
        (folder / ".env" for folder in _env_candidates() if (folder / ".env").exists()),
        None,
    )
    if target is None:
        base = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path.cwd()
        )
        target = base / ".env"
    try:
        lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        out, replaced = [], False
        for line in lines:
            if line.strip().startswith("GEMINI_API_KEY="):
                out.append(f"GEMINI_API_KEY={key}")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            out.append(f"GEMINI_API_KEY={key}")
        target.write_text("\n".join(out) + "\n", encoding="utf-8")
        os.environ["GEMINI_API_KEY"] = key
        return str(target)
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# Model resolution (live, cached per key)
# --------------------------------------------------------------------------- #


def list_vision_models(api_key: str) -> list:
    """Gemini model IDs this key can use for generateContent (flash family)."""
    import httpx

    r = httpx.get(f"{GEMINI_BASE}/v1beta/models", params={"key": api_key}, timeout=30)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        name = (m.get("name") or "").split("/")[-1]
        methods = m.get("supportedGenerationMethods") or []
        if name and "generateContent" in methods and "flash" in name:
            out.append(name)
    return out


def pick_vision_model(available: list) -> str:
    for name in VISION_PREFERENCES:
        if name in available:
            return name
    return available[0] if available else VISION_PREFERENCES[0]


def resolve_model(api_key: str, force: bool = False) -> str:
    cached = _model_cache.get(api_key)
    if cached and not force:
        return cached
    try:
        model = pick_vision_model(list_vision_models(api_key))
    except Exception:  # noqa: BLE001 - offline: try the preferred name anyway
        model = VISION_PREFERENCES[0]
    _model_cache[api_key] = model
    return model


# --------------------------------------------------------------------------- #
# Looking at images
# --------------------------------------------------------------------------- #


def _prepare(data: bytes, ext: str) -> tuple:
    """Return (bytes, mime) safe for Gemini: GIF/BMP become PNG."""
    mime = MIME_BY_EXT.get(ext, "")
    if not mime:
        raise RuntimeError(
            f"unsupported image type '{ext or '?'}' - use png, jpg, webp, gif or bmp"
        )
    if mime in ("image/gif", "image/bmp"):
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(data))
            if getattr(img, "is_animated", False):
                img.seek(0)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            return buf.getvalue(), "image/png"
        except Exception:  # noqa: BLE001 - send as-is and let Gemini complain
            return data, mime
    return data, mime


def analyze_image(
    data: bytes,
    api_key: str,
    prompt: str = "Describe this image in detail.",
    mime: str = "image/png",
) -> str:
    """Ask Gemini about one image; returns its text answer.

    Raises RuntimeError with a friendly, key-free message on failure.
    """
    import httpx

    if not api_key:
        raise RuntimeError("no Gemini API key configured")
    if len(data) > _MAX_IMAGE_BYTES:
        raise RuntimeError("that image is too large (over 8 MB)")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(data).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }

    def _call(model: str):
        return httpx.post(
            f"{GEMINI_BASE}/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json=payload,
            timeout=90,
        )

    try:
        model = resolve_model(api_key)
        r = _call(model)
        if r.status_code == 404:
            # Stale cached name - re-resolve once and retry.
            model = resolve_model(api_key, force=True)
            r = _call(model)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"could not reach Gemini ({type(exc).__name__})") from exc

    if r.status_code != 200:
        reason = ""
        try:
            err = r.json().get("error", {})
            reason = " ".join(
                str(err.get(k, "")) for k in ("status", "message")
            ).strip()
        except Exception:  # noqa: BLE001
            pass
        # Google reports a bad key as 400 INVALID_ARGUMENT ("API key not
        # valid"), so match on the text, not just the HTTP code.
        if r.status_code in (401, 403) or "API_KEY" in reason.upper().replace(" ", "_"):
            raise RuntimeError("Gemini rejected the API key - check the key in the sidebar")
        if r.status_code == 429:
            raise RuntimeError("Gemini free-tier limit reached - try again in a minute")
        raise RuntimeError(f"Gemini error {r.status_code}: {reason[:160]}")

    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = "\n".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text:
        raise RuntimeError("Gemini returned no description")
    return text[:4000]


def _within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_image_path(path_str: str) -> Path:
    """Resolve a user/model-supplied image path inside the user's own folders."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    roots = [Path.home().resolve(), UPLOAD_DIR.resolve(), SHOTS_DIR.resolve()]
    try:
        from system_control import allowed_roots

        roots += [Path(r).resolve() for r in allowed_roots()]
    except Exception:  # noqa: BLE001
        pass
    if not any(_within(root, p) for root in roots):
        raise RuntimeError("that file is outside your own folders")
    if not p.is_file():
        raise RuntimeError(f"no file at {p}")
    return p


def save_upload(name: str, data: bytes) -> str:
    """Store one uploaded image under ~/.jarvis/uploads; returns its path."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(name or "").suffix.lower()
    if ext not in MIME_BY_EXT:
        ext = ".png"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = UPLOAD_DIR / f"upload_{stamp}_{os.getpid()}{ext}"
    path.write_bytes(data)
    return str(path)


def capture_screen() -> str:
    """Grab the whole screen (all monitors) and return the PNG path."""
    from PIL import ImageGrab

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOTS_DIR / f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png"
    img = ImageGrab.grab(include_layered_windows=True, all_screens=True)
    img.save(path, format="PNG")
    return str(path)


# --------------------------------------------------------------------------- #
# Agent tools
# --------------------------------------------------------------------------- #

VISION_NOTES = (
    "\n\nVISION - JARVIS can see:\n"
    "- look_at_image: study an image file on the computer (photo, chart, "
    "screenshot) and answer questions about it. When the user attaches an image "
    "(its path appears in the message) ALWAYS call this tool with that exact "
    "path - NEVER guess or invent what an image shows.\n"
    "- look_at_screen (desktop only): take a fresh screenshot of the screen and "
    "study it. Use it for 'what is on my screen', 'read this error', 'what does "
    "this dialog say'.\n"
    "- Report only what is actually visible; if something is unclear, say so."
)


def make_vision_tools(api_key: str, desktop: bool = False) -> list:
    """LangChain tools bound to one Gemini key."""
    from langchain_core.tools import tool

    @tool
    def look_at_image(
        path: str, question: str = "Describe this image in detail."
    ) -> str:
        """Look at an image file on this computer and answer a question about it.
        Use for pictures, photos, charts, diagrams and screenshot files
        (png, jpg, webp, gif, bmp). Pass the full file path in 'path', and put
        what the user wants to know in 'question'."""
        try:
            file = _resolve_image_path(path)
            data, mime = _prepare(file.read_bytes(), file.suffix.lower())
            return analyze_image(data, api_key, question, mime)
        except Exception as exc:  # noqa: BLE001
            return f"Could not look at that image: {exc}"

    tools = [look_at_image]

    if desktop:

        @tool
        def look_at_screen(
            question: str = "Describe what is on the screen and flag anything the user should notice.",
        ) -> str:
            """Take a screenshot of this computer's screen right now and look at
            it. Use for 'what is on my screen', 'read this error', 'what does
            this dialog say' and similar. 'question' is what the user wants to
            know about it."""
            try:
                shot = capture_screen()
                data, mime = _prepare(Path(shot).read_bytes(), ".png")
                return analyze_image(data, api_key, question, mime)
            except Exception as exc:  # noqa: BLE001
                return f"Could not look at the screen: {exc}"

        tools.append(look_at_screen)

    return tools
