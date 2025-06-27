#!/usr/bin/env python3
# storage.py – rev-s4  (2025-06-30)
r"""
Persistent app-state helper
═══════════════════════════
* Stores JSON in a per-user config directory
  – **Windows** :  ``%APPDATA%\Playlist-Player\appstate.json``
  – **Unix**    :  ``~/.playlist-player/appstate.json``
* Atomic write (tmp + replace) to avoid corruption.
* Persists optional flags like ``auto_resume`` and ``normalize``.

(Only the doc-string was changed to a raw string so that back-slashes
inside the Windows path example don’t trigger SyntaxWarnings.)
"""

from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing  import Any, List

# ------------------------------------------------------------
# 1. resolve user-writable config path
# ------------------------------------------------------------
if os.name == "nt":
    base = Path(os.getenv("APPDATA", Path.home()))
    CFG_DIR = base / "Playlist-Player"
else:
    CFG_DIR = Path.home() / ".playlist-player"

CFG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = CFG_DIR / "appstate.json"

# ------------------------------------------------------------
# 2. atomic writer
# ------------------------------------------------------------
def _atomic_write(path: Path, data: Any) -> None:
    tmp = Path(tempfile.gettempdir()) / (path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)

# ------------------------------------------------------------
# 3. public API
# ------------------------------------------------------------

def load() -> dict:
    """Return persisted state or defaults.

    Structure::
        {
            "playlists": [...],
            "last": "/path" | None,
            "auto_resume": bool,
            "normalize": bool,
            "compress": bool,
        }
    """
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"playlists": [], "last": None, "auto_resume": False, "normalize": False, "compress": False}

    if isinstance(data, list):
        return {"playlists": data, "last": None, "auto_resume": False, "normalize": False, "compress": False}
    if isinstance(data, dict):
        return {
            "playlists": data.get("playlists", []),
            "last": data.get("last"),
            "auto_resume": data.get("auto_resume", False),
            "normalize": data.get("normalize", False),
            "compress": data.get("compress", False),
        }
    return {"playlists": [], "last": None, "auto_resume": False, "normalize": False, "compress": False}


def save(state: dict) -> None:
    """Write app state to disk."""
    _atomic_write(STATE_FILE, state)
