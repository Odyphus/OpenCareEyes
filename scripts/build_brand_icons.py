"""Build Windows icon sizes from editable app and tray SVG masters."""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ICONS_DIR = Path(__file__).resolve().parents[1] / 'assets/icons'


def render_svg(name, size, color=None):
    svg = (ICONS_DIR / name).read_text(encoding='utf-8')
    if color:
        svg = svg.replace('currentColor', color)
    image = QImage(size * 4, size * 4, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    bitmap = Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits()))
    return bitmap.resize((size, size), Image.Resampling.LANCZOS)


def draw_eye_icon(size: int) -> Image.Image:
    return render_svg('app-mark.svg', size)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    image = draw_eye_icon(256)
    image.save(ICONS_DIR / 'opencareyes.ico', format='ICO', sizes=[(s, s) for s in sizes])
    image.save(ICONS_DIR / 'app-icon.png')
    for theme, color in (('light', '#203E4A'), ('dark', '#E5EEE8')):
        render_svg('tray.svg', 32, color).save(ICONS_DIR / f'tray_{theme}.png')
    render_svg('tray.svg', 32, '#203E4A').save(ICONS_DIR / 'tray_normal.png')
    print('Built app icon (7 sizes) and light/dark monochrome tray icons.')


if __name__ == '__main__':
    main()
