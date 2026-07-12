"""Build the README demo GIF from deterministic page captures."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    names = ("overview", "display", "breaks", "focus", "automation", "settings")
    frames = [Image.open(args.input_dir / f"demo-{name}.png").convert("RGB") for name in names]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        args.output,
        save_all=True,
        append_images=frames[1:],
        duration=[5000] * len(frames),
        loop=0,
        optimize=True,
        disposal=2,
    )
    for frame in frames:
        frame.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
