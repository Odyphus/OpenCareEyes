"""Generate application icon files for OpenCareEyes."""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")


def draw_eye_icon(size: int) -> Image.Image:
    """Draw a simple stylized eye icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = size // 8
    cx, cy = size // 2, size // 2

    # Eye shape (ellipse)
    eye_w = size - pad * 2
    eye_h = int(eye_w * 0.5)
    eye_bbox = (pad, cy - eye_h // 2, pad + eye_w, cy + eye_h // 2)

    # Outer eye (white fill with blue border)
    draw.ellipse(eye_bbox, fill=(240, 245, 255, 255), outline=(70, 130, 220, 255), width=max(1, size // 16))

    # Iris (blue circle)
    iris_r = int(eye_h * 0.38)
    iris_bbox = (cx - iris_r, cy - iris_r, cx + iris_r, cy + iris_r)
    draw.ellipse(iris_bbox, fill=(70, 130, 220, 255))

    # Pupil (dark circle)
    pupil_r = int(iris_r * 0.45)
    pupil_bbox = (cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r)
    draw.ellipse(pupil_bbox, fill=(20, 30, 60, 255))

    # Highlight (small white dot)
    hl_r = max(1, int(pupil_r * 0.4))
    hl_x = cx - int(iris_r * 0.25)
    hl_y = cy - int(iris_r * 0.25)
    draw.ellipse((hl_x - hl_r, hl_y - hl_r, hl_x + hl_r, hl_y + hl_r), fill=(255, 255, 255, 230))

    return img


def main():
    os.makedirs(ICONS_DIR, exist_ok=True)

    # Generate .ico with multiple sizes
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw_eye_icon(s) for s in sizes]

    ico_path = os.path.join(ICONS_DIR, "opencareyes.ico")
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Created {ico_path}")

    # Tray icon (32x32 PNG)
    tray_path = os.path.join(ICONS_DIR, "tray_normal.png")
    images[2].save(tray_path, format="PNG")  # 32x32
    print(f"Created {tray_path}")


if __name__ == "__main__":
    main()
