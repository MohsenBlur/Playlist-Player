@echo off
rem build_windows.bat – package Playlist-Player with custom icon

setlocal
set PY=python

if not exist ".venv\Scripts\python.exe" (
  echo [BUILD] Creating local venv...
  %PY% -m venv .venv || goto :err
  .venv\Scripts\python.exe -m pip install --upgrade pip
)

echo [BUILD] Installing build deps into venv...
.venv\Scripts\python.exe -m pip install --quiet ^
      pyinstaller==6.* PySide6 pillow mutagen python-vlc

echo [BUILD] Running PyInstaller...
.venv\Scripts\pyinstaller.exe ^
  --onefile --windowed ^
  --name PlaylistPlayer ^
  --icon Playlist-Player_logo.ico ^            rem ← NEW
  --hidden-import PySide6 ^
  --hidden-import PySide6.QtCore ^
  --hidden-import PySide6.QtGui ^
  --hidden-import PySide6.QtWidgets ^
  --hidden-import PySide6.QtNetwork ^
  --hidden-import mutagen.id3 ^
  --hidden-import vlc ^
  --collect-all PySide6 ^
  --collect-all PIL ^
  main.py || goto :err

echo.
echo  Build complete → dist\PlaylistPlayer.exe
goto :eof

:err
echo BUILD FAILED
exit /b 1
