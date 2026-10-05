"""Draws the app icon (purple rounded square with sound bars) as a macOS .iconset."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int) -> Image.Image:
    s = 1024
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # macOS icon grid: ~824px rounded square centred on a 1024 canvas.
    m = 100
    top, bottom = (110, 92, 230), (75, 58, 196)
    for y in range(m, s - m):
        t = (y - m) / (s - 2 * m)
        col = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        d.line([(m, y), (s - m, y)], fill=col)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, s - m, s - m], radius=185, fill=255)
    img.putalpha(mask)
    # Sound bars
    bars = [(330, 0.36), (430, 0.62), (530, 0.36), (630, 0.18)]
    for x, h in bars:
        half = int((s - 2 * m) * h / 2)
        d.rounded_rectangle([x - 34 + 30, s // 2 - half, x + 34 + 30, s // 2 + half], radius=34, fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        draw(base).save(out / f"icon_{base}x{base}.png")
        draw(base * 2).save(out / f"icon_{base}x{base}@2x.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
