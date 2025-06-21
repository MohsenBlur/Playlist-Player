@echo off
REM build_windows.bat - Package Playlist-Player for Windows using PyInstaller

REM Ensure PyInstaller is installed
python -m pip install pyinstaller

REM Build a single-file, windowed executable
pyinstaller --onefile --windowed --name PlaylistPlayer main.py

