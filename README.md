# Playlist-Player
![Playlist-Player logo](Playlist-Player_logo.png)

A minimal, Python-Qt music player that opens **`.m3u / .m3u8 / .fplite`** playlists and plays them gap-lessly through VLC, and remembers playback history and position (per playlist).

---

## Features
* **Folder scan** – add all playlists beneath a chosen directory  
* **Gap-less playback** – powered by libVLC  
* **Per-playlist history** – resumes where you left off  
* **Embedded cover-art** – JPEG / PNG extracted automatically  
* **Timeline seek** – click, drag or mouse-wheel (± 5 s, *Ctrl* ± 1 s)
* **Light / Dark mode** – follows your OS theme
* **Play/Pause hotkey** – responds to the global media key

---

## Quick Start

## 1 - [DOWNLOAD Playlist-Player.exe](https://github.com/MohsenBlur/Playlist-Player/releases/tag/v0.25.06.21)
## 2 - [Install VLC](https://www.videolan.org/vlc/) (If you're not planning on using VLC for anything else, at "Choose Components" step, uncheck everything)
## 3 - Put Playlist-Player.exe anywhere you want
## 4 - Run Playlist-Player.exe
### 5 - Either just drag-and-drop playlists into the window, or use SCAN (it scans for playlists in a folder and all folders within it) or CREATE your own playlists


---

## To run the script instead of binary:


```bash
git clone https://github.com/your-name/playlist-player.git
cd playlist-player
python main.py          # first run sets up a local .venv
# alternatively install dependencies manually:
pip install -r requirements.txt
python main.py
````
or
````
Download as ZIP, make sure python and VLC are installed and double-click main.py
````

### First-run bootstrap

On first launch the script creates **`.venv/`** beside itself and installs:

* `PySide6` – Qt GUI bindings
* `python-vlc` – VLC Python wrapper
* `mutagen` – tag & cover-art reader
* `Pillow` – image helpers
* `keyboard` – global hotkey listener

You do **not** need to install these manually.

---

## Dependencies

| Requirement          | Notes                                                                             |
| -------------------- | --------------------------------------------------------------------------------- |
| **Python ≥ 3.8**     | 3.9 – 3.12 tested                                                                 |
| **VLC media player** | Desktop build (64-bit) – [download](https://www.videolan.org/vlc/)                |
| libVLC path          | Found automatically on Windows; set env var **`VLC_PATH`** if VLC lives elsewhere |

---

## Basic Usage

1. Click **Scan** and choose a folder → playlists appear on the left (or Drag and drop playlists into window).
  
2. Double-click a playlist to start playback.
3. **Prev/Next** (top-right) switch tracks.
4. Drag / wheel the timeline to seek.
5. Close the app – play positions & custom names are saved automatically.

---

## File Tree

```
playlist-player/
├─ main.py          # GUI + bootstrap
├─ player.py        # gap-less VLC wrapper
├─ scanner.py       # playlist discovery
├─ history.py       # per-playlist progress
├─ storage.py       # saved playlist list
└─ .venv/           # local virtual-env (auto)
```

---

## Windows Packaging

Run the provided **`build_windows.bat`** script to create a standalone
executable using PyInstaller:

```cmd
build_windows.bat
```

The resulting **`dist/PlaylistPlayer.exe`** can be distributed without
requiring Python on the target system.

---

## License

MIT – free to use, modify, and distribute.
