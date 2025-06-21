#!/usr/bin/env python3
# player.py – rev-k  (2025-06-29)
"""
Gap-less VLC wrapper for Playlist-Player.

• Debounced history writes (5 s) via background thread
• Output switcher: default / DirectSound / WASAPI (shared & exclusive)
• NEW in rev-k
  – End-of-track callback now dispatches `next_track()` through Tk
    `after(0, …)` → no freeze when one track ends.
"""

from __future__ import annotations
import time, threading
from pathlib import Path
from typing  import List, Set, Callable, Dict

import vlc
import tkinter as tk
import history

# ── helper to run GUI work on the Tk main loop ───────────────
def _tk_dispatch(fn: Callable[[], None]):
    root = tk._default_root
    if root and root.winfo_exists():
        root.after(0, fn)
    else:
        fn()

# ── VLC audio-output command lines ───────────────────────────
AOUT_OPTS: dict[str, list[str]] = {
    "default"         : [],
    "directsound"     : ["--aout=directsound"],
    "wasapi_shared"   : ["--aout=wasapi"],
    "wasapi_exclusive": ["--aout=wasapi", "--wasapi-exclusive-mode"],
}

class VLCGaplessPlayer:
    WRITE_INTERVAL = 5.0   # seconds between auto-flushes

    def __init__(self, on_track_change: Callable[[], None]):
        self._aout_mode = "default"
        self._instance  = vlc.Instance(["--no-video", "--quiet"])
        self._cb        = on_track_change

        self.playlist: List[Path] = []
        self.idx       = 0
        self._pl_path: Path | None = None
        self._finished: Set[str]   = set()
        self.player: vlc.MediaPlayer | None = None

        # history writer thread
        self._lock        = threading.Lock()
        self._pending: Dict | None = None
        self._last_write  = 0.0
        threading.Thread(target=self._writer_loop,
                         daemon=True).start()

    # ── output mode ──────────────────────────────────────────
    def _make_instance(self):
        self._instance = vlc.Instance(
            ["--no-video", "--quiet", *AOUT_OPTS[self._aout_mode]]
        )

    def set_output(self, mode: str):
        if mode == self._aout_mode or mode not in AOUT_OPTS:
            return
        cur_pl, cur_idx = self.playlist, self.idx
        cur_pos         = self.position()
        self.stop()
        self._aout_mode = mode
        self._make_instance()

        if cur_pl:
            self.load_playlist(self._pl_path, cur_pl)
            self.idx = min(cur_idx, len(cur_pl) - 1)
            self.seek(cur_pos)

    # ── playlist handling ───────────────────────────────────
    def load_playlist(self, pl_path: Path, tracks: List[Path]):
        self.flush_history()
        self._pl_path  = pl_path
        self.playlist  = tracks
        hist           = history.load(pl_path)
        self.idx       = min(hist.get("track_index", 0), len(tracks) - 1)
        resume         = float(hist.get("position", 0))
        self._finished = set(hist.get("finished", []))
        self._set_media(self.playlist[self.idx], resume=resume)
        _tk_dispatch(self._cb)

    # ── internal: create & start VLC media-player ───────────
    def _set_media(self, path: Path, *, resume: float = 0.0):
        if self.player:
            self.player.stop()

        media = self._instance.media_new(str(path))
        if resume > 0:
            media.add_option(f"start-time={resume}")

        self.player = self._instance.media_player_new()
        self.player.set_media(media)
        self.player.play()

        # attach *after* play(), else first track may fire instantly
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached,
            lambda *_: _tk_dispatch(self.next_track)  # ← the fix
        )

        self._mark_dirty(force=True)  # immediate write on change

    # ── public controls ─────────────────────────────────────
    def play(self):  self.player and self.player.play()
    def pause(self):
        if self.player: self.player.pause(); self._mark_dirty(force=True)
    def stop(self):  self.player and self.player.stop()

    def next_track(self):
        self._mark_finished()
        if self.idx + 1 < len(self.playlist):
            self.idx += 1
            self._set_media(self.playlist[self.idx])
            _tk_dispatch(self._cb)

    def prev_track(self):
        if self.position() > 5:
            self.seek(0); return
        if self.idx > 0:
            self.idx -= 1
            self._set_media(self.playlist[self.idx])
            _tk_dispatch(self._cb)

    # ── position helpers ────────────────────────────────────
    def length(self)   -> float: return (self.player.get_length() or 0)/1000 if self.player else 0.0
    def position(self) -> float: return (self.player.get_time()   or 0)/1000 if self.player else 0.0
    def seek(self, sec: float):
        if self.player:
            self.player.set_time(int(sec * 1000))
            self._mark_dirty(force=True)

    # ── finished marker ─────────────────────────────────────
    def _mark_finished(self):
        if self._pl_path and self.playlist:
            self._finished.add(str(self.playlist[self.idx]))

    # ── debounced history writer ────────────────────────────
    def _snapshot(self) -> Dict:
        return {
            "pl_path":     self._pl_path,
            "track_index": self.idx,
            "position":    self.position(),
            "finished":    set(self._finished),
        }

    def _mark_dirty(self, *, force=False):
        with self._lock:
            self._pending = self._snapshot()
            if force: self._last_write = 0.0

    def _writer_loop(self):
        while True:
            time.sleep(0.5)
            with self._lock:
                snap = None
                if self._pending and time.monotonic() - self._last_write >= self.WRITE_INTERVAL:
                    snap, self._pending = self._pending, None
                    self._last_write = time.monotonic()
            if snap:
                history.save(snap["pl_path"],
                             snap["track_index"],
                             snap["position"],
                             snap["finished"])

    def flush_history(self):
        with self._lock:
            snap = self._snapshot() if self._pl_path else None
            self._pending = None
        if snap:
            history.save(snap["pl_path"],
                         snap["track_index"],
                         snap["position"],
                         snap["finished"])

    # ── GUI tick (call every 100 ms) ────────────────────────
    def tick(self):
        if self.player and self._pl_path:
            self._mark_dirty()  # schedule debounced write
