@echo off
rem build_windows.bat  – package Playlist-Player via PyInstaller

set PY=python
if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
) else (
    echo [BUILD] Creating local venv...
    %PY% -m venv .venv || goto :error
    .venv\Scripts\python.exe -m pip install --upgrade pip
)

echo [BUILD] Ensuring PyInstaller is in the venv...
.venv\Scripts\python.exe -m pip install --quiet pyinstaller==6.*

echo [BUILD] Running PyInstaller...
.venv\Scripts\pyinstaller.exe ^
   --onefile ^
   --windowed ^
   --name PlaylistPlayer ^
   main.py || goto :error

echo [BUILD] Done!  See dist\PlaylistPlayer.exe
goto :eof

:error
echo BUILD FAILED
exit /b 1
