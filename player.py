#!/usr/bin/env python3
# player.py – rev-e3  (2025-06-23)
"""
Gap-less VLC wrapper for Playlist-Relinker.

Fixes
─────
• Stops an existing MediaPlayer before creating the next one
  → prevents multiple tracks playing simultaneously (Prev/Next bug).
• Audio-output table now exposes a working WASAPI *exclusive* mode:
      shared  → ["--aout=wasapi"]
      exclusive → ["--aout=wasapi", "--wasapi-exclusivemode"]
• Robust re-creation of the vlc.Instance when output mode changes.
• History is written every tick with the expected arguments.
"""

from __future__ import annotations
import time
from pathlib import Path
from typing import List, Set, Callable

import vlc
import history

# ── audio backend CLI options ────────────────────────────────────
AOUT_OPTS: dict[str, list[str]] = {
    "default":         [],
    "directsound":     ["--aout=directsound"],
    "wasapi_shared":   ["--aout=wasapi"],
    "wasapi_exclusive":["--aout=wasapi", "--wasapi-exclusivemode"],
}

# ── main class ───────────────────────────────────────────────────
class VLCGaplessPlayer:
    def __init__(self, on_track_change: Callable[[], None]):
        self._aout_mode: str = "default"
        self._instance: vlc.Instance | None = None
        self._make_instance()

        self.playlist: List[Path] = []
        self.idx: int = 0
        self._finished: Set[str] = set()

        self.player: vlc.MediaPlayer | None = None
        self._pl_path: Path | None = None
        self._cb = on_track_change

    # ── instance helpers ─────────────────────────────────────────
    def _make_instance(self):
        self._instance = vlc.Instance(
            ["--no-video", "--quiet", *AOUT_OPTS[self._aout_mode]]
        )

    def set_output(self, mode: str):
        """Switch audio back-end and recreate VLC instance."""
        if mode == self._aout_mode or mode not in AOUT_OPTS:
            return
        self._aout_mode = mode

        # snapshot current state
        cur_pl, cur_tracks = self._pl_path, list(self.playlist)
        cur_idx, cur_pos   = self.idx, self.position()

        # stop & rebuild
        self.stop()
        self._make_instance()

        # restore state
        if cur_pl:
            self.load_playlist(cur_pl, cur_tracks)
            self.idx = min(cur_idx, max(0, len(self.playlist) - 1))
            self.seek(cur_pos)

    # ── media helpers ────────────────────────────────────────────
    def _attach_end_event(self):
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached,
            lambda *_: self.next_track()
        )

    def _set_media(self, path: Path, *, resume: float = 0.0):
        # make sure previous player stops first
        if self.player:
            self.player.stop()
        self.player = self._instance.media_player_new()
        media = self._instance.media_new(str(path))
        self.player.set_media(media)
        self._attach_end_event()
        self.player.play()

        if resume:
            # wait a short moment so VLC has length information
            for _ in range(10):
                if self.player.get_length() > 0:
                    break
                time.sleep(0.05)
            self.player.set_time(int(resume * 1000))

    # ── public API ───────────────────────────────────────────────
    def load_playlist(self, pl_path: Path, tracks: List[Path]):
        self._pl_path = pl_path
        self.playlist = tracks

        hist = history.load(pl_path)
        self.idx = min(hist.get("track_index", 0), max(0, len(tracks) - 1))
        position = float(hist.get("position", 0))
        self._finished = set(hist.get("finished", []))

        self._set_media(self.playlist[self.idx], resume=position)
        self._cb()

    # basic controls
    def play(self):    self.player and self.player.play()
    def pause(self):   self.player and self.player.pause()
    def stop(self):
        if self.player:
            self.player.stop()
            self.player = None

    # navigation
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

    # timing
    def length(self) -> float:
        return (self.player.get_length() or 0) / 1000 if self.player else 0.0

    def position(self) -> float:
        return (self.player.get_time() or 0) / 1000 if self.player else 0.0

    def seek(self, seconds: float):
        if self.player:
            self.player.set_time(int(seconds * 1000))

    # history
    def _mark_finished(self):
        if self._pl_path and self.playlist:
            self._finished.add(str(self.playlist[self.idx]))

    def tick(self):
        """Call from GUI every 100 ms."""
        if not self.player or not self._pl_path:
            return
        history.save(
            self._pl_path,
            self.idx,
            self.position(),
            self._finished,
        )
