"""Export a preview from the original v0.9 ICO without rewriting the master."""

from pathlib import Path

from PIL import Image

ICONS_DIR = Path(__file__).resolve().parents[1] / 'assets/icons'


def draw_eye_icon(size: int) -> Image.Image:
    with Image.open(ICONS_DIR / 'opencareyes.ico') as master:
        largest = max(master.ico.sizes(), key=lambda dimensions: dimensions[0])
        bitmap = master.ico.getimage(largest).convert('RGBA')
    return bitmap.resize((size, size), Image.Resampling.LANCZOS)


def main():
    draw_eye_icon(256).save(ICONS_DIR / 'app-icon.png')
    print('Exported app preview; preserved original v0.9 ICO and tray PNG masters.')


if __name__ == '__main__':
    main()
