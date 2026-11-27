"""Data models for BatchWatermark v2.0 Creative Mode (创作模式).

Schema is designed for 100% JSON compatibility between Desktop (Python/PySide6)
and Web (HTML5/JS) editions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import uuid

CREATIVE_LIBRARY_SCHEMA_ID = "batch_watermark_creative_library"
CREATIVE_LIBRARY_SCHEMA_VERSION = 1

VALID_ASSET_KINDS = ("image", "text")
VALID_ASSET_ROLES = ("auto", "hero", "accent", "micro")
VALID_LAYOUT_STYLES = (
    "artistic_scatter",
    "frame_halo",
    "full_anti_theft",
    "magazine_editorial",
)


def new_id(prefix: str = "item") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@dataclass
class CreativeAsset:
    """Single watermark element stored in the Creative Mode Watermark Library."""

    id: str = field(default_factory=lambda: new_id("ast"))
    kind: str = "text"  # "image" | "text"
    name: str = "水印元素"
    role: str = "auto"  # "auto" | "hero" | "accent" | "micro"
    enabled: bool = True
    weight: float = 1.0  # 0.2..3.0 relative frequency in auto-layout

    # Image asset payload (self-contained PNG/WebP data URL for cross-platform JSON portability)
    image_data_url: str = ""

    # Text asset properties
    text: str = "初雪犹如初見"
    font_name: str = "宋体"
    custom_font_path: str = ""
    color: str = "#FFFFFF"
    line_spacing: float = 1.25
    stroke_enabled: bool = True
    stroke_color: str = "#1E293B"
    stroke_width: int = 2
    glow_enabled: bool = True
    glow_color: str = "#FFFFFF"
    glow_radius: int = 6

    # Default appearance hints for auto & manual placement
    base_scale: float = 0.14  # fraction of image short edge (0.03..0.55)
    opacity: int = 75  # 10..100
    rotation_range: int = 18  # max random tilt degrees in auto-layout (0..45)
    builtin: bool = False

    def clone(self, *, new_asset_id: bool = False) -> CreativeAsset:
        data = asdict(self)
        if new_asset_id:
            data["id"] = new_id("ast")
        return CreativeAsset(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CreativeAsset:
        if not isinstance(raw, dict):
            return cls()
        kind = str(raw.get("kind", "text")).strip().lower()
        if kind not in VALID_ASSET_KINDS:
            kind = "text"
        role = str(raw.get("role", "auto")).strip().lower()
        if role not in VALID_ASSET_ROLES:
            role = "auto"
        return cls(
            id=str(raw.get("id") or new_id("ast")),
            kind=kind,
            name=str(raw.get("name") or ("图片贴纸" if kind == "image" else "文字水印")),
            role=role,
            enabled=bool(raw.get("enabled", True)),
            weight=_clamp_float(raw.get("weight", 1.0), 0.2, 3.0, 1.0),
            image_data_url=str(raw.get("image_data_url") or ""),
            text=str(raw.get("text") or ""),
            font_name=str(raw.get("font_name") or "宋体"),
            custom_font_path=str(raw.get("custom_font_path") or ""),
            color=str(raw.get("color") or "#FFFFFF"),
            line_spacing=_clamp_float(raw.get("line_spacing", 1.25), 1.0, 2.4, 1.25),
            stroke_enabled=bool(raw.get("stroke_enabled", True)),
            stroke_color=str(raw.get("stroke_color") or "#1E293B"),
            stroke_width=_clamp_int(raw.get("stroke_width", 2), 0, 12, 2),
            glow_enabled=bool(raw.get("glow_enabled", True)),
            glow_color=str(raw.get("glow_color") or "#FFFFFF"),
            glow_radius=_clamp_int(raw.get("glow_radius", 6), 0, 24, 6),
            base_scale=_clamp_float(raw.get("base_scale", 0.14), 0.03, 0.55, 0.14),
            opacity=_clamp_int(raw.get("opacity", 75), 10, 100, 75),
            rotation_range=_clamp_int(raw.get("rotation_range", 18), 0, 45, 18),
            builtin=bool(raw.get("builtin", False)),
        )


@dataclass
class CreativePlacement:
    """One placed watermark layer on an image canvas (auto-generated or manually dragged)."""

    id: str = field(default_factory=lambda: new_id("lyr"))
    asset_id: str = ""
    x: float = 0.5  # normalized center X (0..1)
    y: float = 0.5  # normalized center Y (0..1)
    scale: float = 0.14  # rendered width as fraction of image short edge (0.02..0.90)
    rotation: float = 0.0  # degrees (-180..180, positive = CCW in Pillow / negated in Canvas)
    opacity: int = 75  # 5..100
    glow_enabled: bool = True
    locked: bool = False  # if True, auto-layout keeps this layer untouched
    auto_generated: bool = False
    z_index: int = 0

    def clone(self, *, new_layer_id: bool = False) -> CreativePlacement:
        data = asdict(self)
        if new_layer_id:
            data["id"] = new_id("lyr")
        return CreativePlacement(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CreativePlacement:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            id=str(raw.get("id") or new_id("lyr")),
            asset_id=str(raw.get("asset_id") or ""),
            x=_clamp_float(raw.get("x", 0.5), -0.15, 1.15, 0.5),
            y=_clamp_float(raw.get("y", 0.5), -0.15, 1.15, 0.5),
            scale=_clamp_float(raw.get("scale", 0.14), 0.02, 0.90, 0.14),
            rotation=_clamp_float(raw.get("rotation", 0.0), -180.0, 180.0, 0.0),
            opacity=_clamp_int(raw.get("opacity", 75), 5, 100, 75),
            glow_enabled=bool(raw.get("glow_enabled", True)),
            locked=bool(raw.get("locked", False)),
            auto_generated=bool(raw.get("auto_generated", False)),
            z_index=_clamp_int(raw.get("z_index", 0), -1000, 10000, 0),
        )


@dataclass
class AutoLayoutConfig:
    """Parameters governing the subject-aware multi-scale aesthetic auto-layout algorithm."""

    style: str = "artistic_scatter"
    density: int = 58  # 10..100
    scale_variation: int = 72  # 0..100 (controls big/medium/small contrast)
    subject_avoidance: int = 75  # 0..100 (protects face/center focal region)
    global_opacity: int = 78  # 15..100
    rotation_jitter: int = 18  # 0..45 degrees
    soft_glow: bool = True  # dreamy white outer glow + subtle dark halo
    include_micro_grid: bool = True  # sprinkle delicate low-opacity micro stamps
    seed: int = 202601

    def clone(self) -> AutoLayoutConfig:
        return AutoLayoutConfig(**asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AutoLayoutConfig:
        if not isinstance(raw, dict):
            return cls()
        style = str(raw.get("style", "artistic_scatter")).strip().lower()
        if style not in VALID_LAYOUT_STYLES:
            style = "artistic_scatter"
        return cls(
            style=style,
            density=_clamp_int(raw.get("density", 58), 10, 100, 58),
            scale_variation=_clamp_int(raw.get("scale_variation", 72), 0, 100, 72),
            subject_avoidance=_clamp_int(raw.get("subject_avoidance", 75), 0, 100, 75),
            global_opacity=_clamp_int(raw.get("global_opacity", 78), 15, 100, 78),
            rotation_jitter=_clamp_int(raw.get("rotation_jitter", 18), 0, 45, 18),
            soft_glow=bool(raw.get("soft_glow", True)),
            include_micro_grid=bool(raw.get("include_micro_grid", True)),
            seed=_clamp_int(raw.get("seed", 202601), 0, 2_147_483_647, 202601),
        )
