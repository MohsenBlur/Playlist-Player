#!/usr/bin/env python3
# storage.py
"""Persist the list of playlists (path + display name) between sessions."""

from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict

_STATE = "app_state.json"


def load() -> List[Dict]:
    if Path(_STATE).exists():
        try:
            return json.loads(Path(_STATE).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def save(playlists: List[Dict]) -> None:
    Path(_STATE).write_text(json.dumps(playlists, indent=2),
                            encoding="utf-8")
