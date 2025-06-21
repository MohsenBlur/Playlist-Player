#!/usr/bin/env python3
# main.py – rev-asynccover-full  (2025-06-30)
"""
Playlist-Player
───────────────
Gap-less playlist player for Windows (Tkinter + python-vlc).

Key features
• Scan / rename / delete playlists (.m3u, .m3u8, .fplite + index.txt)
• Gap-less playback with DirectSound / WASAPI selector
• Resume history written every 5 s (or on key events) → *.history.json
• Friendly *display_name* stored in history.json
• Embedded cover-art, timeline seek (click / drag / wheel; Ctrl = fine)
• Async cover/artwork loading to avoid freezes at track boundaries
"""

from __future__ import annotations
import sys, os, venv, site, subprocess, hashlib, io, concurrent.futures
from pathlib import Path
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageFile
import scanner, storage, player, history

# allow large embedded images
ImageFile.LOAD_TRUNCATED_IMAGES = True

# ─────────────────── 0. Bootstrap local venv ───────────────────
APP_DIR  = Path(__file__).parent
VENV_DIR = APP_DIR / ".venv"
PYSIDE_REQ = "PySide6>=6.9.0" if sys.version_info >= (3,13) else "PySide6>=6.7,<6.8"
REQS = [PYSIDE_REQ, "python-vlc", "mutagen", "pillow"]

def _ensure_env() -> None:
    if getattr(sys, "frozen", False):
        return
    if not VENV_DIR.exists():
        venv.create(VENV_DIR, with_pip=True)
        subprocess.check_call([
            str(VENV_DIR / ("Scripts" if os.name=="nt" else "bin") / "pip"),
            "install", *REQS, "--quiet"
        ])
    # add venv site-packages
    sp = (VENV_DIR/"Lib/site-packages") if os.name=="nt" else \
         next((VENV_DIR/"lib").glob("python*/site-packages"))
    site.addsitedir(str(sp))
    os.environ["PATH"] = f"{VENV_DIR/('Scripts' if os.name=='nt' else 'bin')}{os.pathsep}{os.environ.get('PATH','')}"

_ensure_env()

# ─────────────────── imports ────────────────────────────────
import mutagen
from mutagen.id3 import ID3
import player as pl_module

# ─────────────────── constants ──────────────────────────────
APPSTATE_FILE = storage.STATE_FILE
SUPPORTED = scanner.PLAYLIST_EXTS

# ─────────────────── async cover loader ────────────────────
EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1)

class CoverLoader:
    def __init__(self, on_ready):
        self._future: concurrent.futures.Future | None = None
        self._cb = on_ready

    def request(self, path: Path):
        # cancel any in-flight
        if self._future and not self._future.done():
            self._future.cancel()
        self._future = EXEC.submit(self._load, path)
        self._future.add_done_callback(self._done)

    def _done(self, fut: concurrent.futures.Future):
        img = None
        try:
            img = fut.result()
        except Exception:
            pass
        # marshal back to Tk main thread
        root = tk._default_root
        if root and root.winfo_exists():
            root.after(0, lambda: self._cb(img))
        else:
            self._cb(img)

    @staticmethod
    def _load(path: Path) -> Optional[Image.Image]:
        """Extract highest-res embedded artwork via mutagen."""
        try:
            audio = mutagen.File(path)
            if not getattr(audio, "tags", None):
                return None
            pics = []
            # ID3 APIC frames
            if isinstance(audio.tags, ID3):
                for ap in audio.tags.getall("APIC"):
                    pics.append((ap.data, ap.mime or "image/jpeg"))
            # MP4 pictures
            if getattr(audio, "pictures", None):
                for pic in audio.pictures:
                    pics.append((pic.data, pic.mime or "image/jpeg"))
            if not pics:
                return None
            # pick largest bytes
            data, mime = max(pics, key=lambda x: len(x[0]))
            img = Image.open(io.BytesIO(data))
            return img.copy()
        except Exception:
            return None

# ─────────────────── main GUI ────────────────────────────────
class MainWindow(tk.Tk):
    TICK_MS = 100

    def __init__(self):
        super().__init__()
        self.title("Playlist-Player")
        self.geometry("900x600")

        # Scan / playlist list / controls frame
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=8, pady=8)

        # left: playlist selector
        left = ttk.Frame(frm)
        left.pack(side="left", fill="y")
        ttk.Button(left, text="Scan Folder…", command=self.scan_folder).pack(fill="x")
        self.lst = tk.Listbox(left, height=30)
        self.lst.pack(fill="y", expand=True)
        self.lst.bind("<<ListboxSelect>>", lambda *_: self.on_select())
        self.plist: List[scanner.Playlist] = []

        # right: playback & metadata
        right = ttk.Frame(frm)
        right.pack(side="left", fill="both", expand=True, padx=8)

        # current track label
        self.lbl_current = ttk.Label(right, text="No track", font=("Segoe UI", 12))
        self.lbl_current.pack(anchor="w")

        # cover-art
        self.lbl_art = ttk.Label(right)
        self.lbl_art.pack(anchor="center", pady=8)

        # playback buttons
        btns = ttk.Frame(right)
        btns.pack()
        ttk.Button(btns, text="Prev", command=self.prev_track).pack(side="left", padx=4)
        ttk.Button(btns, text="Play", command=self.play_pause).pack(side="left", padx=4)
        ttk.Button(btns, text="Next", command=self.next_track).pack(side="left", padx=4)

        # timeline slider
        self.slider = ttk.Scale(right, from_=0, to=100, orient="horizontal", command=self.on_seek)
        self.slider.pack(fill="x", pady=8)
        self.slider.bind("<ButtonRelease-1>", lambda e: self.on_seek_release())

        # audio output selector
        opts = ["default","directsound","wasapi_shared","wasapi_exclusive"]
        self.cmb = ttk.Combobox(right, values=opts, state="readonly")
        self.cmb.current(0)
        self.cmb.pack()
        self.cmb.bind("<<ComboboxSelected>>", lambda *_: self.change_output())

        # internal
        self.player = pl_module.VLCGaplessPlayer(self._on_track_change)
        self.cover  = CoverLoader(self._set_cover)
        self._playing = False

        # start tick
        self.after(self.TICK_MS, self._tick)

    # ── scan folder ────────────────────────────────────────────
    def scan_folder(self):
        d = filedialog.askdirectory(title="Select folder")
        if not d:
            return
        found = scanner.scan_playlists(Path(d), recursive=True)
        self.plist = found
        self.lst.delete(0, "end")
        for pl in found:
            self.lst.insert("end", pl.name)

    # ── playlist selection ─────────────────────────────────────
    def on_select(self):
        idxs = self.lst.curselection()
        if not idxs:
            return
        idx = idxs[0]
        pl = self.plist[idx]
        self.player.load_playlist(pl.path, pl.tracks)
        self._on_track_change()

    # ── playback controls ─────────────────────────────────────
    def play_pause(self):
        if self._playing:
            self.player.pause(); self._playing = False
        else:
            self.player.play();  self._playing = True

    def next_track(self):
        self.player.next_track(); self._playing = True

    def prev_track(self):
        self.player.prev_track(); self._playing = True

    def change_output(self):
        self.player.set_output(self.cmb.get())

    # ── slider / seek ─────────────────────────────────────────
    def on_seek(self, val):
        # live dragging: don't seek until release
        pass

    def on_seek_release(self):
        pos = self.slider.get() / 100.0 * self.player.length()
        self.player.seek(pos)

    # ── cover / meta callback ──────────────────────────────────
    def _on_track_change(self):
        path = self.player.playlist[self.player.idx]
        self.lbl_current.config(text=path.name)
        # request async cover load
        self.cover.request(path)

    def _set_cover(self, img: Optional[Image.Image]):
        if img is None:
            self.lbl_art.config(image=""); return
        img.thumbnail((256,256), Image.Resampling.LANCZOS)
        self._tkimg = tk.PhotoImage(img)
        self.lbl_art.config(image=self._tkimg)

    # ── periodic tick ─────────────────────────────────────────
    def _tick(self):
        # update slider position
        length = self.player.length()
        if length > 0:
            pos = self.player.position()
            self.slider.config(to=length)
            self.slider.set(pos)
        self.player.tick()
        self.after(self.TICK_MS, self._tick)

# ─────────────────── launcher ────────────────────────────────────
def main():
    app = MainWindow()
    app.mainloop()
    EXEC.shutdown(wait=False)

if __name__ == "__main__":
    main()
