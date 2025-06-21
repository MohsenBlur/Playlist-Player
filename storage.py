#!/usr/bin/env python3
# storage.py – rev-s2  (2025-06-27)
"""
Persistent app-state helper.

* Stores JSON in a per-user config directory
  - Windows :  %APPDATA%\Playlist-Player\appstate.json
  - Unix    :  ~/.playlist-player/appstate.json
* Atomic write (tmp + replace) to avoid corruption.
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
# 2. helpers
# ------------------------------------------------------------
def _atomic_write(path: Path, data: Any) -> None:
    tmp = Path(tempfile.gettempdir()) / (path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)

# ------------------------------------------------------------
# 3. public API
# ------------------------------------------------------------
def load() -> List[dict]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save(records: List[dict]) -> None:
    _atomic_write(STATE_FILE, records)
