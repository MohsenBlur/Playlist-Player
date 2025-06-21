#!/usr/bin/env python3
# scanner.py – rev-s5  (2025-06-25)
"""
Playlist discovery & parsing.

* Supports `.m3u`, `.m3u8`, `.fplite`
* For each folder that contains `.fplite`, an accompanying **index.txt**
  (Foobar2000 format) is parsed; playlist names come from that file.

index.txt format (UTF-8-SIG) example
------------------------------------
004F122F-646A-… : Bowie
7C86121D-75A5-… : Audio
"""

from __future__ import annotations
import re, sys, base64
from pathlib import Path
from typing  import List, Dict, Iterable

PLAYLIST_EXTS = {".m3u", ".m3u8", ".fplite"}

# ──────────────────────────────────────────────────────────
#  Data class
# ──────────────────────────────────────────────────────────
class Playlist:
    def __init__(self, *, path: Path,
                 name: str,
                 tracks: List[Path]) -> None:
        self.path   = path
        self.name   = name
        self.tracks = tracks

    def __repr__(self):
        return f"<Playlist {self.name!r} ({len(self.tracks)} tracks)>"

# ──────────────────────────────────────────────────────────
#  Helper: read Foobar index.txt   GUID:Name
# ──────────────────────────────────────────────────────────
_index_cache: Dict[Path, Dict[str, str]] = {}

def _load_index(folder: Path) -> Dict[str, str]:
    if folder in _index_cache:
        return _index_cache[folder]
    mapping: Dict[str, str] = {}
    idx = folder / "index.txt"
    if idx.exists():
        try:
            text = idx.read_text(encoding="utf-8-sig", errors="replace")
            for line in text.splitlines():
                if ":" in line:
                    guid, name = line.split(":", 1)
                    mapping[guid.strip().upper()] = name.strip()
        except Exception:
            pass
    _index_cache[folder] = mapping
    return mapping

# ──────────────────────────────────────────────────────────
#  Parser helpers
# ──────────────────────────────────────────────────────────
URI_PREFIXES = ("file://", "file:\\\\", "file:\\")
WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")

def _strip_prefix(line: str) -> str:
    for pre in URI_PREFIXES:
        if line.lower().startswith(pre):
            return line[len(pre):]
    return line

def _normalise(line: str) -> Path | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    line = _strip_prefix(line)
    # unescape %20 etc.
    try:
        line = bytes(line, "utf-8").decode("utf-8")
        line = re.sub(r"%([0-9A-Fa-f]{2})",
                      lambda m: bytes.fromhex(m.group(1)).decode("utf-8"),
                      line)
    except Exception:
        pass
    # fix slashes
    if WIN_DRIVE_RE.match(line):
        line = line.replace("/", "\\")
    return Path(line)

# ──────────────────────────────────────────────────────────
#  Reading individual playlist files
# ──────────────────────────────────────────────────────────
def _read_m3u(path: Path) -> List[Path]:
    tracks: List[Path] = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        p = _normalise(ln)
        if p:
            tracks.append(p)
    return tracks

def _read_fplite(path: Path) -> List[Path]:
    # Foobar2000 stores plain-text URI list (may be LF or CRLF)
    data = path.read_bytes()
    # heuristic: UTF-8 BOM?
    try:
        text = data.decode("utf-8-sig", errors="replace")
    except UnicodeDecodeError:
        text = data.decode("utf-16", errors="replace")
    # some .fplite collapse into a single long line separated by \x00
    text = text.replace("\x00", "\n")
    tracks: List[Path] = []
    for ln in text.splitlines():
        p = _normalise(ln)
        if p:
            tracks.append(p)
    return tracks

def _read_playlist(path: Path) -> List[Path]:
    ext = path.suffix.lower()
    if ext in {".m3u", ".m3u8"}:
        return _read_m3u(path)
    if ext == ".fplite":
        return _read_fplite(path)
    return []

# ──────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────
def scan_playlists(root: Path, recursive: bool = True) -> List[Playlist]:
    """
    Return Playlist objects for all supported playlist files found under
    *root*. For `.fplite`, the optional Foobar `index.txt` in the same
    folder is used to obtain the display name.
    """
    paths: Iterable[Path]
    if recursive:
        paths = (p for p in root.rglob("*") if p.suffix.lower() in PLAYLIST_EXTS)
    else:
        paths = (p for p in root.iterdir() if p.suffix.lower() in PLAYLIST_EXTS)

    playlists: List[Playlist] = []
    for p in paths:
        try:
            tracks = _read_playlist(p)
        except Exception:
            continue
        if not tracks:
            continue

        name = p.stem
        if p.suffix.lower() == ".fplite":
            idx_map = _load_index(p.parent)
            name = idx_map.get(p.stem.upper(), name)

        playlists.append(Playlist(path=p, name=name, tracks=tracks))
    return playlists
