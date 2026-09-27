# PyInstaller spec for the single-file JARVIS executable.
# Build with:  pyinstaller jarvis.spec
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("app.py", "."),
    ("agent.py", "."),
    ("system_control.py", "."),
    ("assets", "assets"),
]
binaries = []
hiddenimports = [
    "streamlit_mic_recorder",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_classic",
    "langchain_text_splitters",
    "langchain_groq",
    "groq",
    "duckduckgo_search",
    "wikipedia",
    "dotenv",
    "webview",
]

# Conda-based interpreters keep runtime DLLs (ffi/ssl/sqlite) outside the venv,
# so PyInstaller misses them and the frozen exe dies on `import _ctypes`.
# Bundle them explicitly from the base interpreter.
_base = sys.base_prefix
for _rel in [
    os.path.join("Library", "bin", "ffi-7.dll"),
    os.path.join("Library", "bin", "ffi-8.dll"),
    os.path.join("Library", "bin", "ffi.dll"),
    os.path.join("Library", "bin", "libssl-3-x64.dll"),
    os.path.join("Library", "bin", "libcrypto-3-x64.dll"),
    os.path.join("Library", "bin", "sqlite3.dll"),
    os.path.join("Library", "bin", "zlib.dll"),
    os.path.join("DLLs", "libffi-7.dll"),
    os.path.join("DLLs", "libffi-8.dll"),
]:
    _p = os.path.join(_base, _rel)
    if os.path.exists(_p):
        binaries.append((_p, "."))

for pkg in [
    "streamlit",
    "streamlit_mic_recorder",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_classic",
    "langchain_groq",
    "groq",
]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("streamlit")

a = Analysis(
    ["jarvis_exe_main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# One-dir build: no self-extraction at startup, so it launches far faster than
# a single-file build. Ship the whole dist\JARVIS folder.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # set to False for a silent, window-only build
    disable_windowed_traceback=False,
    icon="assets/jarvis.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="JARVIS",
)
