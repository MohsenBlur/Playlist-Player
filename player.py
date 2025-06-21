#!/usr/bin/env python3
# player.py – rev-ℓ  (2025-06-30)
"""
VLCGaplessPlayer
────────────────
Single-`MediaPlayer`, gap-less playlist playback for Playlist-Player.

Fix for “freeze at track end”
─────────────────────────────
* **EndReached** now only schedules `next_track()` on Tk’s main thread
  (unchanged from rev-k) **and** `next_track()` no longer calls
  `MediaPlayer.stop()`.  
  Re-using the same player eliminates the VLC dead-lock that occurred
  when `stop()` was issued while libVLC was still unwinding callbacks.
* If `play()` returns -1 (file missing / Unicode issue), that track is
  skipped automatically; the loop advances until a playable file is
  found or the playlist ends.

History debounce, output switcher, cover-art callback — unchanged.
"""

from __future__ import annotations
import time, threading
from pathlib import Path
from typing    import List, Set, Callable, Dict

import vlc
import tkinter as tk
import history

# ────────────────── helper: dispatch on Tk thread ──────────
def _tk_dispatch(fn: Callable[[], None]):
    root = tk._default_root
    if root and root.winfo_exists():
        root.after(0, fn)
    else:
        fn()

# ────────────────── VLC audio output presets ───────────────
AOUT_OPTS: dict[str, list[str]] = {
    "default"         : [],
    "directsound"     : ["--aout=directsound"],
    "wasapi_shared"   : ["--aout=wasapi"],
    "wasapi_exclusive": ["--aout=wasapi", "--wasapi-exclusive-mode"],
}

END = vlc.EventType.MediaPlayerEndReached   # shorthand


class VLCGaplessPlayer:
    WRITE_INTERVAL = 5.0  # seconds between debounced history writes

    def __init__(self, on_track_change: Callable[[], None]):
        self._aout_mode = "default"
        self._instance  = vlc.Instance(["--no-video", "--quiet"])
        self._cb        = on_track_change

        # runtime
        self.player: vlc.MediaPlayer | None = None
        self.playlist: List[Path] = []
        self.idx  = 0
        self._pl_path: Path | None = None
        self._finished: Set[str] = set()

        # history writer state
        self._lock = threading.Lock()
        self._pending: Dict | None = None
        self._last_write = 0.0
        threading.Thread(target=self._writer_loop, daemon=True).start()

    # ── output mode / VLC instance ──────────────────────────
    def _make_instance(self):
        self._instance = vlc.Instance(
            ["--no-video", "--quiet", *AOUT_OPTS[self._aout_mode]]
        )

    def set_output(self, mode: str):
        if mode == self._aout_mode or mode not in AOUT_OPTS:
            return
        cur_pl, cur_idx, cur_pos = self.playlist, self.idx, self.position()
        self.stop()                       # stop current audio
        self._aout_mode = mode
        self._make_instance()
        if cur_pl:
            self.load_playlist(self._pl_path, cur_pl)
            self.idx = min(cur_idx, len(cur_pl)-1)
            self.seek(cur_pos)

    # ── playlist load / resume ──────────────────────────────
    def load_playlist(self, pl_path: Path, tracks: List[Path]):
        self.flush_history()
        self._pl_path  = pl_path
        self.playlist  = tracks
        hist           = history.load(pl_path)
        self.idx       = min(hist.get("track_index", 0), len(tracks)-1)
        resume         = float(hist.get("position", 0))
        self._finished = set(hist.get("finished", []))
        self._set_media(self.playlist[self.idx], resume)
        _tk_dispatch(self._cb)

    # ── media switching (NO stop()) ─────────────────────────
    def _attach_end(self):
        self.player.event_manager().event_attach(END,
            lambda *_: _tk_dispatch(self.next_track))

    def _detach_end(self):
        try:
            self.player.event_manager().event_detach(END)
        except Exception:
            pass

    def _set_media(self, path: Path, resume: float = 0.0) -> bool:
        """
        Return True on success, False if VLC.play() failed (e.g. file
        missing / codec error).
        """
        if not self.player:
            self.player = self._instance.media_player_new()
        else:
            self._detach_end()

        media = self._instance.media_new(str(path))
        if resume > 0:
            media.add_option(f"start-time={resume}")
        self.player.set_media(media)
        self._attach_end()
        ok = self.player.play() != -1
        if ok:
            self._mark_dirty(force=True)
        return ok

    # ── public controls ─────────────────────────────────────
    def play(self):   self.player and self.player.play()
    def pause(self):
        if self.player: self.player.pause(); self._mark_dirty(force=True)
    def stop(self):   self.player and self.player.stop()

    def next_track(self):
        self._mark_finished()
        while self.idx + 1 < len(self.playlist):
            self.idx += 1
            if self._set_media(self.playlist[self.idx]):
                _tk_dispatch(self._cb)
                return
            # skip unplayable file, mark finished to avoid loop
            self._finished.add(str(self.playlist[self.idx]))
        # playlist ended
        self.stop()

    def prev_track(self):
        if self.position() > 5:
            self.seek(0); return
        if self.idx > 0:
            self.idx -= 1
            if self._set_media(self.playlist[self.idx]):
                _tk_dispatch(self._cb)

    # ── position helpers ────────────────────────────────────
    def length(self)   -> float: return (self.player.get_length() or 0)/1000 if self.player else 0.0
    def position(self) -> float: return (self.player.get_time()   or 0)/1000 if self.player else 0.0
    def seek(self, sec: float):
        if self.player:
            self.player.set_time(int(sec * 1000))
            self._mark_dirty(force=True)

    # ── mark finished track ─────────────────────────────────
    def _mark_finished(self):
        if self._pl_path and self.playlist:
            self._finished.add(str(self.playlist[self.idx]))

    # ── history: debounce / background write ────────────────
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
                if not self._pending:
                    continue
                if time.monotonic() - self._last_write < self.WRITE_INTERVAL:
                    continue
                snap, self._pending = self._pending, None
                self._last_write = time.monotonic()
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
            self._mark_dirty()   # schedule debounced write
