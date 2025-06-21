#!/usr/bin/env python3
# main.py – rev-w35  (2025-06-25)
"""
Playlist-Player GUI

• Tool-bar button **Create** lets you compose a new playlist:
  – choose audio files, optionally reorder, save as .m3u8  
  – the fresh playlist is scanned and appears immediately.
• Prev / Next now live at the right side of the top bar.
• Scroll-wheel seek on timeline (±5 s; hold Ctrl → ±1 s).
• Debounced, atomic history writes (from earlier revisions) retained.
"""

from __future__ import annotations
import sys, os, subprocess, venv, site, hashlib, io, json, tempfile
from pathlib import Path
from typing  import Dict, List, Optional, Tuple, Set

# ═══════════════════════════════════════════════════════════════════════
# local venv bootstrap (installs PySide6, python-vlc, mutagen, pillow)
# ═══════════════════════════════════════════════════════════════════════
APP_DIR  = Path(__file__).parent
VENV_DIR = APP_DIR / ".venv"
PYSIDE_REQ = "PySide6>=6.9.0" if sys.version_info >= (3, 13) \
             else "PySide6>=6.7,<6.8"
REQS = [PYSIDE_REQ, "python-vlc", "mutagen", "pillow"]

def _ensure_env() -> None:
    if getattr(sys, "frozen", False):     # PyInstaller build
        return
    if not VENV_DIR.exists():
        venv.create(VENV_DIR, with_pip=True)
        subprocess.check_call([
            VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / "pip",
            "install", *REQS, "--quiet"
        ])
    sp = (VENV_DIR / "Lib/site-packages") if os.name == "nt" else \
         next((VENV_DIR / "lib").glob("python*/site-packages"))
    site.addsitedir(sp)
    os.environ["PATH"] = f"{VENV_DIR/('Scripts' if os.name=='nt' else 'bin')}" \
                         f"{os.pathsep}{os.environ.get('PATH','')}"
_ensure_env()

# ═════════════════ Qt / extern imports ═════════════════
from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem, QVBoxLayout,
    QHBoxLayout, QSplitter, QPushButton, QFileDialog, QInputDialog,
    QLabel, QMessageBox, QFrame, QComboBox, QSlider, QDialog,
    QDialogButtonBox
)
from PySide6.QtGui    import (
    QColor, QPalette, QPixmap, QIcon, QDragEnterEvent, QDropEvent
)
from PySide6.QtCore   import Qt, QTimer, Signal
from mutagen          import File as MFile
from mutagen.id3      import ID3
from PIL              import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

import scanner, storage, player, history

# ═════════════════ constants ═════════════════
AUDIO_OPTIONS = ["System default", "DirectSound",
                 "WASAPI shared",  "WASAPI exclusive"]
AUDIO_MODES   = ["default", "directsound", "wasapi_shared", "wasapi_exclusive"]

ART_DIR = Path.home()/".playlist-relinker-cache"/"art"
ART_DIR.mkdir(parents=True, exist_ok=True)

TICKS       = 10        # slider: 100 ms per tick
MAX_SECONDS = 86_400    # 24 h cap

# ═════════════════ helper utilities ═════════════════
def strip_dpr(px: QPixmap) -> QPixmap:
    """Return DPR-1 pixmap so logical == physical px."""
    dpr = px.devicePixelRatioF()
    if dpr == 1.0:
        return px
    cp = px.scaled(int(px.width()*dpr), int(px.height()*dpr),
                   Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    cp.setDevicePixelRatio(1.0)
    return cp

class TimelineSlider(QSlider):
    """Clickable / draggable / wheel-seek slider."""
    jumpRequested = Signal(float)  # seconds

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setOrientation(Qt.Horizontal)

    def _val(self, x: int) -> int:
        r = max(0.0, min(x / self.width(), 1.0))
        return int(self.minimum() + r * (self.maximum() - self.minimum()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setSliderDown(True)
            v = self._val(int(e.position().x() if hasattr(e,"position") else e.pos().x()))
            self.setValue(v); self.jumpRequested.emit(v / TICKS); e.accept()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            v = self._val(int(e.position().x() if hasattr(e,"position") else e.pos().x()))
            self.setValue(v); self.jumpRequested.emit(v / TICKS); e.accept()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False); e.accept()
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        step  = 1 if e.modifiers() & Qt.ControlModifier else 5
        delta = step * (e.angleDelta().y() // 120)
        self.setValue(max(self.minimum(),
                          min(self.maximum(), self.value() + delta * TICKS)))
        self.jumpRequested.emit(self.value() / TICKS)
        e.accept()

# ═════════════════ CreatePlaylistDialog ═════════════════
class CreatePlaylistDialog(QDialog):
    """Pick audio files, reorder, save."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Playlist")
        self.resize(500, 400)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)

        btn_add  = QPushButton("Add files")
        btn_rm   = QPushButton("Remove")
        btn_up   = QPushButton("Up")
        btn_down = QPushButton("Down")
        hl = QHBoxLayout()
        for b in (btn_add, btn_rm, btn_up, btn_down): hl.addWidget(b)
        hl.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        lay = QVBoxLayout(self)
        lay.addWidget(self.list, 1)
        lay.addLayout(hl)
        lay.addWidget(buttons)

        # signals
        btn_add.clicked.connect(self._add_files)
        btn_rm .clicked.connect(self._remove_sel)
        btn_up .clicked.connect(lambda: self._move_sel(-1))
        btn_down.clicked.connect(lambda: self._move_sel(1))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select audio files")
        for f in sorted(files, key=lambda s: s.lower()):
            self.list.addItem(f)

    def _remove_sel(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _move_sel(self, delta: int):
        rows = sorted({self.list.row(it) for it in self.list.selectedItems()})
        if not rows:
            return
        new_rows = [r + delta for r in rows]
        if min(new_rows) < 0 or max(new_rows) >= self.list.count():
            return
        items = [self.list.takeItem(r) for r in rows]
        for r, it in sorted(zip(new_rows, items)):
            self.list.insertItem(r, it); self.list.setItemSelected(it, True)

    def tracks(self) -> List[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

# ═════════════════ MainWindow ═════════════════
class MainWindow(QWidget):
    ART_PX = 256

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Playlist-Player")
        self.resize(1100, 650)
        self.setAcceptDrops(True)
        self._init_style()

        # ── panes
        self.list_playlists = QListWidget(frameShape=QFrame.NoFrame)

        self.tracks_sel = QListWidget(frameShape=QFrame.NoFrame)
        self.tracks_sel.setSelectionMode(QListWidget.NoSelection)

        self.lbl_curtitle = QLabel("Now Playing", alignment=Qt.AlignCenter)
        self.lbl_curtitle.setStyleSheet("font-weight:bold;")

        self.tracks_cur = QListWidget(frameShape=QFrame.NoFrame)
        self.tracks_cur.setSelectionMode(QListWidget.NoSelection)

        self._bar_sel  = QFrame(self.tracks_sel.viewport());  self._bar_sel.setStyleSheet("background:#00a29f;"); self._bar_sel.setFixedWidth(2); self._bar_sel.hide()
        self._bar_play = QFrame(self.tracks_cur.viewport());  self._bar_play.setStyleSheet("background:#00c8ff;"); self._bar_play.setFixedWidth(2); self._bar_play.hide()

        self.cmb_output = QComboBox(); self.cmb_output.addItems(AUDIO_OPTIONS)
        self.lbl_cover  = QLabel(alignment=Qt.AlignCenter); self.lbl_cover.setFixedSize(self.ART_PX, self.ART_PX); self.lbl_cover.setStyleSheet("background:palette(Base);")

        sidebar = QWidget()
        sv = QVBoxLayout(sidebar); sv.setContentsMargins(0, 0, 0, 0)
        sv.addWidget(self.lbl_curtitle)
        sv.addWidget(self.tracks_cur, 1)
        sv.addWidget(QLabel("Audio output"))
        sv.addWidget(self.cmb_output)
        sv.addStretch()
        sv.addWidget(self.lbl_cover, 0, Qt.AlignCenter)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.list_playlists)
        split.addWidget(self.tracks_sel)
        split.addWidget(sidebar)
        split.setSizes([240, 460, 300])

        # ── toolbar
        self.btn_create, self.btn_scan, self.btn_rename, self.btn_delete = (
            QPushButton(t) for t in ("Create", "Scan", "Rename", "Delete")
        )
        self.btn_prev = QPushButton("Prev")
        self.btn_next = QPushButton("Next")

        tb = QHBoxLayout()
        for b in (self.btn_create, self.btn_scan, self.btn_rename, self.btn_delete):
            tb.addWidget(b)
        tb.addStretch()
        tb.addWidget(self.btn_prev); tb.addWidget(self.btn_next)

        # ── playback
        self.btn_play = QPushButton("Play/Pause")
        self.slider   = TimelineSlider(); self.slider.setEnabled(False)
        self.lbl_time = QLabel("00:00 / 00:00", alignment=Qt.AlignRight|Qt.AlignVCenter); self.lbl_time.setFixedWidth(110)
        pb = QHBoxLayout(); pb.addWidget(self.btn_play); pb.addWidget(self.slider, 1); pb.addWidget(self.lbl_time)

        root = QVBoxLayout(self)
        root.addLayout(tb)
        root.addWidget(split, 1)
        root.addLayout(pb)

        # state
        self._playlists: List[scanner.Playlist] = []
        self._cur_pl_idx: Optional[int] = None
        self._meta_cache: Dict[Path, Tuple[str, str, Optional[Path]]] = {}
        self._icon_cache: Dict[Path, QPixmap] = {}

        # player
        self._load_state()
        self._player = player.VLCGaplessPlayer(self._on_track_change)

        # signals
        self.slider.jumpRequested.connect(self._player.seek)
        self.cmb_output.currentIndexChanged.connect(lambda i: self._player.set_output(AUDIO_MODES[i]))
        self.btn_create.clicked.connect(self._create_playlist)
        self.btn_scan  .clicked.connect(self._scan_folder)
        self.btn_rename.clicked.connect(self._rename_playlist)
        self.btn_delete.clicked.connect(self._delete_playlist)
        self.list_playlists.itemDoubleClicked.connect(self._play_selected)
        self.list_playlists.currentRowChanged.connect(lambda *_: self._refresh_sel())
        self.btn_prev.clicked.connect(self._player.prev_track)
        self.btn_next.clicked.connect(self._player.next_track)
        self.btn_play.clicked.connect(self._toggle_play)
        QTimer(self, interval=100, timeout=self._tick).start()

    # ── style
    def _init_style(self):
        hi = self.palette().color(QPalette.Highlight)
        self._row_bg = hi.lighter(130).name()
        hover = hi.lighter(150).name()
        self.setStyleSheet(
            "QWidget {font-family:Segoe UI; font-size:10pt;}"
            "QListWidget::item {padding:2px 4px;}"
            "QListWidget::item:selected {background:palette(Highlight); color:palette(HighlightedText);}"
            "QPushButton {padding:4px 12px; border:1px solid palette(Midlight); border-radius:4px; background:palette(Button);}"
            f"QPushButton:hover {{background:{hover};}}"
        )

    # ── drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent):
        if any(Path(u.toLocalFile()).is_dir() or Path(u.toLocalFile()).suffix.lower() in scanner.PLAYLIST_EXTS
               for u in e.mimeData().urls()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        changed = False
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                changed |= self._add_playlists(scanner.scan_playlists(p))
            elif p.suffix.lower() in scanner.PLAYLIST_EXTS:
                pl = next((pl for pl in scanner.scan_playlists(p.parent, False) if pl.path == p), None)
                if pl:
                    changed |= self._add_playlists([pl])
        if changed:
            self._save_state()

    # ── metadata & cover-art
    def _probe(self, data: bytes, mime: str, prio: int):
        area = 0
        try:
            with Image.open(io.BytesIO(data)) as im:
                area = im.width * im.height
        except Exception:
            pass
        return (area, len(data), prio, data, mime)

    def _extract_art(self, audio, path: Path):
        cand = []
        if isinstance(audio.tags, ID3):
            for ap in audio.tags.getall("APIC"):
                cand.append(self._probe(ap.data, ap.mime or "image/jpeg", 2 if ap.type == 3 else 1))
        if getattr(audio, "pictures", None):
            for pic in audio.pictures:
                cand.append(self._probe(pic.data, pic.mime or "image/jpeg", 2 if getattr(pic, "type", 3) == 3 else 1))
        for stem in ("cover", "folder", "front", "AlbumArt", "Artwork"):
            for ext in (".jpg", ".jpeg", ".png"):
                f = path.parent / f"{stem}{ext}"
                if f.exists():
                    cand.append(self._probe(f.read_bytes(), "image/png" if ext.endswith("png") else "image/jpeg", 0))
        if not cand:
            return None
        cand.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        _, _, _, data, mime = cand[0]
        ext = ".png" if "png" in mime else ".jpg"
        art = ART_DIR / (hashlib.md5(str(path).encode()).hexdigest() + ext)
        if not art.exists():
            art.write_bytes(data)
        return art

    def _meta(self, p: Path):
        if p in self._meta_cache:
            return self._meta_cache[p]
        title = artist = ""; art = None
        try:
            audio = MFile(p)
            if getattr(audio, "tags", None):
                title  = (audio.tags.get("TIT2") or audio.tags.get("TITLE") or [""])[0]
                artist = (audio.tags.get("TPE1") or audio.tags.get("ARTIST") or [""])[0]
            art = self._extract_art(audio, p)
        except Exception:
            pass
        self._meta_cache[p] = (title, artist, art)
        return self._meta_cache[p]

    def _display(self, p): t, a, _ = self._meta(p); return f"{a} – {t}" if t and a else (t or a or p.name)
    def _icon48(self, p):
        if p in self._icon_cache:
            return QIcon(self._icon_cache[p])
        _, _, art = self._meta(p)
        if art and art.exists():
            pix = strip_dpr(QPixmap(str(art))).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._icon_cache[p] = pix; return QIcon(pix)
        return None
    def _cover(self, p: Path):
        _, _, art = self._meta(p)
        return strip_dpr(QPixmap(str(art))).scaled(self.ART_PX, self.ART_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation) if art and art.exists() else None

    # ── persistence
    def _load_state(self):
        for rec in storage.load():
            p = Path(rec["path"])
            if not p.exists():
                continue
            pl = next((pl for pl in scanner.scan_playlists(p.parent, False) if pl.path == p), None)
            if pl:
                pl.name = rec.get("name", p.stem)
                self._playlists.append(pl)
                self.list_playlists.addItem(pl.name)

    def _save_state(self):
        storage.save([{"path": str(pl.path), "name": pl.name} for pl in self._playlists])

    # ── playlist mgmt
    def _add_playlists(self, new: List[scanner.Playlist]) -> bool:
        added = False
        for pl in new:
            if all(pl.path != o.path for o in self._playlists):
                self._playlists.append(pl)
                self.list_playlists.addItem(pl.name)
                added = True
        return added

    def _scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder")
        if folder and self._add_playlists(scanner.scan_playlists(Path(folder))):
            self._save_state()

    def _sel_pl(self) -> Optional[scanner.Playlist]:
        idx = self.list_playlists.currentRow()
        return self._playlists[idx] if 0 <= idx < len(self._playlists) else None

    def _rename_playlist(self):
        pl = self._sel_pl()
        if not pl:
            return
        new, ok = QInputDialog.getText(self, "Rename playlist", "Display name:", text=pl.name)
        if ok and new.strip():
            pl.name = new.strip()
            self.list_playlists.currentItem().setText(pl.name)
            self._save_state()

    def _delete_playlist(self):
        pl = self._sel_pl()
        if not pl:
            return
        if QMessageBox.question(self, "Delete playlist",
                                f"Remove “{pl.name}” from list?\n(File stays on disk.)",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            i = self.list_playlists.currentRow()
            self.list_playlists.takeItem(i)
            self._playlists.pop(i)
            self._save_state()
            self._refresh_sel()

    # ── create playlist (NEW)
    def _create_playlist(self):
        dlg = CreatePlaylistDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        tracks = dlg.tracks()
        if not tracks:
            return
        default = str(Path.home() / "playlist.m3u8")
        fname, _ = QFileDialog.getSaveFileName(self, "Save playlist",
                                               default, "M3U8 playlist (*.m3u8)")
        if not fname:
            return
        path = Path(fname)
        try:
            path.write_text("\n".join(tracks), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not write playlist:\n{e}")
            return
        pl = scanner.Playlist(path=path, name=path.stem, tracks=[Path(t) for t in tracks])
        if self._add_playlists([pl]):
            self._save_state()

    # ── list visuals
    def _make_item(self, p: Path, prefix: str = ""):
        it = QListWidgetItem(prefix + self._display(p))
        if ico := self._icon48(p):
            it.setIcon(ico)
        return it

    def _place_bar(self, bar: QFrame, lw: QListWidget, idx: int, frac: float):
        if not (0 <= idx < lw.count()):
            bar.hide(); return
        frac = max(0.0, min(frac, 1.0))
        rect = lw.visualItemRect(lw.item(idx))
        width = lw.viewport().width()
        x = int(max(0, min(rect.left() + frac * rect.width(), width - 2)))
        bar.setGeometry(x, rect.top(), 2, rect.height())
        bar.show()

    def _refresh_sel(self):
        self.tracks_sel.clear(); self._bar_sel.hide()
        pl = self._sel_pl()
        if not pl:
            return
        hist = history.load(pl.path)
        finished = set(hist.get("finished", []))
        idx  = hist.get("track_index", -1)
        pos  = float(hist.get("position", 0))
        length = float(hist.get("length", 0))
        if (length <= 0 or length is None) and 0 <= idx < len(pl.tracks):
            try:
                length = MFile(pl.tracks[idx]).info.length or 0.0
            except Exception:
                length = 0.0
        frac = pos / max(1.0, length)

        for i, t in enumerate(pl.tracks):
            it = self._make_item(Path(t))
            if str(t) in finished: it.setForeground(QColor("gray"))
            if not Path(t).exists(): it.setForeground(QColor("red"))
            if i == idx:
                f = it.font(); f.setBold(True); it.setFont(f)
            self.tracks_sel.addItem(it)

        if pos > 0 and 0 <= idx < len(pl.tracks):
            self._place_bar(self._bar_sel, self.tracks_sel, idx, frac)

    def _refresh_cur(self):
        self.tracks_cur.clear(); self._bar_play.hide()
        if not self._player.playlist:
            return
        fin = set(history.load(self._player._pl_path).get("finished", []))
        for i, t in enumerate(self._player.playlist):
            it = self._make_item(Path(t), "▶ " if i == self._player.idx else "")
            if i == self._player.idx:
                f = it.font(); f.setBold(True); it.setFont(f)
            if str(t) in fin: it.setForeground(QColor("gray"))
            if not Path(t).exists(): it.setForeground(QColor("red"))
            self.tracks_cur.addItem(it)
        self._place_play_bar()

    def _place_play_bar(self):
        if not self._player.player:
            self._bar_play.hide(); return
        length = max(1, self._player.length())
        frac   = self._player.position() / length
        self._place_bar(self._bar_play, self.tracks_cur, self._player.idx, frac)

    def _highlight_row(self):
        for r in range(self.list_playlists.count()):
            it   = self.list_playlists.item(r)
            bold = r == self._cur_pl_idx
            it.setBackground(QColor(self._row_bg) if bold else Qt.transparent)
            f = it.font(); f.setBold(bold); it.setFont(f)

    # ── playback controls
    def _play_selected(self):
        pl = self._sel_pl()
        if pl:
            self._player.load_playlist(pl.path, pl.tracks)
            self.slider.setEnabled(True)
            self._player.play(); self._on_track_change()

    def _toggle_play(self):
        if self._player.player and self._player.player.is_playing():
            self._player.pause()
        elif not self._player.player:
            self._play_selected()
        else:
            self._player.play()

    # ── timer tick (100 ms)
    def _tick(self):
        self._player.tick()
        if self._player.player:
            length = max(1, min(MAX_SECONDS, self._player.length()))
            pos    = max(0.0, min(self._player.position(), length))
            if not self.slider.isSliderDown():
                self.slider.setMaximum(int(length * TICKS))
                self.slider.setValue(int(pos * TICKS))
            self._update_time_label(pos, length)
            self._place_play_bar()
            sel_pl = self._sel_pl()
            if sel_pl and sel_pl.path == self._player._pl_path:
                self._place_bar(self._bar_sel, self.tracks_sel,
                                self._player.idx, pos / length)

    def _update_time_label(self, pos: float, length: float):
        self.lbl_time.setText(
            f"{int(pos)//60:02}:{int(pos)%60:02} / "
            f"{int(length)//60:02}:{int(length)%60:02}"
        )

    # ── player callback
    def _on_track_change(self, *_):
        self.slider.setEnabled(True)
        self._cur_pl_idx = next((i for i, pl in enumerate(self._playlists)
                                 if pl.path == self._player._pl_path), None)
        current_pl = self._sel_pl()
        self.lbl_curtitle.setText(current_pl.name if current_pl else "Now Playing")
        self._highlight_row(); self._refresh_cur(); self._refresh_sel()
        self.lbl_cover.setPixmap(self._cover(self._player.playlist[self._player.idx]) or QPixmap())

    # ── close / save state
    def closeEvent(self, e):
        self._save_state()
        super().closeEvent(e)

# ═════════════════ entry-point ═════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow(); win.show()
    sys.exit(app.exec())
