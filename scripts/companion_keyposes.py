"""Register complete, drawn action poses to one desktop canvas.

The illustrations contain the whole animal. No arm or neck is cut out, and
registration never stretches a limb to manufacture a new pose.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CELL = 384
BODY_X = 192
FLOOR_Y = 348


def register(pose, anchor_x, floor_y, scale):
    bitmap = Image.new('RGBA', (CELL, CELL))
    size = (round(pose.width * scale), round(pose.height * scale))
    bitmap.alpha_composite(pose.resize(size, Image.Resampling.LANCZOS),
                           (round(BODY_X - anchor_x * scale), round(FLOOR_Y - floor_y * scale)))
    return bitmap


class CompletePoses:
    def __init__(self):
        folder = ROOT / 'artwork/companion'
        with Image.open(folder / 'greeting-keyposes-v4.png') as image:
            sheet = image.convert('RGBA')
        # Source art was inspected at cell and actual desktop sizes. The foot
        # baselines and body axes below remove sheet-layout drift, while head
        # inclination and the full paw arc stay exactly as drawn.
        self.greeting = []
        for index, (axis, floor) in enumerate(((259, 488), (249, 488), (251, 488),
                                               (257, 482), (249, 482), (239, 482))):
            x, y = index % 3 * 512, index // 3 * 512
            pose = sheet.crop((x, y, x + 512, y + 512))
            self.greeting.append(register(pose, axis, floor, 316 / 456))
        with Image.open(folder / 'walk-keyposes-v4.png') as image:
            sheet = image.convert('RGBA')
        self.walk = []
        # Four complete animal poses form a light trot. Keeping one source
        # scale preserves head size; only the sheet-layout baseline is aligned.
        for index, floor in enumerate((491, 497, 421, 430)):
            col, row = index % 2, index // 2
            pose = sheet.crop((col * sheet.width // 2, row * sheet.height // 2,
                               (col + 1) * sheet.width // 2, (row + 1) * sheet.height // 2))
            self.walk.append(register(pose, 390, floor, 334 / 738))
        with Image.open(folder / 'gaze-keyposes-v5.png') as image:
            sheet = image.convert('RGBA')
        self.gaze = {}
        for index, direction in enumerate((
            'up_left', 'up', 'up_right', 'left', 'center', 'right',
            'down_left', 'down', 'down_right',
        )):
            col, row = index % 3, index // 3
            pose = sheet.crop((col * 418, row * 418, (col + 1) * 418, (row + 1) * 418))
            # The body axis and foot baseline are shared by all nine complete
            # poses. Head yaw/pitch remain as drawn; no raster head rotation.
            self.gaze[direction] = register(pose, 209, 393, 316 / 370)
        with Image.open(folder / 'walk-keyposes-v6.png') as image:
            sheet = image.convert('RGBA')
        self.walk = []
        for index, floor in enumerate((457, 457, 378, 378)):
            x, y = index % 2 * 768, index // 2 * 512
            pose = sheet.crop((x, y, x + 768, y + 512))
            self.walk.append(register(pose, 395 if index % 2 == 0 else 372, floor, 316 / 640))
        with Image.open(folder / 'stretch-sequence-v8.png') as image:
            sheet = image.convert('RGBA')
        self.stretch_sequence = []
        for index, (axis, floor) in enumerate(((257, 493), (237, 492), (255, 493),
                                               (257, 485), (238, 485), (256, 485))):
            x, y = index % 3 * 512, index // 3 * 512
            pose = sheet.crop((x, y, x + 512, y + 512))
            self.stretch_sequence.append(register(pose, axis, floor, 316 / 470))
