#!/usr/bin/env python3
# history.py  –  rev-h4  (2025-06-27)
"""
Read / write per-playlist history files.

Schema  (JSON)
--------------
{
  "display_name": "My Road-Trip Mix",   # optional – NEW
  "track_index" : 3,
  "position"    : 17.5,                 # seconds
  "finished"    : ["/path/track1.flac", …]
}
All writes are atomic (tmp + replace) and tolerant to partial data.
"""

from __future__ import annotations
import json, tempfile, os, shutil
from pathlib import Path
from typing  import Set, Dict, Any

BAK_PATH: Path | None = None  # updated by _path()

def _path(pl: Path) -> Path:
    path = pl.with_suffix(pl.suffix + ".history.json")
    global BAK_PATH
    BAK_PATH = path.with_suffix(path.suffix + ".bak")
    return path

def load(pl: Path) -> Dict[str, Any]:
    p = _path(pl)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        if BAK_PATH and BAK_PATH.exists():
            try:
                data = json.loads(BAK_PATH.read_text(encoding="utf-8"))
                shutil.copy2(BAK_PATH, p)
                return data
            except Exception:
                pass
        return {}

def _atomic_write(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")          # same directory → same volume
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if path.exists() and BAK_PATH:
        shutil.copy2(path, BAK_PATH)
    tmp.replace(path)

def save(pl: Path,
         track_index: int,
         position: float,
         finished: Set[str]):
    data           = load(pl)
    data["track_index"] = track_index
    data["position"]    = position
    data["finished"]    = sorted(finished)
    _atomic_write(_path(pl), data)

# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# NEW: persist friendly name so it survives app.state loss
# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––
def ensure_name(pl: Path, name: str):
    if not name:
        return
    p   = _path(pl)
    dat = load(pl)
    if dat.get("display_name") == name:
        return
    dat["display_name"] = name
    _atomic_write(p, dat)
