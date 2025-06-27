#!/usr/bin/env python3
# main.py – rev-w43-full  (2025-06-27)
"""
Playlist-Player
───────────────
Gap-less playlist player for Windows (PySide6 + libVLC).

Key features
• Scan / create / rename / delete playlists (.m3u, .m3u8, .fplite + index.txt)
• Gap-less playback with DirectSound / WASAPI selector
• Resume history written every 5 s (or on key events) → *.history.json
• Friendly *display_name* stored in history.json (survives app.state loss)
• Embedded cover-art, timeline seek (click / drag / wheel; Ctrl = fine)
• Custom icon  ▸  Playlist-Player_logo.ico (project root)
"""

from __future__ import annotations
import sys, os, subprocess, venv, site, hashlib, io
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# ═════════════════ 0. bootstrap local venv ═════════════════
APP_DIR  = Path(__file__).parent
VENV_DIR = APP_DIR / ".venv"
PYSIDE_REQ = "PySide6>=6.9.0" if sys.version_info >= (3, 13) else "PySide6>=6.7,<6.8"
REQS = [PYSIDE_REQ, "python-vlc", "mutagen", "pillow", "keyboard"]

def _ensure_env() -> None:
    if getattr(sys, "frozen", False):
        return
    if not VENV_DIR.exists():
        venv.create(VENV_DIR, with_pip=True)
        subprocess.check_call([
            VENV_DIR / ("Scripts" if os.name=="nt" else "bin") / "pip",
            "install", *REQS, "--quiet"
        ])
    sp = (VENV_DIR/"Lib/site-packages") if os.name=="nt" else \
         next((VENV_DIR/"lib").glob("python*/site-packages"))
    site.addsitedir(sp)
    os.environ["PATH"] = f"{VENV_DIR/('Scripts' if os.name=='nt' else 'bin')}{os.pathsep}{os.environ.get('PATH','')}"
_ensure_env()

# ═════════════════ 1. Qt / extern imports ═════════════════
from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem, QVBoxLayout,
    QHBoxLayout, QSplitter, QPushButton, QFileDialog, QInputDialog,
    QLabel, QMessageBox, QFrame, QComboBox, QSlider, QDialog,
    QDialogButtonBox, QCheckBox
)
from PySide6.QtGui    import (
    QColor, QPalette, QPixmap, QIcon, QDragEnterEvent, QDropEvent
)
from PySide6.QtCore   import Qt, QTimer, Signal
from mutagen          import File as MFile
from mutagen.id3      import ID3
from PIL              import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
try:
    import keyboard
except Exception:
    keyboard = None

import scanner, storage, player, history

# ═════════════════ 2. constants & helpers ═════════════════
ICON_PATH  = APP_DIR / "Playlist-Player_logo.ico"
AUDIO_OPTIONS = ["System default", "DirectSound", "WASAPI shared", "WASAPI exclusive"]
AUDIO_MODES   = ["default", "directsound", "wasapi_shared", "wasapi_exclusive"]

# color themes: name -> palette colors
THEMES = {
    "System": None,
    "Light":  {"window":"#ffffff", "text":"#000000", "button":"#f0f0f0", "base":"#ffffff",
                "highlight":"#3daee9", "highlight_text":"#ffffff"},
    "Dark":   {"window":"#2b2b2b", "text":"#dddddd", "button":"#3c3c3c", "base":"#4a4a4a",
                "highlight":"#3daee9", "highlight_text":"#000000"},
    "Ocean":  {"window":"#e0f7fa", "text":"#004d40", "button":"#b2ebf2", "base":"#ffffff",
                "highlight":"#00838f", "highlight_text":"#ffffff"},
    "Forest": {"window":"#e8f5e9", "text":"#1b5e20", "button":"#c8e6c9", "base":"#ffffff",
                "highlight":"#43a047", "highlight_text":"#ffffff"},
    "Plum":   {"window":"#f3e5f5", "text":"#4a148c", "button":"#e1bee7", "base":"#ffffff",
                "highlight":"#6a1b9a", "highlight_text":"#ffffff"},
}
ART_DIR = Path.home()/".playlist-relinker-cache"/"art"; ART_DIR.mkdir(parents=True, exist_ok=True)
TICKS, MAX_SECONDS = 10, 86_400   # slider: 100 ms per tick; clamp 24 h

def strip_dpr(px: QPixmap) -> QPixmap:
    dpr = px.devicePixelRatioF()
    if dpr == 1.0: return px
    cp = px.scaled(int(px.width()*dpr), int(px.height()*dpr),
                   Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    cp.setDevicePixelRatio(1.0)
    return cp

class TimelineSlider(QSlider):
    """Clickable / draggable / wheel-seek slider (Ctrl = ±1 s, else ±5 s)."""
    jumpRequested = Signal(float)          # seconds (float)

    def __init__(self,*a,**k):
        super().__init__(*a,**k); self.setOrientation(Qt.Horizontal)

    def _val(self,x:int)->int:
        r = max(0, min(x/self.width(), 1))
        return int(self.minimum() + r*(self.maximum()-self.minimum()))

    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:
            self.setSliderDown(True)
            v=self._val(int(e.position().x() if hasattr(e,"position") else e.pos().x()))
            self.setValue(v); self.jumpRequested.emit(v/TICKS); e.accept()
        super().mousePressEvent(e)

    def mouseMoveEvent(self,e):
        if self.isSliderDown():
            v=self._val(int(e.position().x() if hasattr(e,"position") else e.pos().x()))
            self.setValue(v); self.jumpRequested.emit(v/TICKS); e.accept()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self,e):
        if self.isSliderDown(): self.setSliderDown(False); e.accept()
        super().mouseReleaseEvent(e)

    def wheelEvent(self,e):
        step = 1 if e.modifiers() & Qt.ControlModifier else 5
        delta = step * (e.angleDelta().y() // 120)
        self.setValue(max(self.minimum(), min(self.maximum(), self.value()+delta*TICKS)))
        self.jumpRequested.emit(self.value()/TICKS); e.accept()

# ═════════════════ 3. CreatePlaylistDialog ═════════════════
class CreatePlaylistDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Playlist"); self.resize(500,400)

        self.list = QListWidget(); self.list.setSelectionMode(QListWidget.ExtendedSelection)
        btn_add,btn_rm,btn_up,btn_down = (QPushButton(t) for t in ("Add files","Remove","Up","Down"))
        ctl=QHBoxLayout(); [ctl.addWidget(b) for b in(btn_add,btn_rm,btn_up,btn_down)]; ctl.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        lay = QVBoxLayout(self); lay.addWidget(self.list,1); lay.addLayout(ctl); lay.addWidget(buttons)

        btn_add.clicked.connect(self._add_files); btn_rm.clicked.connect(self._remove_sel)
        btn_up.clicked.connect(lambda:self._move_sel(-1)); btn_down.clicked.connect(lambda:self._move_sel(1))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)

    def _add_files(self):
        files,_ = QFileDialog.getOpenFileNames(self,"Select audio files")
        for f in sorted(files,key=str.lower): self.list.addItem(f)

    def _remove_sel(self):
        for it in self.list.selectedItems(): self.list.takeItem(self.list.row(it))

    def _move_sel(self,delta:int):
        rows = sorted({self.list.row(it) for it in self.list.selectedItems()})
        if not rows: return
        dest = [r+delta for r in rows]
        if min(dest)<0 or max(dest)>=self.list.count(): return
        items = [self.list.takeItem(r) for r in reversed(rows)]
        for r,it in zip(dest, reversed(items)):
            self.list.insertItem(r,it)
            self.list.setItemSelected(it,True)

    def tracks(self)->List[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

# ═════════════════ 4. MainWindow ═════════════════
class MainWindow(QWidget):
    ART_PX=256
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Playlist-Player")
        if ICON_PATH.exists(): self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1100,650); self.setAcceptDrops(True)
        self._init_style(); self._build_widgets()

        # runtime state
        self._playlists:List[scanner.Playlist]=[]
        self._cur_pl_idx:Optional[int]=None
        self._meta_cache:Dict[Path,Tuple[str,str,Optional[Path]]]={}
        self._icon_cache:Dict[Path,QPixmap]={}
        self._auto_resume=False
        self._normalize=False
        self._compress=False
        self._theme="System"

        self._load_state()
        self._player = player.VLCGaplessPlayer(self._on_track_change)
        self._player.set_normalize(self._normalize)
        self._player.set_compress(self._compress)
        self._wire_signals()
        self._apply_theme(self._theme)
        QTimer(self,interval=100,timeout=self._tick).start()
        self._hotkey=None
        if keyboard:
            try:
                self._hotkey=keyboard.add_hotkey(
                    'play/pause media',
                    lambda: QTimer.singleShot(0, self._toggle_play))
            except Exception:
                self._hotkey=None

        if self._auto_resume and self._cur_pl_idx is not None:
            pl = self._playlists[self._cur_pl_idx]
            self._player.load_playlist(pl.path, pl.tracks)
            self.slider.setEnabled(True)
            self._player.play()
            self._on_track_change()

    # ---------- UI
    def _build_widgets(self):
        self.list_playlists = QListWidget(frameShape=QFrame.NoFrame)

        self.tracks_sel = QListWidget(frameShape=QFrame.NoFrame); self.tracks_sel.setSelectionMode(QListWidget.NoSelection)
        self.lbl_curtitle = QLabel("Now Playing",alignment=Qt.AlignCenter); self.lbl_curtitle.setStyleSheet("font-weight:bold;")
        self.tracks_cur = QListWidget(frameShape=QFrame.NoFrame); self.tracks_cur.setSelectionMode(QListWidget.NoSelection)

        self._bar_sel  = QFrame(self.tracks_sel.viewport());  self._bar_sel.setStyleSheet("background:#00a29f;"); self._bar_sel.setFixedWidth(2); self._bar_sel.hide()
        self._bar_play = QFrame(self.tracks_cur.viewport());  self._bar_play.setStyleSheet("background:#00c8ff;"); self._bar_play.setFixedWidth(2); self._bar_play.hide()

        self.cmb_output = QComboBox(); self.cmb_output.addItems(AUDIO_OPTIONS)
        self.chk_normalize = QCheckBox("Normalize volume")
        self.chk_compress  = QCheckBox("Boost quiet audio")
        self.lbl_cover  = QLabel(alignment=Qt.AlignCenter); self.lbl_cover.setFixedSize(self.ART_PX,self.ART_PX); self.lbl_cover.setStyleSheet("background:palette(Base);")

        sidebar = QWidget(); sv = QVBoxLayout(sidebar); sv.setContentsMargins(0,0,0,0)
        sv.addWidget(self.lbl_curtitle); sv.addWidget(self.tracks_cur,1)
        sv.addWidget(QLabel("Audio output")); sv.addWidget(self.cmb_output)
        sv.addWidget(self.chk_normalize); sv.addWidget(self.chk_compress)
        sv.addStretch(); sv.addWidget(self.lbl_cover,0,Qt.AlignCenter)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.list_playlists); split.addWidget(self.tracks_sel); split.addWidget(sidebar)
        split.setSizes([240,460,300])

        self.btn_create,self.btn_scan,self.btn_rename,self.btn_delete=(QPushButton(t) for t in ("Create","Scan","Rename","Delete"))
        self.cmb_theme = QComboBox(); self.cmb_theme.addItems(list(THEMES.keys()))
        self.btn_prev=QPushButton("Prev"); self.btn_next=QPushButton("Next")
        tb=QHBoxLayout(); [tb.addWidget(b) for b in(self.btn_create,self.btn_scan,self.btn_rename,self.btn_delete)]; tb.addStretch(); tb.addWidget(self.cmb_theme); tb.addWidget(self.btn_prev); tb.addWidget(self.btn_next)

        self.btn_play = QPushButton("Play/Pause")
        self.chk_resume = QCheckBox("Auto-resume")
        self.slider   = TimelineSlider(); self.slider.setEnabled(False)
        self.lbl_time = QLabel("00:00 / 00:00",alignment=Qt.AlignRight|Qt.AlignVCenter); self.lbl_time.setFixedWidth(110)
        pb = QHBoxLayout(); pb.addWidget(self.btn_play); pb.addWidget(self.chk_resume); pb.addWidget(self.slider,1); pb.addWidget(self.lbl_time)

        root = QVBoxLayout(self); root.addLayout(tb); root.addWidget(split,1); root.addLayout(pb)

    # ---------- style
    def _init_style(self):
        hi=self.palette().color(QPalette.Highlight)
        self._row_bg=hi.lighter(130).name(); hover=hi.lighter(150).name()
        self.setStyleSheet(
            "QWidget {font-family:Segoe UI; font-size:10pt;}"
            "QListWidget::item {padding:2px 4px;}"
            "QListWidget::item:selected {background:palette(Highlight); color:palette(HighlightedText);}"
            "QPushButton {padding:4px 12px; border:1px solid palette(Midlight); border-radius:4px; background:palette(Button);}"+
            f"QPushButton:hover {{background:{hover};}}"
        )

    def _apply_theme(self,name:str):
        app=QApplication.instance()
        if not app:
            return
        self._theme=name
        cfg=THEMES.get(name)
        if cfg is None:
            pal=app.style().standardPalette()
        else:
            pal=QPalette()
            pal.setColor(QPalette.Window, QColor(cfg["window"]))
            pal.setColor(QPalette.WindowText, QColor(cfg["text"]))
            pal.setColor(QPalette.Base, QColor(cfg.get("base", cfg["window"])))
            pal.setColor(QPalette.Text, QColor(cfg["text"]))
            pal.setColor(QPalette.Button, QColor(cfg["button"]))
            pal.setColor(QPalette.ButtonText, QColor(cfg["text"]))
            pal.setColor(QPalette.Highlight, QColor(cfg["highlight"]))
            pal.setColor(QPalette.HighlightedText, QColor(cfg["highlight_text"]))
        app.setPalette(pal)
        self._init_style()
        self._refresh_sel(); self._refresh_cur(); self._highlight_row()

    # ---------- signals
    def _wire_signals(self):
        self.slider.jumpRequested.connect(self._player.seek)
        self.cmb_output.currentIndexChanged.connect(lambda i:self._player.set_output(AUDIO_MODES[i]))
        self.btn_create.clicked.connect(self._create_playlist)
        self.btn_scan.clicked.connect(self._scan_folder)
        self.btn_rename.clicked.connect(self._rename_playlist)
        self.btn_delete.clicked.connect(self._delete_playlist)
        self.list_playlists.itemDoubleClicked.connect(self._play_selected)
        self.list_playlists.currentRowChanged.connect(lambda *_: self._refresh_sel())
        self.btn_prev.clicked.connect(self._player.prev_track)
        self.btn_next.clicked.connect(self._player.next_track)
        self.btn_play.clicked.connect(self._toggle_play)
        self.chk_resume.stateChanged.connect(lambda *_: self._save_state())
        self.chk_normalize.stateChanged.connect(
            lambda s: (self._player.set_normalize(bool(s)), self._save_state())
        )
        self.chk_compress.stateChanged.connect(
            lambda s: (self._player.set_compress(bool(s)), self._save_state())
        )
        self.cmb_theme.currentTextChanged.connect(lambda n:(self._apply_theme(n), self._save_state()))

    # ═════════════════ 5. drag & drop ═════════════════
    def dragEnterEvent(self,e:QDragEnterEvent):
        if any(Path(u.toLocalFile()).is_dir() or Path(u.toLocalFile()).suffix.lower() in scanner.PLAYLIST_EXTS
               for u in e.mimeData().urls()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self,e:QDropEvent):
        changed=False
        for url in e.mimeData().urls():
            p=Path(url.toLocalFile())
            if p.is_dir():
                changed |= self._add_playlists(scanner.scan_playlists(p))
            elif p.suffix.lower() in scanner.PLAYLIST_EXTS:
                pl=next((pl for pl in scanner.scan_playlists(p.parent,False) if pl.path==p),None)
                if pl: changed |= self._add_playlists([pl])
        if changed: self._save_state()

    # ═════════════════ 6. metadata & icons ═════════════════
    def _probe(self,data:bytes,mime:str,prio:int):
        area=0
        try:
            with Image.open(io.BytesIO(data)) as im: area=im.width*im.height
        except Exception: pass
        return (area,len(data),prio,data,mime)

    def _extract_art(self,audio,path:Path):
        cand=[]
        if isinstance(audio.tags,ID3):
            for ap in audio.tags.getall("APIC"):
                cand.append(self._probe(ap.data, ap.mime or "image/jpeg", 2 if ap.type==3 else 1))
        if getattr(audio,"pictures",None):
            for pic in audio.pictures:
                cand.append(self._probe(pic.data, pic.mime or "image/jpeg", 2 if getattr(pic,"type",3)==3 else 1))
        for stem in ("cover","folder","front","AlbumArt","Artwork"):
            for ext in (".jpg",".jpeg",".png"):
                f=path.parent/f"{stem}{ext}"
                if f.exists():
                    cand.append(self._probe(f.read_bytes(),"image/png" if ext.endswith("png") else "image/jpeg",0))
        if not cand: return None
        cand.sort(key=lambda t:(t[0],t[1],t[2]),reverse=True)
        *_,data,mime=cand[0]
        ext=".png" if "png" in mime else ".jpg"
        art=ART_DIR/(hashlib.md5(str(path).encode()).hexdigest()+ext)
        if not art.exists(): art.write_bytes(data)
        return art

    def _meta(self,p:Path):
        if p in self._meta_cache: return self._meta_cache[p]
        title=artist=""; art=None
        try:
            audio=MFile(p)
            if getattr(audio,"tags",None):
                title =(audio.tags.get("TIT2") or audio.tags.get("TITLE")  or [""])[0]
                artist=(audio.tags.get("TPE1") or audio.tags.get("ARTIST") or [""])[0]
            art=self._extract_art(audio,p)
        except Exception: pass
        self._meta_cache[p]=(title,artist,art); return self._meta_cache[p]

    def _display(self,p:Path):
        t,a,_ = self._meta(p)
        return f"{a} – {t}" if t and a else (t or a or p.name)

    def _icon48(self,p:Path):
        if p in self._icon_cache: return QIcon(self._icon_cache[p])
        _,_,art=self._meta(p)
        if art and art.exists():
            pix=strip_dpr(QPixmap(str(art))).scaled(48,48,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            self._icon_cache[p]=pix; return QIcon(pix)
        return None

    def _cover(self,p:Path):
        _,_,art=self._meta(p)
        return (strip_dpr(QPixmap(str(art))).scaled(self.ART_PX,self.ART_PX,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                if art and art.exists() else None)

    # ═════════════════ 7. persistence ═════════════════
    def _load_state(self):
        state   = storage.load()
        self._theme = state.get("theme", "System")
        if hasattr(self, 'cmb_theme'):
            idx = self.cmb_theme.findText(self._theme)
            if idx != -1:
                self.cmb_theme.setCurrentIndex(idx)
        self._auto_resume = bool(state.get("auto_resume", False))
        self.chk_resume.setChecked(self._auto_resume)
        self._normalize   = bool(state.get("normalize", False))
        if hasattr(self, 'chk_normalize'):
            self.chk_normalize.setChecked(self._normalize)
        self._compress    = bool(state.get("compress", False))
        if hasattr(self, 'chk_compress'):
            self.chk_compress.setChecked(self._compress)
        last    = state.get("last")
        records = state.get("playlists", [])
        for rec in records:
            p = Path(rec["path"])
            if not p.exists():
                continue
            pl = next((pl for pl in scanner.scan_playlists(p.parent, False) if pl.path == p), None)
            if pl:
                hist_name = history.load(p).get("display_name", p.stem)
                pl.name = rec.get("name", hist_name)
                self._playlists.append(pl)
                self.list_playlists.addItem(pl.name)
        if last:
            self._cur_pl_idx = next((i for i, pl in enumerate(self._playlists) if str(pl.path) == last), None)
            self._highlight_row()

    def _save_state(self):
        last = str(self._player._pl_path) if self._player._pl_path else (
            str(self._playlists[self._cur_pl_idx].path) if self._cur_pl_idx is not None else None)
        self._auto_resume = self.chk_resume.isChecked()
        self._normalize   = self.chk_normalize.isChecked()
        self._compress    = self.chk_compress.isChecked()
        state = {
            "playlists": [{"path": str(pl.path), "name": pl.name} for pl in self._playlists],
            "last": last,
            "auto_resume": self._auto_resume,
            "normalize": self._normalize,
            "compress": self._compress,
            "theme": self._theme,
        }
        storage.save(state)
        for pl in self._playlists:
            history.ensure_name(pl.path, pl.name)

    # ═════════════════ 8. playlist management ═════════════════
    def _add_playlists(self,new:List[scanner.Playlist])->bool:
        added=False
        for pl in new:
            if all(pl.path!=o.path for o in self._playlists):
                self._playlists.append(pl); self.list_playlists.addItem(pl.name); added=True
        return added

    def _scan_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Choose folder")
        if folder and self._add_playlists(scanner.scan_playlists(Path(folder))): self._save_state()

    def _sel_pl(self)->Optional[scanner.Playlist]:
        idx=self.list_playlists.currentRow()
        return self._playlists[idx] if 0<=idx<len(self._playlists) else None

    def _rename_playlist(self):
        pl=self._sel_pl()
        if not pl: return
        new,ok=QInputDialog.getText(self,"Rename playlist","Display name:",text=pl.name)
        if ok and new.strip():
            pl.name=new.strip(); self.list_playlists.currentItem().setText(pl.name)
            history.ensure_name(pl.path,pl.name); self._save_state()

    def _delete_playlist(self):
        pl=self._sel_pl()
        if not pl: return
        if QMessageBox.question(self,"Delete playlist",f"Remove “{pl.name}” from list?\n(File stays on disk.)",
                                 QMessageBox.Yes|QMessageBox.No)==QMessageBox.Yes:
            i=self.list_playlists.currentRow()
            self.list_playlists.takeItem(i); self._playlists.pop(i)
            self._save_state(); self._refresh_sel()

    def _create_playlist(self):
        dlg=CreatePlaylistDialog(self)
        if dlg.exec()!=QDialog.Accepted: return
        tracks=dlg.tracks()
        if not tracks: return
        fname,_=QFileDialog.getSaveFileName(self,"Save playlist",
                                            str(Path.home()/"playlist.m3u8"),
                                            "M3U8 playlist (*.m3u8)")
        if not fname: return
        path=Path(fname)
        try: path.write_text("\n".join(tracks),encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Could not write playlist:\n{e}"); return
        pl=scanner.Playlist(path=path,name=path.stem,tracks=[Path(t) for t in tracks])
        if self._add_playlists([pl]): history.ensure_name(pl.path,pl.name); self._save_state()

    # ═════════════════ 9. list helpers ═════════════════
    def _make_item(self,p:Path,prefix:str=""):
        it=QListWidgetItem(prefix+self._display(p))
        if (ico:=self._icon48(p)): it.setIcon(ico)
        return it

    def _place_bar(self,bar:QFrame,lw:QListWidget,idx:int,frac:float):
        if not(0<=idx<lw.count()): bar.hide(); return
        rect=lw.visualItemRect(lw.item(idx)); width=lw.viewport().width()
        x=int(max(0,min(rect.left()+frac*rect.width(),width-2)))
        bar.setGeometry(x,rect.top(),2,rect.height()); bar.show()

    # ═════════════════ 10. refresh panes ═════════════════
    def _refresh_sel(self):
        self.tracks_sel.clear(); self._bar_sel.hide()
        pl=self._sel_pl()
        if not pl: return
        hist=history.load(pl.path)
        finished=set(hist.get("finished",[]))
        idx=hist.get("track_index",-1)
        pos=float(hist.get("position",0)); length=float(hist.get("length",0))
        if (length<=0 or length is None) and 0<=idx<len(pl.tracks):
            try:length=MFile(pl.tracks[idx]).info.length or 0
            except Exception:length=0
        frac=pos/max(1,length)
        for i,t in enumerate(pl.tracks):
            it=self._make_item(Path(t))
            if str(t) in finished: it.setForeground(QColor("gray"))
            if not Path(t).exists(): it.setForeground(QColor("red"))
            if i==idx: f=it.font(); f.setBold(True); it.setFont(f)
            self.tracks_sel.addItem(it)
        if pos>0 and 0<=idx<len(pl.tracks): self._place_bar(self._bar_sel,self.tracks_sel,idx,frac)

    def _refresh_cur(self):
        self.tracks_cur.clear(); self._bar_play.hide()
        if not self._player.playlist: return
        fin=set(history.load(self._player._pl_path).get("finished",[]))
        for i,t in enumerate(self._player.playlist):
            it=self._make_item(Path(t),"▶ " if i==self._player.idx else "")
            if i==self._player.idx:
                f=it.font(); f.setBold(True); it.setFont(f)
            if str(t) in fin: it.setForeground(QColor("gray"))
            if not Path(t).exists(): it.setForeground(QColor("red"))
            self.tracks_cur.addItem(it)
        self._place_play_bar()

    def _place_play_bar(self):
        if not self._player.player: self._bar_play.hide(); return
        length=max(1,self._player.length()); frac=self._player.position()/length
        self._place_bar(self._bar_play,self.tracks_cur,self._player.idx,frac)

    def _highlight_row(self):
        for r in range(self.list_playlists.count()):
            it=self.list_playlists.item(r); bold=r==self._cur_pl_idx
            it.setBackground(QColor(self._row_bg) if bold else Qt.transparent)
            f=it.font(); f.setBold(bold); it.setFont(f)

    # ═════════════════ 11. playback helper ═════════════════
    def _play_selected(self):
        pl=self._sel_pl()
        if pl:
            self._player.load_playlist(pl.path,pl.tracks)
            self.slider.setEnabled(True); self._player.play(); self._on_track_change()

    def _toggle_play(self):
        if self._player.player and self._player.player.is_playing(): self._player.pause()
        elif not self._player.player: self._play_selected()
        else: self._player.play()

    def _update_time_label(self,pos:float,length:float):
        self.lbl_time.setText(f"{int(pos)//60:02}:{int(pos)%60:02} / {int(length)//60:02}:{int(length)%60:02}")

    # ═════════════════ 12. timer tick ═════════════════
    def _tick(self):
        self._player.tick()
        if self._player.player:
            length=max(1,min(MAX_SECONDS,self._player.length()))
            pos=max(0,min(self._player.position(),length))
            if not self.slider.isSliderDown():
                self.slider.setMaximum(int(length*TICKS)); self.slider.setValue(int(pos*TICKS))
            self._update_time_label(pos,length); self._place_play_bar()
            sel_pl=self._sel_pl()
            if sel_pl and sel_pl.path==self._player._pl_path:
                self._place_bar(self._bar_sel,self.tracks_sel,self._player.idx,pos/length)

    # ═════════════════ 13. VLC callback ═════════════════
    def _on_track_change(self,*_):
        self.slider.setEnabled(True)
        self._cur_pl_idx=next((i for i,pl in enumerate(self._playlists) if pl.path==self._player._pl_path),None)
        cur=self._sel_pl(); self.lbl_curtitle.setText(cur.name if cur else "Now Playing")
        self._highlight_row(); self._refresh_cur(); self._refresh_sel()
        self.lbl_cover.setPixmap(self._cover(self._player.playlist[self._player.idx]) or QPixmap())

    # ═════════════════ 14. close ═════════════════
    def closeEvent(self,e):
        if keyboard and self._hotkey is not None:
            try: keyboard.remove_hotkey(self._hotkey)
            except Exception: pass
        self._player.close(); self._save_state(); super().closeEvent(e)

# ═════════════════ 15. entry-point ═════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    if ICON_PATH.exists(): app.setWindowIcon(QIcon(str(ICON_PATH)))
    win = MainWindow(); win.show()
    sys.exit(app.exec())
