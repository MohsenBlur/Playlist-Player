@echo off
rem build_windows.bat  – package Playlist-Player with PyInstaller
rem Creates a local .venv, installs PyInstaller & runtime deps, then
rem builds a single-file, windowed EXE in dist\PlaylistPlayer.exe

setlocal
set PY=python

if not exist ".venv\Scripts\python.exe" (
  echo [BUILD] Creating venv ...
  %PY% -m venv .venv || goto :err
  .venv\Scripts\python.exe -m pip install --upgrade pip
)

echo [BUILD] Installing build deps into venv ...
.venv\Scripts\python.exe -m pip install --quiet ^
      pyinstaller==6.* PySide6 mutagen pillow python-vlc

echo [BUILD] Running PyInstaller ...
.venv\Scripts\pyinstaller.exe ^
  --onefile --windowed ^
  --name PlaylistPlayer ^
  --collect-all PySide6 ^
  --collect-all PIL ^
  --hidden-import PySide6.QtCore ^
  --hidden-import PySide6.QtGui ^
  --hidden-import PySide6.QtWidgets ^
  --hidden-import PySide6.QtNetwork ^
  --hidden-import vlc ^
  --hidden-import mutagen.id3 ^
  main.py || goto :err

echo.
echo  Build complete!  dist\PlaylistPlayer.exe
goto :eof

:err
echo BUILD FAILED
exit /b 1
