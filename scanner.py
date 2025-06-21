#!/usr/bin/env python3
# scanner.py
"""Scan folders for playlists (.m3u, .m3u8, .fplite) without altering them.

Changes 2025-06-20 d
────────────────────
* Decode percent-encoding (%20 → space, etc.).
* Resolve relative paths against the playlist file’s directory.
"""

from __future__ import annotations
import os
from pathlib import Path, PureWindowsPath
from dataclasses import dataclass
from typing import List
from urllib.parse import unquote   # NEW

PLAYLIST_EXTS = {".m3u", ".m3u8", ".fplite"}
URI_PREFIXES  = ("file:///", "file://", "file:\\\\", "file:\\")  # longest first


@dataclass
class Playlist:
    path: Path
    name: str
    tracks: List[Path]


# ── helpers ──────────────────────────────────────────────────────────
def _strip_prefix(line: str) -> str:
    lower = line.lower()
    for pre in URI_PREFIXES:
        if lower.startswith(pre):
            return line[len(pre):]
    return line


def _parse_line(line: str, base_dir: Path) -> Path | None:
    """
    Convert one playlist line into an absolute Path.

    • Ignores comments / blank lines.
    • Percent-decodes.
    • Resolves relative paths against *base_dir*.
    """
    raw = line.lstrip("\ufeff").strip()
    if not raw or raw.startswith("#"):
        return None

    rest = _strip_prefix(raw)
    rest = unquote(rest)                  # %20 -> space, etc.
    rest = rest.replace("/", "\\")        # Windows separators

    pw = PureWindowsPath(rest)
    if not pw.drive:                      # relative -> prepend base dir
        pw = PureWindowsPath(base_dir / pw)

    return Path(pw)


def _read_playlist(pl_path: Path) -> List[Path]:
    """Return decoded/absolute track list for a single playlist file."""
    try:
        text = pl_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = pl_path.read_text(encoding="latin-1")

    base_dir = pl_path.parent
    tracks: List[Path] = []
    for ln in text.splitlines():
        p = _parse_line(ln, base_dir)
        if p:
            tracks.append(p)
    return tracks


# ── public API ───────────────────────────────────────────────────────
def scan_playlists(root: Path, recursive: bool = True) -> List[Playlist]:
    """
    Scan *root* for playlists; returns List[Playlist] with absolute tracks.
    """
    if not root.exists():
        return []

    walker = root.rglob if recursive else root.glob
    out: List[Playlist] = []
    for p in walker("*"):
        if p.suffix.lower() in PLAYLIST_EXTS and p.is_file():
            tracks = _read_playlist(p)
            out.append(Playlist(path=p,
                                name=p.stem,
                                tracks=tracks))
    return out
