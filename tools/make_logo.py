"""Generate the InsAuto app icon (PNG + ICO) into assets/.

Design: dark rounded square, six-segment gradient aperture ring, and
white aperture blades forming the iris opening (camera = content,
aperture = posting). Rendered at 4x and downscaled for smooth edges.

Run:
    python tools/make_logo.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
SS = 4     # supersample factor
S = 512    # final png size
W = S * SS

PALETTE = ["#FEDA75", "#FA7E1E", "#E1306C", "#C13584", "#833AB4", "#4F5BD5"]


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _polar(cx, cy, r, deg):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def build(size_px: int) -> Image.Image:
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    # rounded-square background, subtle vertical gradient
    top, bot = _hex("#161c28"), _hex("#0b0f16")
    grad = Image.new("RGBA", (W, W))
    gd = ImageDraw.Draw(grad)
    for y in range(W):
        gd.line([(0, y), (W, y)], fill=_lerp(top, bot, y / W) + (255,))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1],
                                           radius=int(W * 0.225), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    cx = cy = W / 2
    r_out = W * 0.335
    ring_w = int(W * 0.072)

    # six-segment colored ring, warm -> cool, starting at the top
    seg, gap = 60.0, 6.0
    for i, col in enumerate(PALETTE):
        start = i * seg + gap / 2 - 90
        end = (i + 1) * seg - gap / 2 - 90
        d.arc([cx - r_out, cy - r_out, cx + r_out, cy + r_out],
              start, end, fill=_hex(col) + (255,), width=ring_w)

    # iris: solid disc with a hexagonal opening (lens stop look)
    r_disc = r_out * 0.70
    r_hex = r_out * 0.26
    disc = (233, 239, 245, 250)
    d.ellipse([cx - r_disc, cy - r_disc, cx + r_disc, cy + r_disc], fill=disc)
    hex_pts = [_polar(cx, cy, r_hex, k * 60 + 25) for k in range(6)]
    d.polygon(hex_pts, fill=_hex("#0b0f16") + (255,))

    # soft center glow
    glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gd2 = ImageDraw.Draw(glow)
    gr = W * 0.11
    gd2.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=(255, 255, 255, 22))
    glow = glow.filter(ImageFilter.GaussianBlur(W * 0.035))
    img.alpha_composite(glow)

    return img.resize((size_px, size_px), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    build(512).save(OUT / "app_icon.png")
    build(256).save(OUT / "app_icon.ico", format="ICO",
                    sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                           (64, 64), (128, 128), (256, 256)])
    print("saved:", OUT / "app_icon.png", "and", OUT / "app_icon.ico")


if __name__ == "__main__":
    main()
