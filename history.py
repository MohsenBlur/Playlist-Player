#!/usr/bin/env python3
# history.py – rev-d1  (2025-06-25)
"""
Per-playlist playback history, stored as JSON next to the playlist.

Changes
───────
• `save()` now writes atomically:
    playlist.fplite.history.json.tmp  →  os.replace() →  .history.json
  so a crash/power-loss can’t corrupt the file.
"""

from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Dict, Set

_HISTORY_SUFFIX = ".history.json"


def _hist_path(pl_path: Path) -> Path:
    return pl_path.with_suffix(pl_path.suffix + _HISTORY_SUFFIX)


def load(pl_path: Path) -> Dict:
    path = _hist_path(pl_path)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    # defaults
    return {"track_index": 0, "position": 0.0, "finished": []}


def save(pl_path: Path,
         track_index: int,
         position: float,
         finished: Set[str]) -> None:
    """Atomically write history JSON (tmp file + rename)."""
    data = {
        "track_index": track_index,
        "position": position,
        "finished": sorted(finished),
    }
    path = _hist_path(pl_path)
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".tmp",
                                        dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp_name, path)          # atomic on NTFS / POSIX
    finally:
        # if something went wrong and tmp still exists
        try: os.unlink(tmp_name)
        except FileNotFoundError: pass
