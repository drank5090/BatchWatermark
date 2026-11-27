"""Generate static SEO / PWA assets for the Web Edition (``web/``).

Outputs (all written into ``web/``):

* ``favicon.svg``                 – vector favicon (modern browsers)
* ``favicon.ico``                 – 16/32/48 px fallback for legacy browsers & crawlers
* ``apple-touch-icon.png``        – 180 px full-bleed icon for iOS home screen
* ``icons/icon-192.png``          – PWA manifest icon
* ``icons/icon-512.png``          – PWA manifest icon / JSON-LD logo
* ``icons/icon-maskable-512.png`` – PWA maskable icon (content inside 80 % safe zone)
* ``og-image.png``                – 1200x630 Open Graph / Twitter share card

Usage::

    uv run python scripts/generate_web_assets.py

Only Pillow is required (already a project dependency). CJK text on the share
card needs a Chinese font; Microsoft YaHei (Windows), PingFang (macOS) and
Noto Sans CJK (Linux) are probed in that order.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SCREENSHOT = ROOT / "docs" / "images" / "preview_main.png"

# Brand palette (mirrors web/styles.css "Studio Dark")
BG_DARK = (26, 31, 42)  # #1a1f2a
BG_APP = (22, 24, 29)  # #16181d
INNER = (31, 41, 55)  # #1f2937
ACCENT = (59, 130, 246)  # #3b82f6
ACCENT_DEEP = (37, 99, 235)  # #2563eb
ACCENT_SOFT = (147, 197, 253)  # #93c5fd
WHITE = (255, 255, 255)
TEXT = (229, 231, 235)
MUTED = (156, 163, 175)
GREEN = (110, 231, 183)

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="4" y="4" width="56" height="56" rx="14" fill="#1a1f2a" stroke="#3b82f6" stroke-width="3"/>
  <rect x="14" y="16" width="30" height="26" rx="4" fill="#1f2937" stroke="#93c5fd" stroke-width="2.5"/>
  <circle cx="44" cy="44" r="11" fill="#2563eb" stroke="#ffffff" stroke-width="2.5"/>
  <path d="M44 38 L39 45 A5 5 0 1 0 49 45 Z" fill="#ffffff"/>
</svg>
"""

SUPERSAMPLE = 8


# --------------------------------------------------------------------------- #
# Icon rendering (raster re-implementation of FAVICON_SVG)
# --------------------------------------------------------------------------- #
def _box(cx: float, cy: float, half_w: float, half_h: float, s: float, ox: float, oy: float):
    return [ox + (cx - half_w) * s, oy + (cy - half_h) * s, ox + (cx + half_w) * s, oy + (cy + half_h) * s]


def _draw_glyph(draw: ImageDraw.ImageDraw, s: float, ox: float, oy: float) -> None:
    """Draw the inner photo frame + droplet badge in 64-unit SVG coordinates."""
    # Photo frame: rect x=14 y=16 w=30 h=26 rx=4, stroke 2.5 centred on the path
    sw = 2.5
    draw.rounded_rectangle(
        _box(29, 29, 15 + sw / 2, 13 + sw / 2, s, ox, oy),
        radius=(4 + sw / 2) * s,
        fill=ACCENT_SOFT,
    )
    draw.rounded_rectangle(
        _box(29, 29, 15 - sw / 2, 13 - sw / 2, s, ox, oy),
        radius=max(0.0, (4 - sw / 2) * s),
        fill=INNER,
    )
    # Badge: circle cx=44 cy=44 r=11, white stroke 2.5
    draw.ellipse(_box(44, 44, 11 + sw / 2, 11 + sw / 2, s, ox, oy), fill=WHITE)
    draw.ellipse(_box(44, 44, 11 - sw / 2, 11 - sw / 2, s, ox, oy), fill=ACCENT_DEEP)
    # Droplet: triangle (44,38)-(39,45)-(49,45) + circle r=5 at (44,45)
    draw.polygon(
        [(ox + 44 * s, oy + 38 * s), (ox + 39 * s, oy + 45 * s), (ox + 49 * s, oy + 45 * s)],
        fill=WHITE,
    )
    draw.ellipse(_box(44, 45, 5, 5, s, ox, oy), fill=WHITE)


def render_icon(size: int, *, full_bleed: bool = False, safe_zone: float = 1.0) -> Image.Image:
    """Render the brand icon.

    ``full_bleed`` paints an opaque square background (iOS / maskable icons get
    their own platform mask). ``safe_zone`` shrinks the artwork so it fits in
    the central fraction of the canvas.
    """
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), BG_DARK + (255,) if full_bleed else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if full_bleed:
        # No outer tile: centre the glyph's own bounding box (x 12.75..56.25,
        # y 14.75..56.25 incl. strokes) and scale it into the safe zone.
        extent = 56.25 - 12.75
        s = big * safe_zone / extent
        ox = big / 2 - (12.75 + 56.25) / 2 * s
        oy = big / 2 - (14.75 + 56.25) / 2 * s
    else:
        s = big / 64
        ox = oy = 0.0
        sw = 3
        draw.rounded_rectangle(
            _box(32, 32, 28 + sw / 2, 28 + sw / 2, s, ox, oy), radius=(14 + sw / 2) * s, fill=ACCENT
        )
        draw.rounded_rectangle(
            _box(32, 32, 28 - sw / 2, 28 - sw / 2, s, ox, oy), radius=(14 - sw / 2) * s, fill=BG_DARK
        )

    _draw_glyph(draw, s, ox, oy)
    return img.resize((size, size), Image.Resampling.LANCZOS)


# --------------------------------------------------------------------------- #
# Open Graph share card
# --------------------------------------------------------------------------- #
FONT_CANDIDATES = {
    "bold": [
        "C:/Windows/Fonts/msyhbd.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ],
    "regular": [
        "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ],
}


def load_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES[weight]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(f"No CJK font found for weight={weight!r}; edit FONT_CANDIDATES.")


def vertical_gradient(w: int, h: int, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        grad.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return grad.resize((w, h))


def pill(draw: ImageDraw.ImageDraw, xy, text, font, fg, bg, border) -> int:
    x, y = xy
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    pad_x, pad_y = 18, 10
    w = r - l + pad_x * 2
    h = b - t + pad_y * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg, outline=border, width=2)
    draw.text((x + pad_x - l, y + pad_y - t), text, font=font, fill=fg)
    return x + w


def render_og_image() -> Image.Image:
    W, H = 1200, 630
    card = vertical_gradient(W, H, (20, 22, 27), (17, 27, 48)).convert("RGBA")

    # Soft accent glow behind the screenshot
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([640, 60, 1300, 640], fill=ACCENT + (70,))
    card.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))

    # Product screenshot in a framed window, bleeding off the right edge
    if SCREENSHOT.exists():
        shot = Image.open(SCREENSHOT).convert("RGB")
        target_w = 640
        shot = shot.resize((target_w, round(shot.height * target_w / shot.width)), Image.Resampling.LANCZOS)
        sx, sy = 640, (H - shot.height) // 2 + 10
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [sx - 6, sy - 2, sx + shot.width + 16, sy + shot.height + 24], radius=18, fill=(0, 0, 0, 170)
        )
        card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
        mask = Image.new("L", shot.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, shot.width, shot.height], radius=14, fill=255)
        card.paste(shot, (sx, sy), mask)
        ImageDraw.Draw(card).rounded_rectangle(
            [sx, sy, sx + shot.width, sy + shot.height], radius=14, outline=(56, 63, 78), width=2
        )

    draw = ImageDraw.Draw(card)

    # Brand row
    icon = render_icon(72)
    card.alpha_composite(icon, (64, 64))
    brand_font = load_font("bold", 40)
    draw.text((152, 74), "BatchWatermark", font=brand_font, fill=WHITE)
    brand_right = 152 + draw.textbbox((0, 0), "BatchWatermark", font=brand_font)[2]
    pill(draw, (brand_right + 16, 80), "Web", load_font("bold", 20), ACCENT_SOFT, (29, 50, 87), (48, 82, 140))

    # Headline
    draw.text((64, 186), "免费在线", font=load_font("bold", 64), fill=WHITE)
    draw.text((64, 268), "批量加水印", font=load_font("bold", 64), fill=ACCENT_SOFT)
    draw.text((64, 362), "图片 · 视频 · 文字 / Logo 水印 · 实时预览", font=load_font("regular", 26), fill=TEXT)

    # Feature pills
    f = load_font("regular", 20)
    x = 64
    x = pill(draw, (x, 428), "零上传 · 纯本地处理", f, GREEN, (24, 39, 34), (36, 71, 58)) + 12
    x = pill(draw, (x, 428), "全图平铺防盗", f, ACCENT_SOFT, (29, 40, 62), (48, 70, 110)) + 12
    pill(draw, (64, 482), "横竖版分开导出", f, ACCENT_SOFT, (29, 40, 62), (48, 70, 110))

    # URL footer
    draw.text((64, 560), "drank5090.github.io/BatchWatermark", font=load_font("regular", 22), fill=MUTED)
    return card.convert("RGB")


def main() -> None:
    (WEB / "icons").mkdir(parents=True, exist_ok=True)

    (WEB / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")

    ico_src = render_icon(256)
    ico_src.save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    render_icon(180, full_bleed=True, safe_zone=0.76).save(WEB / "apple-touch-icon.png", optimize=True)
    render_icon(192).save(WEB / "icons" / "icon-192.png", optimize=True)
    render_icon(512).save(WEB / "icons" / "icon-512.png", optimize=True)
    render_icon(512, full_bleed=True, safe_zone=0.72).save(WEB / "icons" / "icon-maskable-512.png", optimize=True)

    render_og_image().save(WEB / "og-image.png", optimize=True)

    for p in sorted(WEB.glob("favicon.*")) + sorted(WEB.glob("*.png")) + sorted((WEB / "icons").glob("*.png")):
        print(f"{p.relative_to(ROOT).as_posix():40s} {p.stat().st_size / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
