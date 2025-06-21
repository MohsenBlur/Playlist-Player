#!/usr/bin/env python3
# scanner.py – rev-s8  (2025-06-28)
"""
Playlist discovery & parsing.

• Supports .m3u / .m3u8 / .fplite
• Reads Foobar2000 **index.txt** for friendly names
  ─ rev-s8 widens the parser:  ‘GUID  <spaces|tabs|colon>  Title’
• Fixes FLAC paths that start “/s:/...” after stripping file://

Public API
──────────
scan_playlists(root: Path, recursive=True) → list[Playlist]
"""

from __future__ import annotations
import re, urllib.parse
from pathlib import Path
from typing  import List, Dict, Iterable

PLAYLIST_EXTS = {".m3u", ".m3u8", ".fplite"}

# ───── simple data class ───────────────────────────────────────────
class Playlist:
    def __init__(self, *, path: Path, name: str, tracks: List[Path]):
        self.path   = path
        self.name   = name
        self.tracks = tracks
    def __repr__(self): return f"<Playlist {self.name!r} ({len(self.tracks)} tracks)>"

# ───── Foobar2000 index.txt cache ─────────────────────────────────
_index_cache: Dict[Path, Dict[str, str]] = {}

def _norm_guid(s: str) -> str:
    s = s.strip()
    if s.lower().startswith("playlist-"):
        s = s[9:]
    return s.upper()

def _load_index(folder: Path) -> Dict[str, str]:
    """Return {GUID: Title} for a folder, cached."""
    if folder in _index_cache:
        return _index_cache[folder]

    mapping: Dict[str, str] = {}
    idx = folder / "index.txt"
    if idx.is_file():
        try:
            text = idx.read_text(encoding="utf-8-sig", errors="replace")
            for ln in text.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                # Split by first colon *or* first run of whitespace
                if ":" in ln:
                    guid, title = ln.split(":", 1)
                else:
                    parts = ln.split(None, 1)
                    if len(parts) != 2:
                        continue
                    guid, title = parts
                guid  = _norm_guid(guid)
                title = title.strip()
                if title:
                    mapping[guid] = title
        except Exception:
            pass
    _index_cache[folder] = mapping
    return mapping

# ───── parsing helpers ────────────────────────────────────────────
URI_PREFIXES = ("file:///", "file://", "file:\\\\", "file:\\")
WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")

def _strip_uri_prefix(s: str) -> str:
    lo = s.lower()
    for pre in URI_PREFIXES:
        if lo.startswith(pre):
            return s[len(pre):]
    return s

def _percent_decode(s: str) -> str:
    try:
        return urllib.parse.unquote(s)
    except Exception:
        return re.sub(r"%([0-9A-Fa-f]{2})",
                      lambda m: bytes.fromhex(m.group(1)).decode("latin-1"),
                      s)

def _normalise(line: str) -> Path | None:
    line = line.lstrip("\ufeff").strip()
    if not line or line.startswith("#"):
        return None
    line = _strip_uri_prefix(line)
    line = _percent_decode(line)
    # drop single leading slash for drive-paths  /s:/Music/…
    if WIN_DRIVE_RE.match(line.lstrip("/")):
        line = line.lstrip("/")
    if WIN_DRIVE_RE.match(line):
        line = line.replace("/", "\\")
    return Path(line)

# ───── playlist readers ───────────────────────────────────────────
def _read_m3u(p: Path) -> List[Path]:
    text = p.read_text(encoding="utf-8", errors="replace")
    return [q for ln in text.splitlines() if (q := _normalise(ln))]

def _read_fplite(p: Path) -> List[Path]:
    data = p.read_bytes()
    try:  text = data.decode("utf-8-sig", errors="replace")
    except UnicodeDecodeError:
        text = data.decode("utf-16",    errors="replace")
    text = text.replace("\x00", "\n")
    return [q for ln in text.splitlines() if (q := _normalise(ln))]

def _read_playlist(p: Path) -> List[Path]:
    ext = p.suffix.lower()
    if ext in {".m3u", ".m3u8"}: return _read_m3u(p)
    if ext == ".fplite":         return _read_fplite(p)
    return []

# ───── scan public API ────────────────────────────────────────────
def scan_playlists(root: Path, recursive: bool = True) -> List[Playlist]:
    """Return list of Playlist objects under *root* (file or folder)."""
    if root.is_file() and root.suffix.lower() in PLAYLIST_EXTS:
        walker: Iterable[Path] = [root]
    elif recursive:
        walker = (p for p in root.rglob("*") if p.suffix.lower() in PLAYLIST_EXTS)
    else:
        walker = (p for p in root.iterdir()  if p.suffix.lower() in PLAYLIST_EXTS)

    playlists: List[Playlist] = []
    for p in walker:
        tracks = []
        try: tracks = _read_playlist(p)
        except Exception: continue
        if not tracks:  continue

        name = p.stem
        if p.suffix.lower() == ".fplite":
            idx = _load_index(p.parent)
            name = idx.get(_norm_guid(p.stem), name)

        playlists.append(Playlist(path=p, name=name, tracks=tracks))
    return playlists
