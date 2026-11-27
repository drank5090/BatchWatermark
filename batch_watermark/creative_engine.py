"""Subject-aware multi-scale aesthetic auto-layout and Pillow compositor for Creative Mode.

Features:
- Fast 48x48 visual saliency + portrait-center protection map so large/bright watermarks
  gracefully avoid covering faces/key subjects while framing edges & breathing zones.
- Multi-tier scale hierarchy (Hero focal title/stamp + varied-size organic Accents +
  delicate low-opacity Micro anti-theft rhythm) inspired by ACG/illustration art watermarks.
- Weighted Best-Candidate / Blue-Noise collision avoidance so elements never ugly-pile.
- Exact normalized coordinate & short-edge relative scaling for 100% WYSIWYG parity between
  interactive canvas preview, multi-image sync, and full-resolution Pillow export.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, ImageFilter

from .creative_library import data_url_to_pil
from .creative_models import (
    AutoLayoutConfig,
    CreativeAsset,
    CreativePlacement,
    new_id,
)
from .engine import _alpha_composite_clipped, _resolve_target_format_and_ext, _scale_alpha, load_image_oriented, resolve_output_path
from .fonts import load_truetype_font, resolve_font_path
from .models import ExportConfig, OrientationGroup


class Mulberry32:
    """Deterministic 32-bit PRNG matching the Web JS edition for identical seeded layouts."""

    def __init__(self, seed: int) -> None:
        self._state = int(seed) & 0xFFFFFFFF

    def next(self) -> float:
        self._state = (self._state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self._state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.next()

    def weighted_choice(self, items: list[CreativeAsset]) -> CreativeAsset:
        total = sum(max(0.05, float(a.weight)) for a in items)
        pick = self.next() * total
        acc = 0.0
        for item in items:
            acc += max(0.05, float(item.weight))
            if pick <= acc:
                return item
        return items[-1]


# ---- Saliency & Subject Protection Map ----

SALIENCY_GRID = 48


def compute_saliency_grid(image: Image.Image) -> list[list[float]]:
    """Compute a normalized [0..1] 48x48 saliency + portrait-center protection grid."""
    small_rgb = image.convert("RGB").resize((SALIENCY_GRID, SALIENCY_GRID), Image.Resampling.BILINEAR)
    px = small_rgb.load()
    lum = [[0.0] * SALIENCY_GRID for _ in range(SALIENCY_GRID)]
    sat = [[0.0] * SALIENCY_GRID for _ in range(SALIENCY_GRID)]

    for y in range(SALIENCY_GRID):
        for x in range(SALIENCY_GRID):
            r, g, b = px[x, y]
            lum[y][x] = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            mx = max(r, g, b)
            mn = min(r, g, b)
            sat[y][x] = (mx - mn) / float(mx) if mx > 12 else 0.0

    grid = [[0.0] * SALIENCY_GRID for _ in range(SALIENCY_GRID)]
    max_val = 1e-6

    for y in range(SALIENCY_GRID):
        ny = (y + 0.5) / SALIENCY_GRID
        for x in range(SALIENCY_GRID):
            nx = (x + 0.5) / SALIENCY_GRID
            xm = max(0, x - 1)
            xp = min(SALIENCY_GRID - 1, x + 1)
            ym = max(0, y - 1)
            yp = min(SALIENCY_GRID - 1, y + 1)
            gx = abs(lum[y][xp] - lum[y][xm])
            gy = abs(lum[yp][x] - lum[ym][x])
            edge = min(1.0, math.hypot(gx, gy) * 2.2)

            # Portrait/subject focal prior centered slightly above geometric center (face/eyes area)
            dx = (nx - 0.50) / 0.25
            dy = (ny - 0.42) / 0.28
            center_prior = math.exp(-0.5 * (dx * dx + dy * dy))

            score = 0.52 * center_prior + 0.36 * edge + 0.12 * sat[y][x]
            grid[y][x] = score
            if score > max_val:
                max_val = score

    # Box-smooth once so protection zones are gentle & organic
    smoothed = [[0.0] * SALIENCY_GRID for _ in range(SALIENCY_GRID)]
    for y in range(SALIENCY_GRID):
        for x in range(SALIENCY_GRID):
            acc = 0.0
            cnt = 0
            for yy in range(max(0, y - 1), min(SALIENCY_GRID, y + 2)):
                for xx in range(max(0, x - 1), min(SALIENCY_GRID, x + 2)):
                    acc += grid[yy][xx]
                    cnt += 1
            smoothed[y][x] = min(1.0, (acc / cnt) / max_val)
    return smoothed


def _sample_saliency(grid: list[list[float]] | None, nx: float, ny: float, radius_norm: float = 0.05) -> float:
    if not grid:
        dx = (nx - 0.50) / 0.26
        dy = (ny - 0.42) / 0.28
        return math.exp(-0.5 * (dx * dx + dy * dy))
    n = len(grid)
    cx = max(0, min(n - 1, int(nx * n)))
    cy = max(0, min(n - 1, int(ny * n)))
    rad = max(1, int(round(radius_norm * n)))
    acc = 0.0
    cnt = 0
    for yy in range(max(0, cy - rad), min(n, cy + rad + 1)):
        for xx in range(max(0, cx - rad), min(n, cx + rad + 1)):
            acc += grid[yy][xx]
            cnt += 1
    return acc / max(1, cnt)


# ---- Asset Rendering & Aspect Estimation ----

@lru_cache(maxsize=96)
def _decode_asset_image_cached(cache_key: str, data_url: str) -> Image.Image | None:
    del cache_key
    return data_url_to_pil(data_url)


def get_asset_source_image(asset: CreativeAsset) -> Image.Image | None:
    if asset.kind != "image" or not asset.image_data_url:
        return None
    digest = hashlib.md5(asset.image_data_url.encode("utf-8", "ignore")).hexdigest()
    return _decode_asset_image_cached(digest, asset.image_data_url)


def estimate_asset_aspect(asset: CreativeAsset) -> float:
    """Return natural height / width ratio for collision estimation."""
    if asset.kind == "image":
        im = get_asset_source_image(asset)
        if im and im.width > 0:
            return max(0.18, min(4.0, im.height / float(im.width)))
        return 1.0

    lines = [ln for ln in (asset.text or "").splitlines() if ln.strip()] or ["A"]
    max_units = max(sum(1.0 if ord(ch) > 127 else 0.58 for ch in ln) for ln in lines)
    max_units = max(1.5, max_units)
    aspect = (len(lines) * max(1.0, asset.line_spacing)) / max_units
    return max(0.16, min(2.5, aspect))


def _parse_hex_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    try:
        r, g, b = ImageColor.getrgb(hex_color)[:3]
    except ValueError:
        r, g, b = 255, 255, 255
    return (r, g, b, max(0, min(255, int(alpha))))


def render_asset_stamp(
    asset: CreativeAsset,
    target_width_px: int,
    *,
    opacity: int = 80,
    glow_enabled: bool = True,
) -> Image.Image | None:
    """Render an unrotated RGBA stamp of `asset` whose visible content width matches `target_width_px`."""
    target_w = max(8, int(round(target_width_px)))
    if opacity <= 0:
        return None

    if asset.kind == "image":
        src = get_asset_source_image(asset)
        if src is None or src.width <= 0 or src.height <= 0:
            return None
        target_h = max(8, int(round(target_w * (src.height / float(src.width)))))
        resized = src.resize((target_w, target_h), Image.Resampling.LANCZOS)
        if glow_enabled and asset.glow_enabled:
            g_rad = max(1.2, min(10.0, target_w * 0.03))
            pad = max(3, int(math.ceil(g_rad * 2.2)))
            canvas = Image.new("RGBA", (target_w + pad * 2, target_h + pad * 2), (0, 0, 0, 0))
            # Soft dark rim + bright halo so stickers look luminous on both light & dark photos
            alpha_ch = resized.getchannel("A")
            glow_layer = Image.new("RGBA", resized.size, _parse_hex_rgba(asset.glow_color or "#FFFFFF", 160))
            glow_layer.putalpha(alpha_ch.point(lambda a: int(a * 0.55)))
            dark_layer = Image.new("RGBA", resized.size, (15, 23, 42, 110))
            dark_layer.putalpha(alpha_ch.point(lambda a: int(a * 0.40)))

            tmp_dark = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            tmp_dark.paste(dark_layer, (pad + 1, pad + 1))
            tmp_dark = tmp_dark.filter(ImageFilter.GaussianBlur(radius=max(1.0, g_rad * 0.7)))

            tmp_glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            tmp_glow.paste(glow_layer, (pad, pad))
            tmp_glow = tmp_glow.filter(ImageFilter.GaussianBlur(radius=g_rad))

            canvas = Image.alpha_composite(canvas, tmp_dark)
            canvas = Image.alpha_composite(canvas, tmp_glow)
            canvas.alpha_composite(resized, dest=(pad, pad))
            return _scale_alpha(canvas, opacity)
        return _scale_alpha(resized, opacity)

    # Text asset rendering scaled precisely to target_w
    text = (asset.text or "").strip("\r\n")
    if not text.strip():
        return None

    font_path = resolve_font_path(asset.font_name, asset.custom_font_path)
    # Measure at reference 64px to compute exact font_px hitting target_w
    ref_font = load_truetype_font(font_path, 64)
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    ref_spacing = max(0, int(round(64 * max(0.0, asset.line_spacing - 1.0))))
    ref_bbox = dummy.multiline_textbbox((0, 0), text, font=ref_font, spacing=ref_spacing, align="center")
    ref_w = max(1.0, float(ref_bbox[2] - ref_bbox[0]))
    font_px = max(8, min(420, int(round(64.0 * (target_w / ref_w)))))

    font = load_truetype_font(font_path, font_px)
    spacing_px = max(0, int(round(font_px * max(0.0, asset.line_spacing - 1.0))))
    unit = max(0.45, font_px / 48.0)
    stroke_w = max(1, int(round(asset.stroke_width * unit))) if (asset.stroke_enabled and asset.stroke_width > 0) else 0
    g_rad = (
        max(1.5, min(14.0, asset.glow_radius * unit))
        if (glow_enabled and asset.glow_enabled and asset.glow_radius > 0)
        else 0.0
    )

    bbox = dummy.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing_px, stroke_width=stroke_w, align="center"
    )
    tw = max(2, int(math.ceil(bbox[2] - bbox[0])))
    th = max(2, int(math.ceil(bbox[3] - bbox[1])))
    pad = stroke_w + int(math.ceil(g_rad * 2.2)) + 4
    stamp = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    dx = pad - bbox[0]
    dy = pad - bbox[1]

    if g_rad > 0:
        glow_img = Image.new("RGBA", stamp.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_img)
        gd.multiline_text(
            (dx, dy),
            text,
            font=font,
            fill=_parse_hex_rgba(asset.glow_color or "#FFFFFF", 185),
            spacing=spacing_px,
            align="center",
            stroke_width=max(1, stroke_w),
            stroke_fill=_parse_hex_rgba(asset.glow_color or "#FFFFFF", 150),
        )
        glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=g_rad))
        stamp = Image.alpha_composite(stamp, glow_img)

    draw = ImageDraw.Draw(stamp)
    # Soft dark shadow for readability on bright snow/highlights
    sh_off = max(1, int(round(1.8 * unit)))
    draw.multiline_text(
        (dx + sh_off, dy + sh_off),
        text,
        font=font,
        fill=(15, 23, 42, 135),
        spacing=spacing_px,
        align="center",
        stroke_width=stroke_w,
        stroke_fill=(15, 23, 42, 110) if stroke_w > 0 else None,
    )

    draw.multiline_text(
        (dx, dy),
        text,
        font=font,
        fill=_parse_hex_rgba(asset.color or "#FFFFFF", 255),
        spacing=spacing_px,
        align="center",
        stroke_width=stroke_w,
        stroke_fill=_parse_hex_rgba(asset.stroke_color or "#1E293B", 230) if stroke_w > 0 else None,
    )

    return _scale_alpha(stamp, opacity)


# ---- Aesthetic Multi-Scale Auto-Layout Algorithm ----

def _partition_assets(assets: list[CreativeAsset]) -> tuple[list[CreativeAsset], list[CreativeAsset], list[CreativeAsset]]:
    """Split enabled assets into (hero_pool, accent_pool, micro_pool) smartly."""
    enabled = [a for a in assets if a.enabled]
    if not enabled:
        return [], [], []

    heroes = [a for a in enabled if a.role == "hero"]
    accents = [a for a in enabled if a.role == "accent"]
    micros = [a for a in enabled if a.role == "micro"]
    autos = [a for a in enabled if a.role == "auto"]

    if autos:
        # Promote one auto text (or first auto asset) into hero if none designated
        if not heroes:
            auto_texts = [a for a in autos if a.kind == "text"]
            heroes = [auto_texts[0] if auto_texts else autos[0]]
        accents.extend(autos)
        micros.extend(autos)

    if not accents:
        accents = list(enabled)
    if not micros:
        micros = list(accents)
    if not heroes and enabled:
        # Optional hero only if user explicitly has text or multiple assets
        text_candidates = [a for a in enabled if a.kind == "text"]
        if text_candidates:
            heroes = [text_candidates[0]]

    return heroes, accents, micros


def generate_aesthetic_layout(
    canvas_size: tuple[int, int],
    assets: list[CreativeAsset],
    config: AutoLayoutConfig,
    *,
    base_image: Image.Image | None = None,
    existing_locked: list[CreativePlacement] | None = None,
) -> list[CreativePlacement]:
    """Generate an organic, varied-size, subject-aware watermark layout.

    Returns a list of `CreativePlacement` layers (preserving any `existing_locked` layers).
    """
    cw, ch = max(1, int(canvas_size[0])), max(1, int(canvas_size[1]))
    short_edge = float(min(cw, ch))
    rng = Mulberry32(config.seed ^ (cw * 73856093) ^ (ch * 19349663))

    heroes, accents, micros = _partition_assets(assets)
    if not accents and not heroes and not micros:
        return [p.clone() for p in (existing_locked or [])]

    saliency = compute_saliency_grid(base_image) if base_image is not None else None
    avoid_strength = max(0.0, min(1.0, config.subject_avoidance / 100.0))
    scale_var = max(0.0, min(1.0, config.scale_variation / 100.0))
    density_f = max(0.1, min(1.0, config.density / 100.0))
    op_factor = max(0.15, min(1.0, config.global_opacity / 100.0))

    asset_by_id = {a.id: a for a in assets}
    aspects = {a.id: estimate_asset_aspect(a) for a in assets}

    # Placed list keeps (x_px, y_px, half_w_px, half_h_px, asset_id, tier)
    occupied: list[tuple[float, float, float, float, str, int]] = []
    placements: list[CreativePlacement] = []

    for idx, locked in enumerate(existing_locked or []):
        lp = locked.clone()
        lp.z_index = idx
        placements.append(lp)
        asp = aspects.get(lp.asset_id, 1.0)
        hw = (lp.scale * short_edge) * 0.52
        hh = hw * asp
        occupied.append((lp.x * cw, lp.y * ch, hw, hh, lp.asset_id, 0))

    def _collides(nx: float, ny: float, scale: float, aspect: float, pad_mult: float) -> bool:
        cx_px, cy_px = nx * cw, ny * ch
        hw = (scale * short_edge) * 0.5 * pad_mult
        hh = max(hw * aspect, short_edge * 0.015)
        for ox, oy, ohw, ohh, _, _ in occupied:
            if abs(cx_px - ox) < (hw + ohw) and abs(cy_px - oy) < (hh + ohh):
                return True
        return False

    def _nearest_dist_norm(nx: float, ny: float, same_asset_id: str | None = None) -> float:
        best = 9.0
        for ox, oy, _, _, aid, _ in occupied:
            if same_asset_id is not None and aid != same_asset_id:
                continue
            d = math.hypot((nx * cw - ox) / short_edge, (ny * ch - oy) / short_edge)
            if d < best:
                best = d
        return best

    def _register(
        asset: CreativeAsset,
        nx: float,
        ny: float,
        scale: float,
        rotation: float,
        opacity: int,
        tier: int,
    ) -> None:
        asp = aspects.get(asset.id, 1.0)
        hw = (scale * short_edge) * 0.5
        hh = max(hw * asp, short_edge * 0.015)
        occupied.append((nx * cw, ny * ch, hw, hh, asset.id, tier))
        placements.append(
            CreativePlacement(
                id=new_id("lyr"),
                asset_id=asset.id,
                x=round(nx, 5),
                y=round(ny, 5),
                scale=round(max(0.025, min(0.75, scale)), 5),
                rotation=round(rotation, 2),
                opacity=max(8, min(100, int(round(opacity)))),
                glow_enabled=bool(config.soft_glow and asset.glow_enabled),
                locked=False,
                auto_generated=True,
                z_index=len(placements),
            )
        )

    # ---- TIER 1: Hero Focal Element(s) ----
    if heroes and config.style != "full_anti_theft":
        hero_asset = rng.weighted_choice(heroes)
        h_asp = aspects.get(hero_asset.id, 0.35)
        hero_scale = max(0.18, min(0.50, hero_asset.base_scale * rng.uniform(0.95, 1.18 + 0.14 * scale_var)))
        # Ensure hero text fits comfortably inside width
        max_w_scale = (cw * 0.72) / short_edge
        hero_scale = min(hero_scale, max_w_scale)

        if config.style == "magazine_editorial":
            hero_slots = [(0.50, 0.82), (0.50, 0.14), (0.28, 0.82), (0.72, 0.82)]
        elif config.style == "frame_halo":
            hero_slots = [(0.50, 0.86), (0.50, 0.12), (0.78, 0.86), (0.22, 0.86)]
        else:  # artistic_scatter (inspired by reference image bottom-center title)
            hero_slots = [(0.50, 0.79), (0.50, 0.84), (0.36, 0.80), (0.64, 0.80), (0.50, 0.16)]

        best_slot = None
        best_score = -1e9
        for sx, sy in hero_slots:
            jx = max(0.16, min(0.84, sx + rng.uniform(-0.04, 0.04)))
            jy = max(0.10, min(0.90, sy + rng.uniform(-0.03, 0.03)))
            if _collides(jx, jy, hero_scale, h_asp, 1.05):
                continue
            sal = _sample_saliency(saliency, jx, jy, 0.08)
            score = -sal * avoid_strength * 1.4 + rng.uniform(-0.08, 0.08)
            if score > best_score:
                best_score = score
                best_slot = (jx, jy)

        if best_slot:
            max_rot = min(float(hero_asset.rotation_range), float(config.rotation_jitter) * 0.25, 6.0)
            rot = rng.uniform(-max_rot, max_rot) if max_rot > 0.3 else 0.0
            op = min(100, hero_asset.opacity * (0.75 + 0.35 * op_factor))
            _register(hero_asset, best_slot[0], best_slot[1], hero_scale, rot, int(op), tier=1)

    # ---- TIER 2: Multi-Scale Organic Accents (large / medium / small varied sizes) ----
    base_accent_count = int(round(7 + density_f * 18))
    if config.style == "frame_halo":
        base_accent_count = int(round(8 + density_f * 15))
    elif config.style == "full_anti_theft":
        base_accent_count = int(round(12 + density_f * 22))
    elif config.style == "magazine_editorial":
        base_accent_count = int(round(6 + density_f * 11))

    # Build a size-tiered schedule (largest first so big elements get breathing space)
    size_multipliers: list[float] = []
    for i in range(base_accent_count):
        frac = i / max(1, base_accent_count - 1)
        if frac < 0.22:
            # Large decorative accents
            m = rng.uniform(1.08, 1.08 + 0.55 * scale_var)
        elif frac < 0.62:
            # Medium accents
            m = rng.uniform(max(0.55, 0.92 - 0.22 * scale_var), 1.06 + 0.14 * scale_var)
        else:
            # Compact accents
            m = rng.uniform(max(0.32, 0.65 - 0.30 * scale_var), max(0.52, 0.85 - 0.12 * scale_var))
        size_multipliers.append(m)
    size_multipliers.sort(reverse=True)

    # Keep text accents tasteful (max 2 repeats per unique quote, <= 32% of accents)
    text_accent_limit = max(2, int(round(base_accent_count * 0.28)))
    placed_text_accents = 0
    text_asset_counts: dict[str, int] = {}

    for mult in size_multipliers:
        non_text = [a for a in accents if a.kind == "image"]
        eligible_texts = [a for a in accents if a.kind == "text" and text_asset_counts.get(a.id, 0) < 2]
        if placed_text_accents >= text_accent_limit and non_text:
            pool = non_text
        elif non_text:
            pool = non_text + eligible_texts
        else:
            pool = eligible_texts or accents
        asset = rng.weighted_choice(pool)
        asp = aspects.get(asset.id, 1.0)
        scale = max(0.04, min(0.42, asset.base_scale * mult))
        if asset.kind == "text":
            scale = min(scale, (cw * 0.44) / short_edge)

        half_w_norm = (scale * short_edge * 0.5) / cw
        half_h_norm = (scale * short_edge * asp * 0.5) / ch
        # Text stays cleanly inside borders; stickers may slightly bleed at edges like editorial art
        margin_x = half_w_norm + 0.025 if asset.kind == "text" else max(0.03, half_w_norm * 0.45)
        margin_y = half_h_norm + 0.025 if asset.kind == "text" else max(0.03, half_h_norm * 0.45)
        margin_x = min(margin_x, 0.38)
        margin_y = min(margin_y, 0.38)

        best_cand = None
        best_score = -1e9
        pad_mult = 1.18 if asset.kind == "text" else 1.10

        for _ in range(30):
            if config.style == "frame_halo":
                # Sample preferentially along the outer perimeter ring
                edge_pick = rng.next()
                band = rng.uniform(0.04, 0.22)
                if edge_pick < 0.28:
                    nx, ny = rng.uniform(margin_x, 1.0 - margin_x), max(margin_y, band)
                elif edge_pick < 0.56:
                    nx, ny = rng.uniform(margin_x, 1.0 - margin_x), min(1.0 - margin_y, 1.0 - band)
                elif edge_pick < 0.78:
                    nx, ny = max(margin_x, band), rng.uniform(margin_y, 1.0 - margin_y)
                else:
                    nx, ny = min(1.0 - margin_x, 1.0 - band), rng.uniform(margin_y, 1.0 - margin_y)
            else:
                nx = rng.uniform(margin_x, 1.0 - margin_x)
                ny = rng.uniform(margin_y, 1.0 - margin_y)

            if _collides(nx, ny, scale, asp, pad_mult):
                continue

            sal = _sample_saliency(saliency, nx, ny, max(0.04, scale * 0.35))
            # Larger elements avoid the focal subject much more strongly than small ones
            size_weight = 0.65 + 0.85 * min(1.4, mult)
            dist_all = min(0.45, _nearest_dist_norm(nx, ny))
            dist_same = min(0.60, _nearest_dist_norm(nx, ny, asset.id))

            # Subtle preference for framing aesthetics in artistic_scatter
            edge_dist = min(nx, 1.0 - nx, ny, 1.0 - ny)
            frame_bonus = 0.14 if (config.style == "artistic_scatter" and edge_dist < 0.24) else 0.0

            score = (
                dist_all * 1.45
                + dist_same * 0.95
                + frame_bonus
                - sal * avoid_strength * size_weight * 1.85
                + rng.uniform(-0.06, 0.06)
            )
            if score > best_score:
                best_score = score
                best_cand = (nx, ny, sal)

        if best_cand is None:
            continue

        nx, ny, sal = best_cand
        max_rot = min(float(asset.rotation_range), float(config.rotation_jitter))
        if asset.kind == "text":
            max_rot = min(max_rot * 0.30, 8.0)
        rot = rng.uniform(-max_rot, max_rot) if max_rot > 0.3 else 0.0

        # Gently soften opacity if a stamp lands over moderate saliency
        sal_fade = 1.0 - (sal * avoid_strength * 0.32)
        op = asset.opacity * op_factor * rng.uniform(0.76, 1.08) * sal_fade
        _register(asset, nx, ny, scale, rot, int(op), tier=2)
        if asset.kind == "text":
            placed_text_accents += 1
            text_asset_counts[asset.id] = text_asset_counts.get(asset.id, 0) + 1

    # ---- TIER 3: Micro Anti-Theft Rhythm Stamps ----
    if (config.include_micro_grid or config.style == "full_anti_theft") and micros:
        cols = max(3, min(7, int(round(3 + density_f * 3.5))))
        rows = max(3, min(7, int(round(3 + density_f * 3.5))))
        for r in range(rows):
            for c in range(cols):
                if config.style == "frame_halo":
                    # Keep the central face window crystal clear in frame_halo mode
                    cx0 = (c + 0.5) / cols
                    cy0 = (r + 0.5) / rows
                    if abs(cx0 - 0.5) < 0.24 and abs(cy0 - 0.45) < 0.24:
                        continue
                if rng.next() > (0.48 + 0.44 * density_f):
                    continue

                asset = rng.weighted_choice(micros)
                asp = aspects.get(asset.id, 1.0)
                jitter_x = rng.uniform(-0.34, 0.34) / cols
                jitter_y = rng.uniform(-0.34, 0.34) / rows
                nx = max(0.05, min(0.95, (c + 0.5) / cols + jitter_x))
                ny = max(0.05, min(0.95, (r + 0.5) / rows + jitter_y))

                micro_mult = rng.uniform(0.30, max(0.42, 0.62 - 0.12 * scale_var))
                scale = max(0.032, min(0.14, asset.base_scale * micro_mult))
                if _collides(nx, ny, scale, asp, 1.06):
                    continue

                sal = _sample_saliency(saliency, nx, ny, 0.04)
                if sal > 0.78 and avoid_strength > 0.6 and config.style != "full_anti_theft":
                    continue

                max_rot = min(float(asset.rotation_range), float(config.rotation_jitter))
                if asset.kind == "text":
                    max_rot = min(max_rot * 0.45, 14.0)
                rot = rng.uniform(-max_rot, max_rot) if max_rot > 0.3 else 0.0

                sal_fade = 1.0 - (sal * avoid_strength * 0.45)
                op = asset.opacity * op_factor * rng.uniform(0.32, 0.58) * sal_fade
                _register(asset, nx, ny, scale, rot, int(max(12, op)), tier=3)

    # Sort z-order: micro bottom -> accents middle -> hero & locked top
    placements.sort(key=lambda p: (0 if p.auto_generated else 1, p.z_index))
    for i, p in enumerate(placements):
        p.z_index = i
    return placements


# ---- High-Resolution & Preview Compositor ----

def render_creative_overlay(
    canvas_size: tuple[int, int],
    placements: Iterable[CreativePlacement],
    assets_by_id: dict[str, CreativeAsset],
) -> Image.Image:
    """Render all creative watermark placements onto a transparent RGBA overlay."""
    cw, ch = max(1, int(canvas_size[0])), max(1, int(canvas_size[1]))
    short_edge = float(min(cw, ch))
    overlay = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    ordered = sorted(placements, key=lambda p: p.z_index)
    for layer in ordered:
        asset = assets_by_id.get(layer.asset_id)
        if asset is None or layer.opacity <= 0:
            continue
        target_w = max(8, int(round(layer.scale * short_edge)))
        stamp = render_asset_stamp(
            asset,
            target_w,
            opacity=layer.opacity,
            glow_enabled=layer.glow_enabled,
        )
        if stamp is None:
            continue

        angle = float(layer.rotation)
        if abs(angle) > 0.05:
            rot_stamp = stamp.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        else:
            rot_stamp = stamp

        px = int(round(layer.x * cw - rot_stamp.width / 2.0))
        py = int(round(layer.y * ch - rot_stamp.height / 2.0))
        _alpha_composite_clipped(overlay, rot_stamp, px, py)

    return overlay


def apply_creative_watermarks(
    base_image: Image.Image,
    placements: Iterable[CreativePlacement],
    assets_by_id: dict[str, CreativeAsset],
) -> Image.Image:
    """Composite creative watermark layers onto `base_image` and return a new RGBA image."""
    base_rgba = base_image if base_image.mode == "RGBA" else base_image.convert("RGBA")
    overlay = render_creative_overlay(base_rgba.size, placements, assets_by_id)
    return Image.alpha_composite(base_rgba, overlay)


def export_creative_image(
    src_path: Path,
    placements: list[CreativePlacement],
    assets_by_id: dict[str, CreativeAsset],
    export_config: ExportConfig,
) -> Path:
    """Apply full-resolution Creative Mode composition to `src_path` and save to output_dir."""
    img, orig_format, exif_bytes = load_image_oriented(src_path)
    orig_w, orig_h = img.size
    orientation = OrientationGroup.PORTRAIT if orig_h > orig_w else OrientationGroup.LANDSCAPE

    composited = apply_creative_watermarks(img, placements, assets_by_id)
    pil_fmt, ext = _resolve_target_format_and_ext(src_path, orig_format, export_config.output_format)
    out_path = resolve_output_path(src_path, export_config, ext, orientation=orientation)

    save_kwargs: dict[str, object] = {}
    if pil_fmt in {"JPEG", "BMP"}:
        bg = Image.new("RGB", composited.size, (255, 255, 255))
        bg.paste(composited, mask=composited.getchannel("A"))
        to_save = bg
    elif pil_fmt == "TIFF":
        to_save = composited if img.mode in {"RGBA", "LA", "PA"} else composited.convert("RGB")
    else:
        to_save = composited

    if pil_fmt == "JPEG":
        save_kwargs["quality"] = max(1, min(100, int(export_config.quality)))
        save_kwargs["subsampling"] = 0
        save_kwargs["optimize"] = True
        if export_config.keep_exif and exif_bytes:
            save_kwargs["exif"] = exif_bytes
    elif pil_fmt == "WEBP":
        save_kwargs["quality"] = max(1, min(100, int(export_config.quality)))
        save_kwargs["method"] = 4
        if export_config.keep_exif and exif_bytes:
            save_kwargs["exif"] = exif_bytes
    elif pil_fmt == "PNG":
        save_kwargs["optimize"] = True

    to_save.save(out_path, format=pil_fmt, **save_kwargs)
    return out_path
