"""
Build the small ghost sprites for the map from the source artwork.

    uv run --with pillow --with numpy apps/grandma-ghost/make_ghost_image.py <source.jpg>

Writes static/ghost.png (cyan) and static/ghost-red.png (used while a fall is flagged).
The source is a 1374x766 particle-hologram ghost on a black background. The black
becomes transparent, so only the glow is left, and the bottom edge fades out so the
ghost floats instead of being cut off.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Crop around the figure in the 1374x766 source (left, top, right, bottom)
CROP = (400, 30, 1030, 766)
OUT_H = 220                      # about 2x the displayed size, for sharp screens
OUT_DIR = Path(__file__).parent / "static"


def build(src: Path) -> None:
    img = Image.open(src).convert("RGB").crop(CROP)
    img = img.resize((round(img.width * OUT_H / img.height), OUT_H), Image.LANCZOS)
    rgb = np.asarray(img).astype(np.float32)

    # Transparency from brightness: black -> clear, bright particles -> opaque
    lum = rgb.max(axis=2)
    # (the cutoff is above the source's dark teal background haze, so none of it survives)
    alpha = np.clip((lum - 38.0) * 2.8, 0, 255)

    # Soft fade at the bottom and sides
    h, w = alpha.shape
    ys = np.linspace(0, 1, h)[:, None]
    xs = np.linspace(0, 1, w)[None, :]
    fade_bottom = np.clip((1.0 - ys) / 0.22, 0, 1)
    fade_sides = np.clip(np.minimum(xs, 1 - xs) / 0.10, 0, 1)
    alpha = alpha * fade_bottom * fade_sides

    def save(channels: np.ndarray, name: str) -> None:
        out = np.dstack([channels, alpha]).clip(0, 255).astype(np.uint8)
        Image.fromarray(out, "RGBA").save(OUT_DIR / name, optimize=True)
        print(f"{name}: {(OUT_DIR / name).stat().st_size / 1024:.0f} KB, {w}x{h}")

    save(rgb, "ghost.png")

    # Red version for a fall: keep the brightness pattern, move it into the red channel
    # (swapping red and blue would turn cyan into yellow, not red)
    mean = rgb.mean(axis=2)
    red = np.dstack([lum, mean * 0.22, mean * 0.34])
    save(red, "ghost-red.png")

    # Preview on the dark map colour, to check how it will look in the page
    bg = np.array([4, 4, 6], dtype=np.float32)
    a = (alpha / 255.0)[:, :, None]
    both = np.concatenate([rgb * a + bg * (1 - a), red * a + bg * (1 - a)], axis=1)
    Image.fromarray(both.clip(0, 255).astype(np.uint8)).save(OUT_DIR / "_preview.png")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
