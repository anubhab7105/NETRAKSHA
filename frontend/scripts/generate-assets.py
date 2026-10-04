#!/usr/bin/env python3
"""Generate Netraksha brand assets for the web frontend.

Outputs (written into frontend/public):
  favicon.svg          - copy of the hand-authored SVG mark (kept in sync here)
  favicon.ico          - 16/32/48 px legacy icon
  favicon-32x32.png    - PNG fallback icon
  apple-touch-icon.png - 180x180 iOS home-screen icon
  og-image.png         - 1200x630 social share card (Open Graph / Twitter)

Run from the frontend directory:
    python scripts/generate-assets.py

Requires only Pillow (already used by the screening pipeline).
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.normpath(os.path.join(HERE, "..", "public"))


BACKGROUND = (15, 23, 42)
PRIMARY = (59, 130, 246)
ACCENT = (139, 92, 246)
TEXT = (241, 245, 249)
MUTED = (148, 163, 184)

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Netraksha">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3B82F6"/>
      <stop offset="1" stop-color="#8B5CF6"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="#0F172A"/>
  <path d="M32 7.5 50 14v14c0 11.4-7.9 21.7-18 25.5C21.9 49.7 14 39.4 14 28V14Z" fill="url(#g)"/>
  <path d="m23.5 31.8 5.6 5.6 11-11" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def shield_geometry(size):
    """Return (shield polygon bbox-relative points, check polyline) in a unit
    box scaled to `size`. Points mirror the SVG paths above."""
    def px(x, y):
        return (x * size, y * size)

    top_l = px(14 / 64, 14 / 64)
    top_r = px(50 / 64, 14 / 64)
    apex = px(32 / 64, 7.5 / 64)
    bot = px(32 / 64, 53.5 / 64)
    join_y = px(0, 28 / 64)[1]


    pts = [apex, top_l]
    steps = 40
    for i in range(steps + 1):
        t = i / steps
        y = join_y + (bot[1] - join_y) * t

        x_left = top_l[0] + (bot[0] - top_l[0]) * (t * t)
        pts.append((x_left, y))
    pts.append(bot)
    for i in range(steps, -1, -1):
        t = i / steps
        y = join_y + (bot[1] - join_y) * t
        x_right = top_r[0] + (bot[0] - top_r[0]) * (t * t)
        pts.append((x_right, y))
    pts.append(top_r)

    check = [px(23.5 / 64, 31.8 / 64), px(29.1 / 64, 37.4 / 64), px(40.1 / 64, 26.4 / 64)]
    return pts, check


def vertical_gradient(size, top, bottom):
    """Diagonal-ish gradient image of `size` (w, h) blending top->bottom."""
    w, h = size
    base = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        base.putpixel(
            (0, y),
            tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)),
        )
    return base.resize((w, h), Image.BICUBIC)


def draw_mark(size, pad_ratio=0.0):
    """Render the full app icon (tile + shield + check) at `size` px."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = round(size * (14 / 64))
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BACKGROUND + (255,))


    inner = size - 2 * round(size * pad_ratio)
    shield_mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(shield_mask)
    poly, check = shield_geometry(size)
    md.polygon(poly, fill=255)

    grad = vertical_gradient((size, size), PRIMARY, ACCENT).convert("RGBA")
    img.paste(grad, (0, 0), shield_mask)


    stroke = max(round(size * 4.5 / 64), 1)
    d = ImageDraw.Draw(img)
    d.line(check, fill=(255, 255, 255, 255), width=stroke, joint="curve")
    r = stroke / 2
    for pt in (check[0], check[-1]):
        d.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=(255, 255, 255, 255))
    return img


def load_font(names, size):
    for name in names:
        for folder in (os.environ.get("WINDIR", r"C:\Windows") + r"\Fonts",):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def glow(canvas, center, radius, color, alpha=110):
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.ellipse(
        [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius],
        fill=color + (alpha,),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius * 0.55))
    canvas.alpha_composite(overlay)


def generate_og_image(path, domain=None):
    w, h = 1200, 630
    img = Image.new("RGBA", (w, h), BACKGROUND + (255,))
    glow(img, (-140, -160), 330, PRIMARY)
    glow(img, (w + 120, h + 160), 340, ACCENT)
    glow(img, (w - 180, 80), 200, PRIMARY, alpha=60)

    d = ImageDraw.Draw(img)


    tile = draw_mark(120)
    img.alpha_composite(tile, (96, 88))

    f_brand = load_font(["segoeuib.ttf", "arialbd.ttf"], 46)
    f_title = load_font(["segoeuib.ttf", "arialbd.ttf"], 88)
    f_sub = load_font(["segoeui.ttf", "arial.ttf"], 38)
    f_small = load_font(["segoeui.ttf", "arial.ttf"], 27)

    d.text((244, 118), "NETRAKSHA", font=f_brand, fill=TEXT)
    d.text((244, 172), "See. Verify. Secure.", font=f_small, fill=MUTED)

    d.text((96, 276), "AI Identity Document", font=f_title, fill=TEXT)
    d.text((96, 384), "Screening", font=f_title, fill=TEXT)
    tagline = "Document forensics · 3-way biometric face match · Real-time verdicts"
    sub_size = 38
    while True:
        fitted = load_font(["segoeui.ttf", "arial.ttf"], sub_size)
        if d.textlength(tagline, font=fitted) <= (w - 192) or sub_size <= 20:
            break
        sub_size -= 2
    d.text((96, 500), tagline, font=fitted, fill=MUTED)

    d.line([(96, 568), (w - 96, 568)], fill=(51, 65, 85, 255), width=2)
    d.text((96, 586), "Ministry of Home Affairs · Sashastra Seema Bal", font=f_small, fill=MUTED)
    domain = domain or resolve_domain()
    tw = d.textlength(domain, font=f_small)
    d.text((w - 96 - tw, 586), domain, font=f_small, fill=(100, 116, 139))

    img.convert("RGB").save(path, "PNG", optimize=True)


def resolve_domain():
    """Footer domain: --domain > VITE_SITE_URL host > legacy default."""
    import re
    raw = os.environ.get("VITE_SITE_URL", "").strip()
    if raw:
        host = re.sub(r'^https?://', '', raw).split('/')[0].strip()
        if host:
            return host
    return "sih-weld-psi.vercel.app"


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Generate Netraksha brand assets.")
    ap.add_argument("--domain", default=None,
                    help="Domain printed on the og-image footer (default: VITE_SITE_URL host or sih-weld-psi.vercel.app).")
    args = ap.parse_args()

    os.makedirs(PUBLIC, exist_ok=True)

    with open(os.path.join(PUBLIC, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write(FAVICON_SVG)

    master = draw_mark(512)
    master.resize((32, 32), Image.LANCZOS).save(
        os.path.join(PUBLIC, "favicon-32x32.png"), "PNG", optimize=True
    )
    master.resize((180, 180), Image.LANCZOS).save(
        os.path.join(PUBLIC, "apple-touch-icon.png"), "PNG", optimize=True
    )
    master.save(
        os.path.join(PUBLIC, "favicon.ico"),
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )

    generate_og_image(os.path.join(PUBLIC, "og-image.png"), domain=args.domain)
    print("Generated brand assets in", PUBLIC)


if __name__ == "__main__":
    main()
