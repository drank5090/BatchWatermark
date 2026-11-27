"""Built-in starter artistic watermark pack and persistent Creative Library storage."""

from __future__ import annotations

import base64
import io
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .creative_models import (
    CREATIVE_LIBRARY_SCHEMA_ID,
    CREATIVE_LIBRARY_SCHEMA_VERSION,
    CreativeAsset,
    new_id,
)
from .fonts import load_truetype_font, resolve_font_path


def _pil_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def data_url_to_pil(data_url: str) -> Image.Image | None:
    """Decode a base64 image data URL into an RGBA Pillow image."""
    if not data_url:
        return None
    try:
        if "," in data_url:
            _, b64 = data_url.split(",", 1)
        else:
            b64 = data_url
        raw = base64.b64decode(b64)
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            return im.convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


def image_file_to_asset(path: Path, *, max_edge: int = 640, role: str = "auto") -> CreativeAsset:
    """Load a user image sticker (PNG/WebP/JPG/BMP) into a portable CreativeAsset."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
        w, h = im.size
        if max(w, h) > max_edge:
            scale = max_edge / max(w, h)
            im = im.resize((max(1, int(round(w * scale))), max(1, int(round(h * scale)))), Image.Resampling.LANCZOS)
        # Trim fully transparent excess borders for accurate collision & handles
        bbox = im.getbbox()
        if bbox:
            pad = 2
            crop_box = (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(im.width, bbox[2] + pad),
                min(im.height, bbox[3] + pad),
            )
            im = im.crop(crop_box)
        data_url = _pil_to_data_url(im)

    return CreativeAsset(
        id=new_id("img"),
        kind="image",
        name=path.stem[:28] or "图片水印",
        role=role,
        enabled=True,
        weight=1.0,
        image_data_url=data_url,
        base_scale=0.14,
        opacity=82,
        rotation_range=24,
        glow_enabled=True,
        builtin=False,
    )


def _draw_ornate_snowflake(size: int = 256, *, fine: bool = False) -> Image.Image:
    """Procedurally draw a crisp translucent frosted snowflake sticker with soft glow."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2.0
    radius = size * (0.40 if not fine else 0.36)
    arm_w = max(2, int(round(size * (0.019 if not fine else 0.013))))
    sub_w = max(1, int(round(arm_w * 0.72)))
    white = (255, 255, 255, 245)
    frost = (224, 242, 254, 215)

    branches = 6 if not fine else 8
    for k in range(branches):
        ang = math.radians(k * (360.0 / branches) - 90.0)
        ca, sa = math.cos(ang), math.sin(ang)
        ex, ey = cx + ca * radius, cy + sa * radius
        draw.line([(cx, cy), (ex, ey)], fill=white, width=arm_w)

        # V-shaped crystalline twigs along each main arm
        twig_positions = (0.38, 0.62, 0.80) if not fine else (0.45, 0.74)
        for frac in twig_positions:
            bx = cx + ca * (radius * frac)
            by = cy + sa * (radius * frac)
            tlen = radius * (0.30 if frac < 0.5 else (0.24 if frac < 0.75 else 0.14))
            for side in (-1, 1):
                tang = ang + side * math.radians(52)
                tx = bx + math.cos(tang) * tlen
                ty = by + math.sin(tang) * tlen
                draw.line([(bx, by), (tx, ty)], fill=frost, width=sub_w)

        # Tip diamond crystal
        tip_r = size * (0.026 if not fine else 0.018)
        draw.ellipse((ex - tip_r, ey - tip_r, ex + tip_r, ey + tip_r), fill=white)

    # Inner hex/ring lattice
    ring_r = radius * 0.24
    pts = [
        (
            cx + math.cos(math.radians(i * (360.0 / branches) - 90.0)) * ring_r,
            cy + math.sin(math.radians(i * (360.0 / branches) - 90.0)) * ring_r,
        )
        for i in range(branches)
    ]
    pts.append(pts[0])
    draw.line(pts, fill=frost, width=sub_w)

    center_r = size * 0.036
    draw.ellipse((cx - center_r, cy - center_r, cx + center_r, cy + center_r), fill=white)

    # Subtle frosty outer halo
    glow = img.filter(ImageFilter.GaussianBlur(radius=max(1.5, size * 0.016)))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out = Image.alpha_composite(out, glow)
    out = Image.alpha_composite(out, img)
    return out


def _draw_sparkle_cluster(size: int = 200) -> Image.Image:
    """Draw a delicate anime four-point star sparkle cluster."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def _star(cx: float, cy: float, r_out: float, r_in: float, alpha: int = 245) -> None:
        pts: list[tuple[float, float]] = []
        for i in range(8):
            ang = math.radians(i * 45.0 - 90.0)
            rad = r_out if i % 2 == 0 else r_in
            pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
        draw.polygon(pts, fill=(255, 255, 255, alpha))

    _star(size * 0.44, size * 0.46, size * 0.34, size * 0.07, 245)
    _star(size * 0.76, size * 0.26, size * 0.16, size * 0.035, 220)
    _star(size * 0.74, size * 0.74, size * 0.11, size * 0.025, 200)

    for dx, dy, dr in ((0.20, 0.24, 0.022), (0.26, 0.78, 0.018), (0.84, 0.52, 0.016)):
        r = size * dr
        draw.ellipse((size * dx - r, size * dy - r, size * dx + r, size * dy + r), fill=(240, 249, 255, 210))

    glow = img.filter(ImageFilter.GaussianBlur(radius=3.5))
    return Image.alpha_composite(glow, img)


def _draw_ribbon_wave(width: int = 420, height: int = 96) -> Image.Image:
    """Draw a delicate sweeping decorative silk wave line with pearl accents."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pts1: list[tuple[float, float]] = []
    pts2: list[tuple[float, float]] = []
    for i in range(85):
        t = i / 84.0
        x = 18 + t * (width - 36)
        y1 = height * 0.50 + math.sin(t * math.tau * 1.15) * (height * 0.26)
        y2 = height * 0.54 + math.sin(t * math.tau * 1.15 + 0.65) * (height * 0.16)
        pts1.append((x, y1))
        pts2.append((x, y2))

    draw.line(pts1, fill=(255, 255, 255, 220), width=3)
    draw.line(pts2, fill=(219, 234, 254, 150), width=2)

    for idx in (16, 44, 68):
        px, py = pts1[idx]
        r = 5.0 if idx == 44 else 3.5
        draw.ellipse((px - r, py - r, px + r, py + r), fill=(255, 255, 255, 245))

    glow = img.filter(ImageFilter.GaussianBlur(radius=2.2))
    return Image.alpha_composite(glow, img)


def _draw_art_seal(size: int = 200) -> Image.Image:
    """Draw a minimalist circular art badge emblem."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 16
    draw.ellipse((pad, pad, size - pad, size - pad), outline=(255, 255, 255, 235), width=4)
    inner = pad + 11
    draw.ellipse((inner, inner, size - inner, size - inner), outline=(224, 242, 254, 170), width=2)

    font_path = resolve_font_path("宋体", "")
    font = load_truetype_font(font_path, int(size * 0.25))
    text = "初雪"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 4),
        text,
        font=font,
        fill=(255, 255, 255, 240),
    )

    sub_font = load_truetype_font(resolve_font_path("Georgia", ""), int(size * 0.095))
    sub = "ORIGINAL"
    sb = draw.textbbox((0, 0), sub, font=sub_font)
    sw = sb[2] - sb[0]
    draw.text(((size - sw) / 2 - sb[0], size * 0.67), sub, font=sub_font, fill=(224, 242, 254, 210))

    glow = img.filter(ImageFilter.GaussianBlur(radius=2.5))
    return Image.alpha_composite(glow, img)


def get_builtin_creative_assets() -> list[CreativeAsset]:
    """Return a ready-to-use artistic starter watermark library inspired by ACG/illustration watermarks."""
    return [
        CreativeAsset(
            id="builtin_snowflake_ornate",
            kind="image",
            name="❄️ 晶莹雪花",
            role="accent",
            enabled=True,
            weight=1.8,
            image_data_url=_pil_to_data_url(_draw_ornate_snowflake(256, fine=False)),
            base_scale=0.14,
            opacity=78,
            rotation_range=30,
            glow_enabled=True,
            builtin=True,
        ),
        CreativeAsset(
            id="builtin_frost_crystal",
            kind="image",
            name="❅ 冰晶星芒",
            role="micro",
            enabled=True,
            weight=1.5,
            image_data_url=_pil_to_data_url(_draw_ornate_snowflake(192, fine=True)),
            base_scale=0.075,
            opacity=62,
            rotation_range=35,
            glow_enabled=True,
            builtin=True,
        ),
        CreativeAsset(
            id="builtin_sparkle_cluster",
            kind="image",
            name="✧ 梦幻星光",
            role="accent",
            enabled=True,
            weight=1.2,
            image_data_url=_pil_to_data_url(_draw_sparkle_cluster(192)),
            base_scale=0.11,
            opacity=76,
            rotation_range=22,
            glow_enabled=True,
            builtin=True,
        ),
        CreativeAsset(
            id="builtin_art_seal",
            kind="image",
            name="💮 初雪印章",
            role="accent",
            enabled=True,
            weight=0.8,
            image_data_url=_pil_to_data_url(_draw_art_seal(200)),
            base_scale=0.12,
            opacity=74,
            rotation_range=14,
            glow_enabled=True,
            builtin=True,
        ),
        CreativeAsset(
            id="builtin_ribbon_wave",
            kind="image",
            name="〰 丝带波纹",
            role="accent",
            enabled=True,
            weight=0.7,
            image_data_url=_pil_to_data_url(_draw_ribbon_wave(420, 96)),
            base_scale=0.34,
            opacity=58,
            rotation_range=10,
            glow_enabled=True,
            builtin=True,
        ),
        CreativeAsset(
            id="builtin_text_hero",
            kind="text",
            name="主标题 · 初雪犹如初見",
            role="hero",
            enabled=True,
            weight=1.0,
            text="初雪犹如初見",
            font_name="宋体",
            color="#FFFFFF",
            stroke_enabled=True,
            stroke_color="#1E293B",
            stroke_width=2,
            glow_enabled=True,
            glow_color="#E0F2FE",
            glow_radius=8,
            base_scale=0.36,
            opacity=88,
            rotation_range=4,
            builtin=True,
        ),
        CreativeAsset(
            id="builtin_text_poetic",
            kind="text",
            name="诗意配文 · 双语落款",
            role="accent",
            enabled=True,
            weight=1.0,
            text="你代替初雪 降临我身边\nLike quiet snow falling beside you",
            font_name="微软雅黑",
            color="#F8FAFC",
            line_spacing=1.35,
            stroke_enabled=True,
            stroke_color="#0F172A",
            stroke_width=1,
            glow_enabled=True,
            glow_color="#FFFFFF",
            glow_radius=5,
            base_scale=0.22,
            opacity=72,
            rotation_range=5,
            builtin=True,
        ),
        CreativeAsset(
            id="builtin_text_micro",
            kind="text",
            name="微防盗签 · 禁止二改",
            role="micro",
            enabled=True,
            weight=1.4,
            text="Winter · 禁止快转/二改",
            font_name="微软雅黑",
            color="#F1F5F9",
            stroke_enabled=True,
            stroke_color="#0F172A",
            stroke_width=1,
            glow_enabled=False,
            base_scale=0.13,
            opacity=46,
            rotation_range=10,
            builtin=True,
        ),
    ]


def default_creative_library_path() -> Path:
    """Return per-user local storage path for the Creative Mode Watermark Library."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "BatchWatermark" / "creative_library.json"


class CreativeLibraryStore:
    """Local persistent storage + cross-platform JSON pack import/export for Watermark Library."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path: Path = Path(storage_path) if storage_path else default_creative_library_path()
        self._assets: list[CreativeAsset] = []
        self.reload()

    def reload(self) -> list[CreativeAsset]:
        if self.storage_path.is_file():
            try:
                raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
                parsed = self._parse_payload(raw)
                if parsed:
                    self._assets = parsed
                    return self.list_assets()
            except Exception:  # noqa: BLE001
                pass
        # Seed with built-in starter pack on first run
        self._assets = get_builtin_creative_assets()
        return self.list_assets()

    def _persist(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.build_export_payload(self._assets)
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_assets(self) -> list[CreativeAsset]:
        return [a.clone() for a in self._assets]

    def get_asset(self, asset_id: str) -> CreativeAsset | None:
        for a in self._assets:
            if a.id == asset_id:
                return a.clone()
        return None

    def asset_map(self) -> dict[str, CreativeAsset]:
        return {a.id: a for a in self._assets}

    def add_asset(self, asset: CreativeAsset) -> CreativeAsset:
        saved = asset.clone()
        # Ensure unique ID
        existing_ids = {a.id for a in self._assets}
        if saved.id in existing_ids:
            saved.id = new_id("ast")
        self._assets.append(saved)
        self._persist()
        return saved.clone()

    def update_asset(self, asset: CreativeAsset) -> bool:
        for i, existing in enumerate(self._assets):
            if existing.id == asset.id:
                self._assets[i] = asset.clone()
                self._persist()
                return True
        return False

    def delete_asset(self, asset_id: str) -> bool:
        before = len(self._assets)
        self._assets = [a for a in self._assets if a.id != asset_id]
        if len(self._assets) != before:
            self._persist()
            return True
        return False

    def reset_to_builtins(self) -> list[CreativeAsset]:
        self._assets = get_builtin_creative_assets()
        self._persist()
        return self.list_assets()

    def clear_all(self) -> None:
        self._assets = []
        self._persist()

    @staticmethod
    def build_export_payload(assets: list[CreativeAsset]) -> dict[str, Any]:
        return {
            "schema": CREATIVE_LIBRARY_SCHEMA_ID,
            "version": CREATIVE_LIBRARY_SCHEMA_VERSION,
            "assets": [a.to_dict() for a in assets],
        }

    def export_pack(self, target_path: Path, *, only_enabled: bool = False) -> int:
        chosen = [a for a in self._assets if (a.enabled or not only_enabled)]
        payload = self.build_export_payload(chosen)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(chosen)

    def import_pack(self, source_path: Path, *, replace: bool = False) -> list[CreativeAsset]:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        parsed = self._parse_payload(raw)
        if not parsed:
            raise ValueError("文件中未找到有效的创作模式水印库素材。")

        if replace:
            self._assets = parsed
        else:
            existing_ids = {a.id for a in self._assets}
            for item in parsed:
                if item.id in existing_ids:
                    item.id = new_id("ast")
                existing_ids.add(item.id)
                self._assets.append(item)
        self._persist()
        return parsed

    @staticmethod
    def _parse_payload(raw: Any) -> list[CreativeAsset]:
        if isinstance(raw, dict) and isinstance(raw.get("assets"), list):
            items = raw["assets"]
        elif isinstance(raw, list):
            items = raw
        else:
            return []
        out: list[CreativeAsset] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            asset = CreativeAsset.from_dict(entry)
            if asset.kind == "image" and not asset.image_data_url:
                continue
            if asset.kind == "text" and not asset.text.strip():
                continue
            out.append(asset)
        return out
