#!/usr/bin/env python3
# scanner.py – rev-s6  (2025-06-26)
"""
Playlist discovery & parsing.

• Supports .m3u / .m3u8 / .fplite
• Reads Foobar2000 **index.txt** in each folder that has .fplite files.
  ── Handles both forms:
       004F122F-646A-… : My Mix
       playlist-004F122F-646A-… : My Mix
"""

from __future__ import annotations
import re
from pathlib import Path
from typing  import List, Dict, Iterable

PLAYLIST_EXTS = {".m3u", ".m3u8", ".fplite"}

# ──────────────────────────────────────────────────────────
#  Data class
# ──────────────────────────────────────────────────────────
class Playlist:
    def __init__(self, *, path: Path, name: str, tracks: List[Path]):
        self.path   = path
        self.name   = name
        self.tracks = tracks
    def __repr__(self):
        return f"<Playlist {self.name!r} ({len(self.tracks)} tracks)>"

# ──────────────────────────────────────────────────────────
#  Foobar index.txt  (GUID → title)   – with caching
# ──────────────────────────────────────────────────────────
_index_cache: Dict[Path, Dict[str, str]] = {}

def _norm_guid(s: str) -> str:
    """Normalize GUID key: strip ‘playlist-’ prefix, upper-case."""
    s = s.strip()
    if s.lower().startswith("playlist-"):
        s = s[9:]
    return s.upper()

def _load_index(folder: Path) -> Dict[str, str]:
    if folder in _index_cache:
        return _index_cache[folder]

    mapping: Dict[str, str] = {}
    idx = folder / "index.txt"
    if idx.is_file():
        try:
            text = idx.read_text(encoding="utf-8-sig", errors="replace")
            for line in text.splitlines():
                if ":" not in line:
                    continue
                guid, title = line.split(":", 1)
                key_full  = _norm_guid(guid)               # stripped/upper
                key_raw   = guid.strip().upper()           # original
                for k in (key_full, key_raw):
                    mapping[k] = title.strip()
        except Exception:
            pass
    _index_cache[folder] = mapping
    return mapping

# ──────────────────────────────────────────────────────────
#  Parsing helpers
# ──────────────────────────────────────────────────────────
URI_PREFIXES = ("file://", "file:\\\\", "file:\\")
WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")

def _strip_prefix(line: str) -> str:
    for pre in URI_PREFIXES:
        if line.lower().startswith(pre):
            return line[len(pre):]
    return line

def _normalise(line: str) -> Path | None:
    line = line.strip().lstrip("\ufeff")
    if not line or line.startswith("#"):
        return None
    line = _strip_prefix(line)

    # percent-decode
    try:
        line = re.sub(r"%([0-9A-Fa-f]{2})",
                      lambda m: bytes.fromhex(m.group(1)).decode("utf-8"),
                      line)
    except Exception:
        pass
    if WIN_DRIVE_RE.match(line):
        line = line.replace("/", "\\")
    return Path(line)

# ──────────────────────────────────────────────────────────
#  Readers
# ──────────────────────────────────────────────────────────
def _read_m3u(path: Path) -> List[Path]:
    tracks = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        p = _normalise(ln)
        if p:
            tracks.append(p)
    return tracks

def _read_fplite(path: Path) -> List[Path]:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig", errors="replace")
    except UnicodeDecodeError:
        text = data.decode("utf-16",    errors="replace")
    text = text.replace("\x00", "\n")   # some files are NUL-separated
    tracks = []
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
    """Return Playlist objects for all supported playlist files under *root*."""
    walker: Iterable[Path] = (
        (p for p in root.rglob("*") if p.suffix.lower() in PLAYLIST_EXTS)
        if recursive else
        (p for p in root.iterdir() if p.suffix.lower() in PLAYLIST_EXTS)
    )

    playlists: List[Playlist] = []
    for p in walker:
        try:
            tracks = _read_playlist(p)
        except Exception:
            continue
        if not tracks:
            continue

        name = p.stem
        if p.suffix.lower() == ".fplite":
            idx_map = _load_index(p.parent)
            guid_key = _norm_guid(p.stem)
            name = idx_map.get(guid_key, name)

        playlists.append(Playlist(path=p, name=name, tracks=tracks))
    return playlists
