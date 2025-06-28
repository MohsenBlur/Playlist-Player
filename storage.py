#!/usr/bin/env python3
# storage.py – rev-s6 (2025-07-01)

r"""
Resilient persistent-state helper
═════════════════════════════════
* Same config folder for script **and** PyInstaller binary
  – Windows  : %APPDATA%\Playlist-Player\appstate.json
  – macOS/*nix: ~/.config/playlist-player/appstate.json
...
"""

from __future__ import annotations
import json, os, tempfile, shutil, datetime as _dt
from pathlib import Path
from typing  import Any, Dict

# ────────────────────────────────────────────────────────────
# 1. resolve canonical config path
# ────────────────────────────────────────────────────────────
if os.name == "nt":
    # %APPDATA% should exist for *all* normal accounts.  If it doesn't,
    # fall back to <User>\AppData\Roaming.
    _appdata = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    CFG_DIR  = _appdata / "Playlist-Player"
else:
    # Follow XDG spec; ~/.config if XDG_CONFIG_HOME not set.
    CFG_DIR  = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "playlist-player"

CFG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = CFG_DIR / "appstate.json"
BAK_FILE   = CFG_DIR / "appstate.bak"

# ────────────────────────────────────────────────────────────
# 2. atomic writer (+ backup)
# ────────────────────────────────────────────────────────────
def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as UTF-8 JSON atomically and keep a .bak copy."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # create/refresh backup *before* replacement
    if path.exists():
        shutil.copy2(path, BAK_FILE)
    tmp.replace(path)

# ────────────────────────────────────────────────────────────
# 3. helpers
# ────────────────────────────────────────────────────────────
def _empty_state() -> Dict:
    return {
        "version":     1,
        "playlists":   [],
        "last":        None,
        "auto_resume": False,
        "normalize":   False,
        "compress":    False,
        "boost_gain":  12,          # dB  (new)
        "theme":       "System",
    }

def _load_json(path: Path) -> Dict | None:
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception:
        return None

# ────────────────────────────────────────────────────────────
# 4. public API
# ────────────────────────────────────────────────────────────
def load() -> Dict:
    """Return persisted state.  Rolls back to .bak on corruption."""
    data = _load_json(STATE_FILE)
    if data is None:
        # try backup
        data = _load_json(BAK_FILE)
        if data:
            # restore working copy
            shutil.copy2(BAK_FILE, STATE_FILE)
        else:
            return _empty_state()

    # upgrade from very old formats
    if isinstance(data, list):
        data = {"playlists": data}  # old v0 schema

    # merge with defaults to ensure all keys exist
    base = _empty_state()
    base.update(data)
    return base


def save(state: Dict) -> None:
    """Write *state* to disk, safely."""
    # add / update version tag for future migrations
    state["version"] = 1
    _atomic_write(STATE_FILE, state)
