"""Core Pillow watermarking engine with exact WYSIWYG preview/export scaling."""

from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, ImageOps

from .fonts import load_truetype_font, resolve_font_path
from .models import (
    AnchorPosition,
    ConflictPolicy,
    ExportConfig,
    LayoutMode,
    OrientationGroup,
    OutputFormat,
    SUPPORTED_INPUT_EXTENSIONS,
    SUPPORTED_MEDIA_EXTENSIONS,
    WatermarkConfig,
    WatermarkType,
)


PREVIEW_MAX_EDGE = 640


def _scan_files_by_extensions(
    paths: Iterable[Path],
    allowed_exts: set[str],
    recursive: bool = True,
) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()

    def _add_file(fp: Path) -> None:
        if fp.suffix.lower() not in allowed_exts:
            return
        try:
            key = str(fp.resolve()).lower()
        except OSError:
            key = str(fp).lower()
        if key not in seen:
            seen.add(key)
            result.append(fp)

    for p in paths:
        p = Path(p)
        if p.is_file():
            _add_file(p)
        elif p.is_dir():
            iterator = p.rglob("*") if recursive else p.iterdir()
            try:
                children = sorted(iterator, key=lambda x: str(x).lower())
            except OSError:
                children = []
            for child in children:
                if child.is_file():
                    _add_file(child)
    return result


def scan_image_files(paths: Iterable[Path], recursive: bool = True) -> list[Path]:
    """Collect supported image files from file/directory paths, deduplicated in order."""
    return _scan_files_by_extensions(paths, set(SUPPORTED_INPUT_EXTENSIONS), recursive=recursive)


def scan_media_files(
    paths: Iterable[Path],
    recursive: bool = True,
    include_videos: bool = True,
) -> list[Path]:
    """Collect supported image (and optionally video) files from file/directory paths."""
    allowed = set(SUPPORTED_MEDIA_EXTENSIONS if include_videos else SUPPORTED_INPUT_EXTENSIONS)
    return _scan_files_by_extensions(paths, allowed, recursive=recursive)


def load_image_oriented(path: Path) -> tuple[Image.Image, str, bytes | None]:
    """Open an image, apply EXIF orientation, and return (image, orig_format, normalized_exif)."""
    with Image.open(path) as img:
        orig_format = (img.format or "").upper()
        had_exif = bool(img.info.get("exif"))
        # Transpose FIRST before touching EXIF tags (img.getexif() is cached on img!)
        transposed = ImageOps.exif_transpose(img)
        if transposed is None:
            transposed = img.copy()
        else:
            transposed = transposed.copy()

        exif_bytes: bytes | None = None
        if had_exif or transposed.info.get("exif"):
            try:
                exif = transposed.getexif()
                exif[274] = 1  # Pixels are already oriented upright
                exif_bytes = exif.tobytes()
            except Exception:  # noqa: BLE001
                exif_bytes = None
    return transposed, orig_format, exif_bytes


def create_preview_base(
    path: Path,
    max_edge: int = PREVIEW_MAX_EDGE,
) -> tuple[Image.Image, int, int, str, int]:
    """Load an image and return (rgba_preview_base, orig_w, orig_h, orig_format, file_size)."""
    file_size = path.stat().st_size if path.exists() else 0
    img, orig_format, _ = load_image_oriented(path)
    orig_w, orig_h = img.size

    if max(orig_w, orig_h) > max_edge:
        scale = max_edge / max(orig_w, orig_h)
        new_w = max(1, int(round(orig_w * scale)))
        new_h = max(1, int(round(orig_h * scale)))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    rgba = img.convert("RGBA")
    return rgba, orig_w, orig_h, orig_format, file_size


def _parse_hex_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    try:
        r, g, b = ImageColor.getrgb(hex_color)[:3]
    except ValueError:
        r, g, b = 255, 255, 255
    return (r, g, b, max(0, min(255, int(alpha))))


@lru_cache(maxsize=16)
def _load_logo_cached(logo_path: str, mtime_ns: int) -> Image.Image | None:
    """Load and cache logo watermark as RGBA."""
    del mtime_ns  # Used only as cache invalidation key
    try:
        with Image.open(logo_path) as im:
            im = ImageOps.exif_transpose(im)
            return im.convert("RGBA")
    except OSError:
        return None


def _get_logo_image(logo_path: str) -> Image.Image | None:
    if not logo_path:
        return None
    p = Path(logo_path)
    if not p.is_file():
        return None
    try:
        stat = p.stat()
    except OSError:
        return None
    return _load_logo_cached(str(p), stat.st_mtime_ns)


def _scale_alpha(img: Image.Image, opacity_percent: int) -> Image.Image:
    """Multiply the alpha channel of an RGBA image by opacity_percent / 100."""
    factor = max(0.0, min(1.0, opacity_percent / 100.0))
    if factor >= 0.999:
        return img
    out = img.copy()
    alpha = out.getchannel("A")
    alpha = alpha.point(lambda a: int(round(a * factor)))
    out.putalpha(alpha)
    return out


def _build_text_stamp(
    config: WatermarkConfig,
    canvas_w: int,
    canvas_h: int,
    ref_w: int,
    ref_h: int,
) -> Image.Image | None:
    """Render an unrotated RGBA text stamp scaled accurately for canvas vs reference size."""
    text = config.text
    if not text or not text.strip():
        return None

    preview_ratio = canvas_w / max(1, ref_w)
    ref_short = min(ref_w, ref_h)

    if config.proportional_size:
        target_font_px = config.font_size * (ref_short / 1000.0) * preview_ratio
        unit_scale = (ref_short / 1000.0) * preview_ratio
    else:
        target_font_px = config.font_size * preview_ratio
        unit_scale = preview_ratio

    font_px = max(6, int(round(target_font_px)))
    font_path = resolve_font_path(config.font_name, config.custom_font_path)
    font = load_truetype_font(font_path, font_px)

    stroke_w = max(0, int(round(config.stroke_width * unit_scale))) if config.stroke_enabled else 0
    if config.stroke_enabled and config.stroke_width > 0 and stroke_w == 0:
        stroke_w = 1

    shadow_off = max(0, int(round(config.shadow_offset * unit_scale))) if config.shadow_enabled else 0
    if config.shadow_enabled and config.shadow_offset > 0 and shadow_off == 0:
        shadow_off = 1

    spacing_px = max(0, int(round(font_px * max(0.0, config.line_spacing - 1.0))))

    dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    dummy_draw = ImageDraw.Draw(dummy)
    bbox = dummy_draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=spacing_px,
        stroke_width=stroke_w,
        align="center",
    )
    text_w = max(1, int(math.ceil(bbox[2] - bbox[0])))
    text_h = max(1, int(math.ceil(bbox[3] - bbox[1])))

    pad = stroke_w + 4
    stamp_w = text_w + pad * 2 + shadow_off
    stamp_h = text_h + pad * 2 + shadow_off

    stamp = Image.new("RGBA", (stamp_w, stamp_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stamp)

    draw_x = pad - bbox[0]
    draw_y = pad - bbox[1]

    if shadow_off > 0:
        shadow_rgba = _parse_hex_rgba(config.shadow_color, alpha=165)
        draw.multiline_text(
            (draw_x + shadow_off, draw_y + shadow_off),
            text,
            font=font,
            fill=shadow_rgba,
            spacing=spacing_px,
            align="center",
            stroke_width=stroke_w,
            stroke_fill=shadow_rgba if stroke_w > 0 else None,
        )

    fill_rgba = _parse_hex_rgba(config.text_color, alpha=255)
    stroke_rgba = _parse_hex_rgba(config.stroke_color, alpha=255) if stroke_w > 0 else None
    draw.multiline_text(
        (draw_x, draw_y),
        text,
        font=font,
        fill=fill_rgba,
        spacing=spacing_px,
        align="center",
        stroke_width=stroke_w,
        stroke_fill=stroke_rgba,
    )

    return _scale_alpha(stamp, config.opacity)


def _build_logo_stamp(
    config: WatermarkConfig,
    canvas_w: int,
    canvas_h: int,
    ref_w: int,
    ref_h: int,
) -> Image.Image | None:
    """Render an unrotated RGBA logo stamp scaled accurately for canvas vs reference size."""
    logo = _get_logo_image(config.logo_path)
    if logo is None:
        return None

    preview_ratio = canvas_w / max(1, ref_w)
    scale_pct = max(1, min(300, int(config.logo_scale_percent)))

    if config.proportional_size:
        target_w = max(8, int(round(ref_w * (scale_pct / 100.0) * preview_ratio)))
    else:
        target_w = max(8, int(round(logo.width * (scale_pct / 100.0) * preview_ratio)))

    aspect = logo.height / max(1, logo.width)
    target_h = max(8, int(round(target_w * aspect)))

    resized = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
    return _scale_alpha(resized, config.opacity)


def _alpha_composite_clipped(
    canvas: Image.Image,
    stamp: Image.Image,
    x: int,
    y: int,
) -> None:
    """Composite `stamp` onto `canvas` at `(x, y)` with safe boundary clipping."""
    cw, ch = canvas.size
    sw, sh = stamp.size

    if x >= cw or y >= ch or x + sw <= 0 or y + sh <= 0:
        return

    dest_x = max(0, x)
    dest_y = max(0, y)
    src_x = max(0, -x)
    src_y = max(0, -y)

    canvas.alpha_composite(stamp, dest=(dest_x, dest_y), source=(src_x, src_y))


def _compute_single_position(
    canvas_w: int,
    canvas_h: int,
    stamp_w: int,
    stamp_h: int,
    config: WatermarkConfig,
) -> tuple[int, int]:
    """Compute top-left coordinates for single watermark mode."""
    margin_x = canvas_w * (config.margin_x_percent / 100.0)
    margin_y = canvas_h * (config.margin_y_percent / 100.0)

    anchor = config.anchor
    if anchor in (AnchorPosition.TOP_LEFT, AnchorPosition.MIDDLE_LEFT, AnchorPosition.BOTTOM_LEFT):
        x = margin_x
    elif anchor in (AnchorPosition.TOP_CENTER, AnchorPosition.CENTER, AnchorPosition.BOTTOM_CENTER):
        x = (canvas_w - stamp_w) / 2.0
    else:
        x = canvas_w - stamp_w - margin_x

    if anchor in (AnchorPosition.TOP_LEFT, AnchorPosition.TOP_CENTER, AnchorPosition.TOP_RIGHT):
        y = margin_y
    elif anchor in (AnchorPosition.MIDDLE_LEFT, AnchorPosition.CENTER, AnchorPosition.MIDDLE_RIGHT):
        y = (canvas_h - stamp_h) / 2.0
    else:
        y = canvas_h - stamp_h - margin_y

    x += canvas_w * (config.offset_x_percent / 100.0)
    y += canvas_h * (config.offset_y_percent / 100.0)

    return int(round(x)), int(round(y))


def build_watermark_overlay(
    canvas_size: tuple[int, int],
    config: WatermarkConfig,
    reference_size: tuple[int, int] | None = None,
) -> Image.Image:
    """Build a standalone transparent RGBA watermark overlay matching `canvas_size`.

    Shared by both image watermarking and video FFmpeg overlay compositing for 100% WYSIWYG parity.
    """
    canvas_w, canvas_h = max(1, int(canvas_size[0])), max(1, int(canvas_size[1]))
    ref_w, ref_h = reference_size if reference_size else (canvas_w, canvas_h)

    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if config.opacity <= 0:
        return overlay

    if config.watermark_type == WatermarkType.TEXT:
        stamp = _build_text_stamp(config, canvas_w, canvas_h, ref_w, ref_h)
    else:
        stamp = _build_logo_stamp(config, canvas_w, canvas_h, ref_w, ref_h)

    if stamp is None:
        return overlay

    orig_sw, orig_sh = stamp.size
    angle = float(config.rotation)
    if abs(angle) > 0.01:
        rot_stamp = stamp.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    else:
        rot_stamp = stamp

    rw, rh = rot_stamp.size

    if config.layout_mode == LayoutMode.SINGLE:
        px, py = _compute_single_position(canvas_w, canvas_h, rw, rh, config)
        _alpha_composite_clipped(overlay, rot_stamp, px, py)
    else:
        preview_ratio = canvas_w / max(1, ref_w)
        ref_short = min(ref_w, ref_h)
        if config.proportional_size:
            unit_scale = (ref_short / 1000.0) * preview_ratio
        else:
            unit_scale = preview_ratio

        gap_x = max(0.0, config.tile_spacing_x * unit_scale)
        gap_y = max(0.0, config.tile_spacing_y * unit_scale)

        step_x = max(12.0, orig_sw + gap_x)
        step_y = max(12.0, orig_sh + gap_y)

        rad = math.radians(angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        ux, uy = cos_a, -sin_a
        vx, vy = sin_a, cos_a

        cx_canvas = canvas_w / 2.0 + canvas_w * (config.offset_x_percent / 100.0)
        cy_canvas = canvas_h / 2.0 + canvas_h * (config.offset_y_percent / 100.0)

        radius = math.hypot(canvas_w, canvas_h) * 0.55 + max(rw, rh)
        max_i = min(80, int(math.ceil(radius / step_x)) + 1)
        max_j = min(80, int(math.ceil(radius / step_y)) + 1)

        half_rw = rw / 2.0
        half_rh = rh / 2.0

        for j in range(-max_j, max_j + 1):
            stagger_shift = 0.5 if (config.tile_stagger and (j % 2 != 0)) else 0.0
            for i in range(-max_i, max_i + 1):
                lx = (i + stagger_shift) * step_x
                ly = j * step_y

                center_x = cx_canvas + lx * ux + ly * vx
                center_y = cy_canvas + lx * uy + ly * vy

                px = int(round(center_x - half_rw))
                py = int(round(center_y - half_rh))

                if px >= canvas_w or py >= canvas_h or px + rw <= 0 or py + rh <= 0:
                    continue
                _alpha_composite_clipped(overlay, rot_stamp, px, py)

    return overlay


def apply_watermark(
    base_image: Image.Image,
    config: WatermarkConfig,
    reference_size: tuple[int, int] | None = None,
) -> Image.Image:
    """Apply configured watermark onto `base_image` and return a new RGBA image."""
    base_rgba = base_image if base_image.mode == "RGBA" else base_image.convert("RGBA")
    if config.opacity <= 0:
        return base_rgba.copy()

    overlay = build_watermark_overlay(base_rgba.size, config, reference_size=reference_size)
    return Image.alpha_composite(base_rgba, overlay)


def _resolve_target_format_and_ext(src_path: Path, orig_format: str, out_format: OutputFormat) -> tuple[str, str]:
    """Return (PIL_format, file_extension_with_dot)."""
    if out_format == OutputFormat.PNG:
        return "PNG", ".png"
    if out_format == OutputFormat.JPEG:
        return "JPEG", ".jpg"
    if out_format == OutputFormat.WEBP:
        return "WEBP", ".webp"

    ext = src_path.suffix.lower()
    fmt_map = {
        ".jpg": ("JPEG", ".jpg"),
        ".jpeg": ("JPEG", ".jpeg"),
        ".png": ("PNG", ".png"),
        ".webp": ("WEBP", ".webp"),
        ".bmp": ("BMP", ".bmp"),
        ".tif": ("TIFF", ".tif"),
        ".tiff": ("TIFF", ".tiff"),
    }
    if ext in fmt_map:
        return fmt_map[ext]
    if orig_format in {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}:
        default_ext = ".jpg" if orig_format == "JPEG" else f".{orig_format.lower()}"
        return orig_format, default_ext
    return "PNG", ".png"


def resolve_output_path(
    src_path: Path,
    export_config: ExportConfig,
    ext: str,
    orientation: OrientationGroup | None = None,
) -> Path:
    """Compute final output file path respecting orientation isolation & conflict policy."""
    out_dir = Path(export_config.output_dir)
    if export_config.isolate_orientation and orientation is not None:
        sub = (
            export_config.portrait_subfolder
            if orientation == OrientationGroup.PORTRAIT
            else export_config.landscape_subfolder
        )
        out_dir = out_dir / (sub.strip() or ("竖版" if orientation == OrientationGroup.PORTRAIT else "横版"))

    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{export_config.filename_prefix}{src_path.stem}{export_config.filename_suffix}"
    candidate = out_dir / f"{stem}{ext}"

    if export_config.conflict_policy == ConflictPolicy.OVERWRITE or not candidate.exists():
        return candidate

    counter = 1
    while True:
        alt = out_dir / f"{stem}_{counter}{ext}"
        if not alt.exists():
            return alt
        counter += 1


def export_single_image(
    src_path: Path,
    wm_config: WatermarkConfig,
    export_config: ExportConfig,
) -> Path:
    """Apply full-resolution watermark to `src_path` and save to `export_config.output_dir`."""
    img, orig_format, exif_bytes = load_image_oriented(src_path)
    orig_w, orig_h = img.size
    orientation = OrientationGroup.PORTRAIT if orig_h > orig_w else OrientationGroup.LANDSCAPE

    watermarked_rgba = apply_watermark(img, wm_config, reference_size=(orig_w, orig_h))

    pil_fmt, ext = _resolve_target_format_and_ext(src_path, orig_format, export_config.output_format)
    out_path = resolve_output_path(src_path, export_config, ext, orientation=orientation)

    save_kwargs: dict[str, object] = {}
    if pil_fmt in {"JPEG", "BMP"}:
        bg = Image.new("RGB", watermarked_rgba.size, (255, 255, 255))
        bg.paste(watermarked_rgba, mask=watermarked_rgba.getchannel("A"))
        to_save = bg
    elif pil_fmt == "TIFF":
        to_save = watermarked_rgba if img.mode in {"RGBA", "LA", "PA"} else watermarked_rgba.convert("RGB")
    else:
        to_save = watermarked_rgba

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
