#!/usr/bin/env python3
# player.py – rev-ℓ2  (2025-06-30)
"""
Gap-less VLC wrapper (freeze-free)

Change log
──────────
rev-ℓ2 • `MediaPlayer.play()` + resume-seek are now executed via
          `root.after_idle`, so the Tk main-thread is never blocked.
"""

from __future__ import annotations
import time, threading
from pathlib import Path
from typing  import Callable, Dict, List, Set

import vlc
import tkinter as tk
import history

# ───────────────── Tk helper ─────────────────
def _tk_dispatch(fn: Callable[[], None]):
    root = tk._default_root
    if root and root.winfo_exists():
        root.after(0, fn)
    else:
        fn()

def _tk_idle(fn: Callable[[], None]):
    root = tk._default_root
    if root and root.winfo_exists():
        root.after_idle(fn)
    else:
        fn()

# ───────────────── VLC presets ───────────────
AOUT_OPTS = {
    "default": [],
    "directsound": ["--aout=directsound"],
    "wasapi_shared": ["--aout=wasapi"],
    "wasapi_exclusive": ["--aout=wasapi", "--wasapi-exclusive-mode"],
}

END = vlc.EventType.MediaPlayerEndReached


class VLCGaplessPlayer:
    WRITE_INT = 5.0  # s

    def __init__(self, on_track_change: Callable[[], None]):
        self._cb = on_track_change
        self._mode = "default"
        self._make_instance()

        self.player: vlc.MediaPlayer | None = None
        self.playlist: List[Path] = []
        self.idx = 0
        self._pl_path: Path | None = None
        self._finished: Set[str] = set()

        # debounced writer
        self._lock = threading.Lock()
        self._pending: Dict | None = None
        self._last_write = 0.0
        threading.Thread(target=self._writer, daemon=True).start()

    # ── instance / output ─────────────────────
    def _make_instance(self):
        self._instance = vlc.Instance(
            ["--no-video", "--quiet", *AOUT_OPTS[self._mode]]
        )

    def set_output(self, mode: str):
        if mode == self._mode or mode not in AOUT_OPTS:
            return
        cur = (self.playlist, self.idx, self.position(), self._pl_path)
        self.stop()
        self._mode = mode
        self._make_instance()
        pl, idx, pos, plp = cur
        if pl:
            self.load_playlist(plp, pl)
            self.idx = min(idx, len(pl) - 1)
            self.seek(pos)

    # ── playlist load ─────────────────────────
    def load_playlist(self, pl_path: Path, tracks: List[Path]):
        self.flush_history()
        self._pl_path, self.playlist = pl_path, tracks

        hist = history.load(pl_path)
        self.idx = min(hist.get("track_index", 0), len(tracks) - 1)
        resume = float(hist.get("position", 0))
        self._finished = set(hist.get("finished", []))

        self._set_media(self.playlist[self.idx], resume)
        _tk_dispatch(self._cb)

    # ── media / gap-less core ─────────────────
    def _attach_end(self):
        self.player.event_manager().event_attach(
            END, lambda *_: _tk_dispatch(self.next_track))

    def _set_media(self, path: Path, resume: float = 0.0) -> bool:
        if not self.player:
            self.player = self._instance.media_player_new()
        else:
            try:
                self.player.event_manager().event_detach(END)
            except Exception:
                pass

        media = self._instance.media_new(str(path))
        self.player.set_media(media)
        self._attach_end()

        def _start():
            if self.player.play() == -1:
                return False
            if resume:
                self.player.set_time(int(resume * 1000))
            self._mark_dirty(force=True)
            return True

        ok_box: list[bool] = []
        _tk_idle(lambda: ok_box.append(_start()))
        return ok_box and ok_box[0]

    # ── controls ──────────────────────────────
    def play(self):  _tk_idle(lambda: self.player and self.player.play())
    def pause(self):
        if self.player:
            self.player.pause()
            self._mark_dirty(force=True)

    def stop(self): self.player and self.player.stop()

    def next_track(self):
        self._mark_finished()
        while self.idx + 1 < len(self.playlist):
            self.idx += 1
            if self._set_media(self.playlist[self.idx]): break
            self._finished.add(str(self.playlist[self.idx]))
        else:
            self.stop()
        _tk_dispatch(self._cb)

    def prev_track(self):
        if self.position() > 5:
            self.seek(0); return
        if self.idx > 0:
            self.idx -= 1
            self._set_media(self.playlist[self.idx])
            _tk_dispatch(self._cb)

    # ── position helpers ──────────────────────
    def length(self)   -> float: return (self.player.get_length() or 0) / 1000 if self.player else 0.0
    def position(self) -> float: return (self.player.get_time()   or 0) / 1000 if self.player else 0.0
    def seek(self, s: float):
        if self.player:
            self.player.set_time(int(s * 1000))
            self._mark_dirty(force=True)

    # ── history mark / write thread ───────────
    def _mark_finished(self):
        if self._pl_path and self.playlist:
            self._finished.add(str(self.playlist[self.idx]))

    def _snap(self) -> Dict:
        return dict(pl_path=self._pl_path,
                    track_index=self.idx,
                    position=self.position(),
                    finished=set(self._finished))

    def _mark_dirty(self, *, force=False):
        with self._lock:
            self._pending = self._snap()
            if force:
                self._last_write = 0.0

    def _writer(self):
        while True:
            time.sleep(0.5)
            with self._lock:
                if not self._pending: continue
                if time.monotonic() - self._last_write < self.WRITE_INT:
                    continue
                snap, self._pending = self._pending, None
                self._last_write = time.monotonic()
            history.save(snap["pl_path"], snap["track_index"],
                         snap["position"], snap["finished"])

    def flush_history(self):
        with self._lock:
            snap = self._snap() if self._pl_path else None
            self._pending = None
        if snap:
            history.save(snap["pl_path"], snap["track_index"],
                         snap["position"], snap["finished"])

    # ── GUI timer tick (every 100 ms) ─────────
    def tick(self):
        if self.player and self._pl_path:
            self._mark_dirty()
