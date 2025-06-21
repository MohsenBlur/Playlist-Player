#!/usr/bin/env python3
# player.py – rev-e5  (2025-06-26)
"""
Gap-less VLC wrapper with debounced, atomic history writes.

* Writes progress to RAM every _tick()_ (100 ms)
* Background thread flushes to JSON once the data is unchanged ≥1 s
* flush_history() forces a synchronous write on app exit
"""

from __future__ import annotations
import time, threading
from pathlib import Path
from typing  import List, Set, Callable, Dict

import vlc
import history

# ── audio output CLI options ───────────────────────────────────────────
AOUT_OPTS: dict[str, list[str]] = {
    "default"         : [],
    "directsound"     : ["--aout=directsound"],
    "wasapi_shared"   : ["--aout=wasapi"],
    "wasapi_exclusive": ["--aout=wasapi", "--wasapi-exclusivemode"],
}

class VLCGaplessPlayer:
    DEBOUNCE_SEC = 1.0

    def __init__(self, on_track_change: Callable[[], None]):
        self._aout_mode = "default"
        self._instance: vlc.Instance | None = None
        self._make_instance()

        self._cb = on_track_change

        self.playlist: List[Path] = []
        self.idx = 0
        self._pl_path: Path | None = None
        self._finished: Set[str] = set()
        self.player: vlc.MediaPlayer | None = None

        # debounced writer state
        self._dirty_lock = threading.Lock()
        self._dirty = False
        self._pending: Dict | None = None
        self._last_update = 0.0
        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()

    # ───────────────────────────────── VLC instance helpers
    def _make_instance(self):
        self._instance = vlc.Instance(
            ["--no-video", "--quiet", *AOUT_OPTS[self._aout_mode]]
        )

    def set_output(self, mode: str):
        if mode == self._aout_mode or mode not in AOUT_OPTS:
            return
        mode_prev = self._aout_mode
        self._aout_mode = mode
        # preserve current playlist
        cur_pl, cur_tracks = self._pl_path, list(self.playlist)
        cur_idx, cur_pos = self.idx, self.position()
        self.stop()
        self._make_instance()
        if cur_pl:
            self.load_playlist(cur_pl, cur_tracks)
            self.idx = min(cur_idx, max(0, len(self.playlist)-1))
            self.seek(cur_pos)
        else:
            self._aout_mode = mode_prev   # rollback if nothing loaded

    # ───────────────────────────────── playlist handling
    def load_playlist(self, pl_path: Path, tracks: List[Path]):
        self._pl_path = pl_path
        self.playlist = tracks

        hist = history.load(pl_path)
        self.idx       = min(hist.get("track_index", 0),
                             max(0, len(tracks)-1))
        position       = float(hist.get("position", 0))
        self._finished = set(hist.get("finished", []))

        self._set_media(self.playlist[self.idx], resume=position)
        self._cb()

    # ───────────────────────────────── media helpers
    def _attach_end_event(self):
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached,
            lambda *_: self.next_track()
        )

    def _set_media(self, path: Path, *, resume: float = 0.0):
        if self.player:
            self.player.stop()
        self.player = self._instance.media_player_new()
        self.player.set_media(self._instance.media_new(str(path)))
        self._attach_end_event()
        self.player.play()
        if resume:
            for _ in range(10):           # wait for length to be known
                if self.player.get_length() > 0: break
                time.sleep(0.05)
            self.player.set_time(int(resume * 1000))

    # ───────────────────────────────── controls
    def play(self):  self.player and self.player.play()
    def pause(self): self.player and self.player.pause()
    def stop(self):
        if self.player:
            self.player.stop(); self.player = None

    def next_track(self):
        self._mark_finished()
        if self.idx + 1 < len(self.playlist):
            self.idx += 1
            self._set_media(self.playlist[self.idx])
            self._cb()

    def prev_track(self):
        if self.idx > 0:
            self.idx -= 1
            self._set_media(self.playlist[self.idx])
            self._cb()

    # ───────────────────────────────── position helpers
    def length(self) -> float:
        return (self.player.get_length() or 0) / 1000 if self.player else 0.0
    def position(self) -> float:
        return (self.player.get_time()   or 0) / 1000 if self.player else 0.0
    def seek(self, s: float):
        self.player and self.player.set_time(int(s * 1000))

    # mark current file finished when moving past it
    def _mark_finished(self):
        if self._pl_path and self.playlist:
            self._finished.add(str(self.playlist[self.idx]))

    # ───────────────────────────────── debounced writer thread
    def _writer_loop(self):
        while True:
            time.sleep(0.25)
            with self._dirty_lock:
                if (self._dirty and
                        time.monotonic() - self._last_update >= self.DEBOUNCE_SEC
                        and self._pending):
                    data = self._pending
                    self._dirty = False
                else:
                    data = None
            if data:
                history.save(data["pl_path"],
                             data["track_index"],
                             data["position"],
                             data["finished"])

    # PUBLIC: synchronous flush for app exit
    def flush_history(self):
        with self._dirty_lock:
            data = self._pending
            self._dirty = False
        if data:
            history.save(data["pl_path"],
                         data["track_index"],
                         data["position"],
                         data["finished"])

    # ───────────────────────────────── tick (100 ms from GUI)
    def tick(self):
        if not (self.player and self._pl_path):
            return
        snapshot = {
            "pl_path":     self._pl_path,
            "track_index": self.idx,
            "position":    self.position(),
            "finished":    set(self._finished),
        }
        with self._dirty_lock:
            self._pending      = snapshot
            self._dirty        = True
            self._last_update  = time.monotonic()
