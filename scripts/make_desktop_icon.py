"""Export the Windows icon from the approved shared application artwork."""
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'assets'
OUTPUT.mkdir(exist_ok=True)

with Image.open(OUTPUT / 'desktop-icon.png') as source:
    canvas = source.convert('RGBA')
canvas.save(OUTPUT / 'desktop.ico', format='ICO', sizes=[(16, 16), (24, 24), (32, 32),
                                                        (48, 48), (64, 64), (128, 128), (256, 256)])
