"""Data models and configuration definitions for BatchWatermark."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class OrientationGroup(str, Enum):
    LANDSCAPE = "landscape"  # width >= height
    PORTRAIT = "portrait"    # height > width


class WatermarkType(str, Enum):
    TEXT = "text"
    IMAGE = "image"


class LayoutMode(str, Enum):
    SINGLE = "single"
    TILED = "tiled"


class AnchorPosition(str, Enum):
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    MIDDLE_LEFT = "middle_left"
    CENTER = "center"
    MIDDLE_RIGHT = "middle_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


class OutputFormat(str, Enum):
    KEEP_ORIGINAL = "keep"
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class ConflictPolicy(str, Enum):
    AUTO_RENAME = "auto_rename"
    OVERWRITE = "overwrite"


SUPPORTED_INPUT_EXTENSIONS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
)

SUPPORTED_VIDEO_EXTENSIONS: tuple[str, ...] = (
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".wmv",
    ".flv",
)

SUPPORTED_MEDIA_EXTENSIONS: tuple[str, ...] = SUPPORTED_INPUT_EXTENSIONS + SUPPORTED_VIDEO_EXTENSIONS


@dataclass
class WatermarkConfig:
    """All parameters controlling watermark rendering."""

    watermark_type: WatermarkType = WatermarkType.TEXT

    # Text watermark settings
    text: str = "© 仅供内部使用"
    font_name: str = "微软雅黑"
    custom_font_path: str = ""
    font_size: int = 44  # Relative to 1000px short edge when proportional=True, else raw px
    proportional_size: bool = True
    text_color: str = "#FFFFFF"
    line_spacing: float = 1.25

    # Stroke & Shadow
    stroke_enabled: bool = True
    stroke_width: int = 2
    stroke_color: str = "#000000"
    shadow_enabled: bool = True
    shadow_offset: int = 3
    shadow_color: str = "#000000"

    # Image/Logo watermark settings
    logo_path: str = ""
    logo_scale_percent: int = 22  # % of target width (when proportional) or % of logo native size

    # Common appearance
    opacity: int = 55  # 0..100
    rotation: int = -25  # -180..180 degrees (positive = CCW, negative = CW)

    # Layout & positioning
    layout_mode: LayoutMode = LayoutMode.TILED
    anchor: AnchorPosition = AnchorPosition.BOTTOM_RIGHT
    margin_x_percent: float = 4.0  # % of media width
    margin_y_percent: float = 4.0  # % of media height
    offset_x_percent: float = 0.0  # fine offset -50..50 %
    offset_y_percent: float = 0.0  # fine offset -50..50 %

    # Tiled settings
    tile_spacing_x: int = 120  # Relative to 1000px short edge when proportional=True, else raw px
    tile_spacing_y: int = 100
    tile_stagger: bool = True

    def clone(self) -> WatermarkConfig:
        return WatermarkConfig(**asdict(self))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["watermark_type"] = self.watermark_type.value
        data["layout_mode"] = self.layout_mode.value
        data["anchor"] = self.anchor.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WatermarkConfig:
        cleaned = dict(data)
        if "watermark_type" in cleaned:
            try:
                cleaned["watermark_type"] = WatermarkType(cleaned["watermark_type"])
            except ValueError:
                cleaned["watermark_type"] = WatermarkType.TEXT
        if "layout_mode" in cleaned:
            try:
                cleaned["layout_mode"] = LayoutMode(cleaned["layout_mode"])
            except ValueError:
                cleaned["layout_mode"] = LayoutMode.TILED
        if "anchor" in cleaned:
            try:
                cleaned["anchor"] = AnchorPosition(cleaned["anchor"])
            except ValueError:
                cleaned["anchor"] = AnchorPosition.BOTTOM_RIGHT
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in cleaned.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class ExportConfig:
    """Parameters controlling batch image & video export."""

    output_dir: str = ""
    filename_prefix: str = ""
    filename_suffix: str = "_watermarked"
    output_format: OutputFormat = OutputFormat.KEEP_ORIGINAL
    quality: int = 92  # 50..100 for JPEG/WebP & mapped to H.264 CRF for video
    keep_exif: bool = True
    conflict_policy: ConflictPolicy = ConflictPolicy.AUTO_RENAME
    isolate_orientation: bool = False
    landscape_subfolder: str = "横版"
    portrait_subfolder: str = "竖版"
    video_keep_audio: bool = True


@dataclass
class ImageItem:
    """Represents one loaded image or video item in the batch workspace."""

    id: str
    path: Path
    media_type: MediaType = MediaType.IMAGE
    filename: str = ""
    orig_width: int = 0
    orig_height: int = 0
    orig_format: str = ""
    file_size_bytes: int = 0
    duration_sec: float = 0.0
    # Cached oriented thumbnail / representative frame (PIL.Image RGBA) for fast live preview
    preview_base: Any = field(default=None, repr=False, compare=False)
    load_error: str = ""

    def __post_init__(self) -> None:
        if not self.filename:
            self.filename = self.path.name
        if self.path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            self.media_type = MediaType.VIDEO

    @property
    def is_video(self) -> bool:
        return self.media_type == MediaType.VIDEO

    @property
    def orientation(self) -> OrientationGroup:
        if self.orig_height > self.orig_width > 0:
            return OrientationGroup.PORTRAIT
        return OrientationGroup.LANDSCAPE

    @property
    def resolution_text(self) -> str:
        if self.orig_width > 0 and self.orig_height > 0:
            return f"{self.orig_width} × {self.orig_height}"
        return "加载中..."

    @property
    def duration_text(self) -> str:
        if not self.is_video:
            return ""
        total = max(0, int(round(self.duration_sec)))
        mins, secs = divmod(total, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    @property
    def file_size_text(self) -> str:
        size = self.file_size_bytes
        if size <= 0:
            return ""
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.2f} MB"


MediaItem = ImageItem
