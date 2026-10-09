"""Compose repository artwork from the original icon and shipped pet frames."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / 'assets/pets/snow_ferret'
OUT = ROOT / 'docs/images/project-home'
BG = '#E7EDEF'
TEXT = '#293A41'
SECONDARY = '#527A8B'


def font(size, *, chinese=False, bold=False):
    name = ('msyhbd.ttc' if bold else 'msyh.ttc') if chinese else (
        'seguisb.ttf' if bold else 'segoeui.ttf')
    return ImageFont.truetype(str(Path('C:/Windows/Fonts') / name), size)


def original_icon(size):
    with Image.open(ROOT / 'assets/icons/opencareyes.ico') as source:
        return source.ico.getimage((256, 256)).convert('RGBA').resize((size, size), Image.Resampling.LANCZOS)


def save_png(image, path, origin):
    info = PngImagePlugin.PngInfo()
    info.add_text('Source', origin)
    image.convert('RGB').save(path, optimize=True, pnginfo=info)


def banner(width, height, *, social=False):
    canvas = Image.new('RGBA', (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    margin = 80 if social else 78
    icon_size = 96
    canvas.alpha_composite(original_icon(icon_size), (margin, 84 if social else 77))
    draw.text((margin + 115, 98 if social else 93), 'OpenCareEyes',
              font=font(65 if social else 78, bold=True), fill=TEXT)
    draw.text((margin, 244 if social else 231), '休息一下，再继续。',
              font=font(49 if social else 57, chinese=True, bold=True), fill=TEXT)
    draw.text((margin, 330 if social else 331), '桌面伙伴 · 休息提醒 · 屏幕调节',
              font=font(27 if social else 32, chinese=True), fill=SECONDARY)
    if social:
        draw.text((margin, 492), 'Windows 10 / 11 · Free & open source',
                  font=font(24), fill=SECONDARY)
    with Image.open(PET / 'preview.png') as source:
        pet_size = 470 if social else 490
        pet = source.convert('RGBA').resize((pet_size, pet_size), Image.Resampling.LANCZOS)
    canvas.alpha_composite(pet, (width - pet_size - 20, (height-pet_size)//2))
    return canvas


def interaction_gif(manifest):
    frames, durations = [], []
    for action, label in (('click_reaction', '摸摸头'), ('play', '玩一会儿')):
        clip = manifest['actions'][action]
        for frame in clip['frames']:
            canvas = Image.new('RGB', (640, 466), BG)
            draw = ImageDraw.Draw(canvas)
            title_font = font(28, chinese=True, bold=True)
            text_width = draw.textlength(label, font=title_font)
            draw.text(((640-text_width)/2, 20), label, font=title_font, fill=TEXT)
            with Image.open(PET / frame['path']) as source:
                x, y, w, h = frame['source_rect']
                image = source.convert('RGBA').crop((x, y, x+w, y+h))
            canvas.paste(image, ((640-w)//2, 70), image)
            frames.append(canvas)
            durations.append(frame['duration_ms'])
        durations[-1] += 600
    # A shared palette keeps the canvas and fur colours stable across clips.
    samples = Image.new('RGB', (160 * len(frames), 117), BG)
    for index, frame in enumerate(frames):
        samples.paste(frame.resize((160, 117)), (index*160, 0))
    palette = samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    indexed[0].save(OUT / 'interactions.gif', save_all=True, append_images=indexed[1:],
                    duration=durations, loop=0, disposal=2, optimize=False,
                    comment=b'Shipped b11 click_reaction and play frames; captioned asset preview, not an OS screen recording.')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    origin = ('Locally composed flat layout using v0.9 assets/icons/opencareyes.ico and '
              'assets/pets/snow_ferret/preview.png. No character edits or generated UI.')
    save_png(banner(1600, 520), OUT / 'cover.png', origin)
    save_png(banner(1280, 640, social=True), OUT / 'social-preview.png', origin)
    interaction_gif(json.loads((PET / 'manifest.json').read_text(encoding='utf-8')))


if __name__ == '__main__':
    main()
