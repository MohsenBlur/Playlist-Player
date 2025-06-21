@echo off
:: ============================================================
:: Playlist-Player — Windows standalone build script
:: Creates a fresh multi-resolution icon and bundles a one-file EXE.
::
:: Prerequisites
::   • Python 3.x in PATH  (py launcher on Windows)
::   • make_icon.py        (PNG-to-ICO helper in project root)
::
:: The resulting EXE appears in  dist\Playlist-Player.exe
:: ============================================================

setlocal EnableExtensions
cd /d "%~dp0"

REM ────────────────────────────────────────────────
REM Step 0 : generate high-DPI multi-resolution icon
REM           (16,24,32,48,64,128,256-px layers)
REM ────────────────────────────────────────────────
py -3 make_icon.py
if errorlevel 1 goto :error

REM ────────────────────────────────────────────────
REM Step 1 : install / upgrade PyInstaller
REM ────────────────────────────────────────────────
py -3 -m pip install --upgrade --quiet pyinstaller
if errorlevel 1 goto :error

REM ────────────────────────────────────────────────
REM Step 2 : build GUI executable
REM ────────────────────────────────────────────────
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
if errorlevel 1 goto :error

echo.
echo ✓ Build succeeded!  Find your app at dist\Playlist-Player.exe
pause
endlocal
exit /b 0

:error
echo.
echo BUILD FAILED
pause
endlocal
exit /b 1
