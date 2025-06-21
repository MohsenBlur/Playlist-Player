@echo off
:: Playlist-Player — Windows standalone build
:: Requires Python 3.x and PyInstaller (`py -m pip install pyinstaller`)

setlocal enableextensions
cd /d "%~dp0"

rem -----------------------------------------------------------------
rem Step 1: make sure PyInstaller is available
rem -----------------------------------------------------------------
py -3 -m pip install --upgrade --quiet pyinstaller

rem -----------------------------------------------------------------
rem Step 2: build
rem  * --onefile      → single EXE
rem  * --noconsole    → GUI app (no black console window)
rem  * --clean        → start from a fresh build dir
rem  * --add-data     → include icon next to the exe             (src;dest)
rem  * --hidden-import→ modules that PyInstaller misses (mutagen, Pillow)
rem -----------------------------------------------------------------
py -3 -m PyInstaller ^
  --name "Playlist-Player" ^
  --onefile ^
  --noconsole ^
  --clean ^
  --add-data "Playlist-Player_logo.ico;." ^
  --hidden-import mutagen ^
  --hidden-import PIL.Image ^
  main.py

if %errorlevel% neq 0 (
    echo(
    echo BUILD FAILED
    pause
    exit /b %errorlevel%
)

echo(
echo Done!  The standalone EXE is in ^"dist\Playlist-Player.exe^"
pause
endlocal
