#!/usr/bin/env python3
"""
make_icon.py
────────────
Convert Playlist-Player_logo.png (≥ 512 × 512) into a multi-resolution
ICO containing all common Windows sizes:

  16, 24, 32, 48, 64, 128, 256, **512**  px

The ≥ 256-px layers are PNG-compressed inside the ICO, which Windows 10/11
and Explorer accept.  Run this once before PyInstaller.
"""

from pathlib import Path
from PIL import Image

SRC   = Path("Playlist-Player_logo.png")   # high-res master
DEST  = Path("Playlist-Player_logo.ico")   # output
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]

def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"❌ {SRC} not found")

    img = Image.open(SRC).convert("RGBA")          # keep alpha
    # Pillow ≥ 9.2: pass *all* sizes; it will embed each as PNG/BMP as needed
    img.save(DEST,
             format="ICO",
             sizes=[(s, s) for s in SIZES])

    print("✓ Multi-resolution ICO written →", DEST)

if __name__ == "__main__":
    main()
