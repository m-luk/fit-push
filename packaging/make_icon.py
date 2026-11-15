"""Draw the fit-push logo (app/static/logo.svg) as a multi-size .ico / .png with Pillow.

The shapes mirror logo.svg (100 x 100 user units); keep the two in sync.
``python packaging/make_icon.py OUT.ico [OUT.png]``
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ORANGE = (238, 90, 44, 255)
WHITE = (255, 255, 255, 255)
LIMBS = [
    [(56, 35), (47, 55)],
    [(54, 39), (63, 46), (71, 40)],
    [(54, 39), (44, 43), (39, 51)],
    [(47, 55), (58, 62), (55, 76)],
    [(47, 55), (39, 66), (28, 67)],
]
NODES = [(61, 25, 6.5), (47, 55, 6), (58, 62, 4.5), (39, 51, 4.5), (28, 67, 4.5)]
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(size: int = 1024) -> Image.Image:
    k = size / 100

    def s(v: float) -> float:
        return v * k

    diamond = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(diamond).rounded_rectangle([s(17), s(17), s(83), s(83)], radius=s(11), fill=ORANGE)
    img = diamond.rotate(45, resample=Image.Resampling.BICUBIC, center=(s(50), s(50)))
    d = ImageDraw.Draw(img)
    w, r = round(s(5)), s(2.5)
    for limb in LIMBS:
        pts = [(s(x), s(y)) for x, y in limb]
        d.line(pts, fill=WHITE, width=w, joint="curve")
        for x, y in pts:  # round caps and joins
            d.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)
    for x, y, rad in NODES:
        d.ellipse([s(x - rad), s(y - rad), s(x + rad), s(y + rad)], fill=WHITE)
    return img


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    big = render()
    for out in map(Path, argv):
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() == ".ico":
            big.resize((256, 256), Image.Resampling.LANCZOS).save(out, sizes=[(n, n) for n in SIZES])
        else:
            big.resize((512, 512), Image.Resampling.LANCZOS).save(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
