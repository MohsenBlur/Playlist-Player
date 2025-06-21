#!/usr/bin/env python3
# scanner.py – rev-s7  (2025-06-28)
"""
Playlist discovery & parsing.

• Supports .m3u / .m3u8 / .fplite
• Reads Foobar2000 **index.txt** for friendly names.
• NEW in s7 – Drops a lone leading “/” that remains after stripping
  file:// URIs (e.g. `/s:/Music/…` → `S:\Music\…`) so Windows can open
  the file and VLC plays FLAC tracks correctly.
"""

from __future__ import annotations
import re, urllib.parse
from pathlib import Path
from typing  import List, Dict, Iterable

PLAYLIST_EXTS = {".m3u", ".m3u8", ".fplite"}

# ────────────────────────── data class ────────────────────────────
class Playlist:
    def __init__(self, *, path: Path, name: str, tracks: List[Path]):
        self.path   = path
        self.name   = name
        self.tracks = tracks
    def __repr__(self):
        return f"<Playlist {self.name!r} ({len(self.tracks)} tracks)>"

# ───────────── Foobar2000 index.txt  (GUID → title) ───────────────-
_index_cache: Dict[Path, Dict[str, str]] = {}

def _norm_guid(s: str) -> str:
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
            for ln in text.splitlines():
                if ":" not in ln and "\t" not in ln:
                    continue
                guid, _, title = re.split(r"[:\t]", ln, maxsplit=1)
                key_full = _norm_guid(guid)
                key_raw  = guid.strip().upper()
                for k in (key_full, key_raw):
                    mapping[k] = title.strip()
        except Exception:
            pass
    _index_cache[folder] = mapping
    return mapping

# ───────────────────────── parsing helpers ─────────────────────────
URI_PREFIXES = ("file:///", "file://", "file:\\\\", "file:\\")  # longest first
WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")

def _strip_uri_prefix(line: str) -> str:
    lower = line.lower()
    for pre in URI_PREFIXES:
        if lower.startswith(pre):
            return line[len(pre):]
    return line

def _percent_decode(s: str) -> str:
    try:
        return urllib.parse.unquote(s)
    except Exception:
        # fallback: manual
        return re.sub(r"%([0-9A-Fa-f]{2})",
                      lambda m: bytes.fromhex(m.group(1)).decode("latin-1"),
                      s)

def _normalise(line: str) -> Path | None:
    line = line.strip().lstrip("\ufeff")          # strip BOM / spaces
    if not line or line.startswith("#"):
        return None

    line = _strip_uri_prefix(line)
    line = _percent_decode(line)

    # NEW s7: drop a single leading "/" when what follows is drive:\
    if WIN_DRIVE_RE.match(line.lstrip("/")):      # ← added
        line = line.lstrip("/")

    if WIN_DRIVE_RE.match(line):
        line = line.replace("/", "\\")

    return Path(line)

# ───────────────────────── readers ────────────────────────────────
def _read_m3u(path: Path) -> List[Path]:
    tracks: List[Path] = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        p = _normalise(ln)
        if p: tracks.append(p)
    return tracks

def _read_fplite(path: Path) -> List[Path]:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig", errors="replace")
    except UnicodeDecodeError:
        text = data.decode("utf-16", errors="replace")
    text = text.replace("\x00", "\n")     # some .fplite are NUL-separated
    tracks: List[Path] = []
    for ln in text.splitlines():
        p = _normalise(ln)
        if p: tracks.append(p)
    return tracks

def _read_playlist(path: Path) -> List[Path]:
    ext = path.suffix.lower()
    if ext in {".m3u", ".m3u8"}:
        return _read_m3u(path)
    if ext == ".fplite":
        return _read_fplite(path)
    return []

# ───────────────────────── public API ─────────────────────────────
def scan_playlists(root: Path, recursive: bool = True) -> List[Playlist]:
    """Return Playlist objects for all supported playlist files under *root*."""
    if root.is_file() and root.suffix.lower() in PLAYLIST_EXTS:
        walker: Iterable[Path] = [root]
    elif recursive:
        walker = (p for p in root.rglob("*") if p.suffix.lower() in PLAYLIST_EXTS)
    else:
        walker = (p for p in root.iterdir() if p.suffix.lower() in PLAYLIST_EXTS)

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
            name = idx_map.get(_norm_guid(p.stem), name)

        playlists.append(Playlist(path=p, name=name, tracks=tracks))
    return playlists
