"""Generate the Windows icon from the existing library colors."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'assets'
OUTPUT.mkdir(exist_ok=True)

canvas = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(canvas)
draw.rounded_rectangle((8, 8, 248, 248), radius=30, fill='#1e3931')
draw.rectangle((28, 31, 35, 225), fill='#c85d3b')

fonts = [
    Path('C:/Windows/Fonts/NotoSerifJP-VF.ttf'),
    Path('C:/Windows/Fonts/yumin.ttf'),
    Path('C:/Windows/Fonts/msmincho.ttc'),
]
font_path = next((path for path in fonts if path.is_file()), None)
if font_path is None:
    raise FileNotFoundError('需要 Windows 日文字体生成桌面图标。')
font = ImageFont.truetype(str(font_path), 168)
draw.text((143, 129), '富', font=font, fill='#fffef9', anchor='mm')

canvas.save(OUTPUT / 'desktop-icon.png')
canvas.save(OUTPUT / 'desktop.ico', format='ICO', sizes=[(16, 16), (24, 24), (32, 32),
                                                        (48, 48), (64, 64), (128, 128), (256, 256)])
