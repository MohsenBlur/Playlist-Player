@echo off
:: Playlist-Player — Windows standalone build
:: Prerequisite:  PyInstaller  (py -m pip install pyinstaller)

setlocal EnableExtensions
cd /d "%~dp0"

rem ─────────────────────────────────────────────────────────────
rem 1) ensure PyInstaller is installed / up-to-date
rem ─────────────────────────────────────────────────────────────
py -3 -m pip install --upgrade --quiet pyinstaller

rem ─────────────────────────────────────────────────────────────
rem 2) build
rem     --onefile       single EXE
rem     --noconsole     hide console window
rem     --clean         wipe older build cache
rem     --icon          embed Playlist-Player_logo.ico
rem     --add-data      copy the icon next to the EXE at runtime
rem     --hidden-import pull-in modules PyInstaller sometimes misses
rem ─────────────────────────────────────────────────────────────
py -3 -m PyInstaller ^
  --name "Playlist-Player" ^
  --onefile ^
  --noconsole ^
  --clean ^
  --icon "Playlist-Player_logo.ico" ^
  --add-data "Playlist-Player_logo.ico;." ^
  --hidden-import mutagen ^
  --hidden-import PIL.Image ^
  main.py

if errorlevel 1 (
    echo(
    echo BUILD FAILED
    pause
    exit /b %errorlevel%
)

echo(
echo Done!  See dist\Playlist-Player.exe
pause
endlocal
