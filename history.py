#!/usr/bin/env python3
# history.py
"""Per-playlist playback history (JSON beside playlist file)."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Set


_HISTORY_SUFFIX = ".history.json"


def _hist_path(pl_path: Path) -> Path:
    return pl_path.with_suffix(pl_path.suffix + _HISTORY_SUFFIX)


def load(pl_path: Path) -> Dict:
    hist_file = _hist_path(pl_path)
    if hist_file.exists():
        try:
            return json.loads(hist_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    # defaults
    return {"track_index": 0,
            "position": 0.0,
            "finished": []}            # list of absolute paths


def save(pl_path: Path,
         track_index: int,
         position: float,
         finished: Set[str]) -> None:
    data = {"track_index": track_index,
            "position": position,
            "finished": sorted(finished)}
    _hist_path(pl_path).write_text(json.dumps(data, indent=2),
                                   encoding="utf-8")
