#!/usr/bin/env python3
# main.py – rev-w35 (2025-06-25)
"""
Playlist-Player GUI

New in w35
──────────
• **Create** button (toolbar, far-left).  
  Opens a dialog where you pick audio files, optionally reorder them,
  then save as a new **.m3u8** playlist. The playlist is scanned and
  added immediately.
• Toolbar layout:  Create · Scan · Rename · Delete   …… Prev Next
• All earlier features (debounced history, cover-art, etc.) unchanged.
"""

from __future__ import annotations
import sys, os, subprocess, venv, site, hashlib, io, tempfile, json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# ════════════════════════════════════════════════════════════════════════
#  Local venv (auto-installs PySide6, python-vlc, mutagen, Pillow)
# ════════════════════════════════════════════════════════════════════════
APP_DIR  = Path(__file__).parent
VENV_DIR = APP_DIR / ".venv"
PYSIDE_REQ = "PySide6>=6.9.0" if sys.version_info >= (3, 13) else "PySide6>=6.7,<6.8"
REQS = [PYSIDE_REQ, "python-vlc", "mutagen", "pillow"]

def _ensure_env() -> None:
    if getattr(sys, "frozen", False):   # PyInstaller etc.
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
                         f"{os.pathsep}{os.environ.get('PATH', '')}"
_ensure_env()

# ════════════════════════════════════════════════════════════════════════
#  Qt / extern imports
# ════════════════════════════════════════════════════════════════════════
from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem, QVBoxLayout,
    QHBoxLayout, QSplitter, QPushButton, QFileDialog, QInputDialog,
    QLabel, QMessageBox, QFrame, QComboBox, QSlider, QDialog,
    QDialogButtonBox
)
from PySide6.QtGui    import QColor, QPalette, QPixmap, QIcon, QDragEnterEvent, QDropEvent
from PySide6.QtCore   import Qt, QTimer, Signal
from mutagen          import File as MFile
from mutagen.id3      import ID3
from PIL              import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

import scanner, storage, player, history

# ════════════════════════════════════════════════════════════════════════
#  Constants
# ════════════════════════════════════════════════════════════════════════
AUDIO_OPTIONS = ["System default", "DirectSound", "WASAPI shared", "WASAPI exclusive"]
AUDIO_MODES   = ["default", "directsound", "wasapi_shared", "wasapi_exclusive"]

ART_DIR = Path.home()/".playlist-relinker-cache"/"art"
ART_DIR.mkdir(parents=True, exist_ok=True)

TICKS       = 10        # 100 ms slider granularity
MAX_SECONDS = 86_400    # 24 h cap

# ════════════════════════════════════════════════════════════════════════
#  Helper utilities
# ════════════════════════════════════════════════════════════════════════
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
    """Clickable, draggable & wheel-seek slider."""
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
            v = self._val(int(e.position().x() if hasattr(e, "position") else e.pos().x()))
            self.setValue(v); self.jumpRequested.emit(v / TICKS); e.accept()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            v = self._val(int(e.position().x() if hasattr(e, "position") else e.pos().x()))
            self.setValue(v); self.jumpRequested.emit(v / TICKS); e.accept()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False); e.accept()
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        step = 1 if e.modifiers() & Qt.ControlModifier else 5
        delta = step * (e.angleDelta().y() // 120)   # ± ticks
        self.setValue(max(self.minimum(),
                          min(self.maximum(), self.value() + delta * TICKS)))
        self.jumpRequested.emit(self.value() / TICKS); e.accept()

# ════════════════════════════════════════════════════════════════════════
#  CreatePlaylistDialog
# ════════════════════════════════════════════════════════════════════════
class CreatePlaylistDialog(QDialog):
    """Dialog: pick files, reorder, save."""
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

        btns = QHBoxLayout()
        for b in (btn_add, btn_rm, btn_up, btn_down):
            btns.addWidget(b)
        btns.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        lay = QVBoxLayout(self)
        lay.addWidget(self.list, 1)
        lay.addLayout(btns)
        lay.addWidget(buttons)

        # signals
        btn_add.clicked.connect(self._add_files)
        btn_rm.clicked.connect(self._remove_sel)
        btn_up.clicked.connect(lambda: self._move_sel(-1))
        btn_down.clicked.connect(lambda: self._move_sel(1))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    # file ops
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
            self.list.insertItem(r, it)
            self.list.setItemSelected(it, True)

    def tracks(self) -> List[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

# ════════════════════════════════════════════════════════════════════════
#  MainWindow
# ════════════════════════════════════════════════════════════════════════
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

        # sidebar
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
        tb.addWidget(self.btn_prev)
        tb.addWidget(self.btn_next)

        # ── playback controls
        self.btn_play = QPushButton("Play/Pause")
        self.slider   = TimelineSlider(); self.slider.setEnabled(False)
        self.lbl_time = QLabel("00:00 / 00:00", alignment=Qt.AlignRight|Qt.AlignVCenter); self.lbl_time.setFixedWidth(110)

        pb = QHBoxLayout()
        pb.addWidget(self.btn_play)
        pb.addWidget(self.slider, 1)
        pb.addWidget(self.lbl_time)

        # root layout
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
        self.btn_scan.clicked.connect(self._scan_folder)
        self.btn_rename.clicked.connect(self._rename_playlist)
        self.btn_delete.clicked.connect(self._delete_playlist)
        self.list_playlists.itemDoubleClicked.connect(self._play_selected)
        self.list_playlists.currentRowChanged.connect(lambda *_: self._refresh_sel())
        self.btn_prev.clicked.connect(self._player.prev_track)
        self.btn_next.clicked.connect(self._player.next_track)
        self.btn_play.clicked.connect(self._toggle_play)
        QTimer(self, interval=100, timeout=self._tick).start()

    # ──────────────────────────────────────────────────────────
    #  styling
    # ──────────────────────────────────────────────────────────
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

    # ──────────────────────────────────────────────────────────
    #  Create playlist (new)
    # ──────────────────────────────────────────────────────────
    def _create_playlist(self):
        dlg = CreatePlaylistDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        tracks = dlg.tracks()
        if not tracks:
            return
        default_path = str(Path.home() / "playlist.m3u8")
        fname, _ = QFileDialog.getSaveFileName(
            self, "Save playlist", default_path, "M3U8 playlist (*.m3u8)"
        )
        if not fname:
            return
        path = Path(fname)
        try:
            # Write UTF-8 M3U8
            path.write_text("\n".join(tracks), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Error",
                                 f"Could not write playlist:\n{e}")
            return
        # Scan just this file
        pl = scanner.Playlist(path=path, name=path.stem,
                              tracks=[Path(t) for t in tracks])
        if self._add_playlists([pl]):
            self._save_state()

    # ──────────────────────────────────────────────────────────
    #  Drag-and-drop handling, metadata, persistence, etc.
    #  (identical to rev-w34, omitted for brevity)
    # ──────────────────────────────────────────────────────────
    # … identical helper methods: _probe, _extract_art, _meta,
    #   _display, _icon48, _cover, _load_state, _save_state,
    #   _add_playlists, _scan_folder, _sel_pl, _rename_playlist,
    #   _delete_playlist …
    # ──────────────────────────────────────────────────────────
