"""Unit tests for the core Pillow watermarking and batch export engine."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageChops

from batch_watermark.engine import (
    apply_watermark,
    create_preview_base,
    export_single_image,
    load_image_oriented,
    scan_image_files,
)
from batch_watermark.models import (
    AnchorPosition,
    ConflictPolicy,
    ExportConfig,
    LayoutMode,
    OutputFormat,
    WatermarkConfig,
    WatermarkType,
)


def _diff_pixel_count(img_a: Image.Image, img_b: Image.Image, threshold: int = 8) -> int:
    diff = ImageChops.difference(img_a.convert("RGB"), img_b.convert("RGB"))
    # Count pixels where any channel exceeds threshold
    data = diff.tobytes()
    count = 0
    for i in range(0, len(data), 3):
        if data[i] > threshold or data[i + 1] > threshold or data[i + 2] > threshold:
            count += 1
    return count


def _make_sample_image(path: Path, size: tuple[int, int] = (400, 300), color=(30, 60, 120)) -> Path:
    img = Image.new("RGB", size, color)
    img.save(path)
    return path


def test_scan_image_files_recursive_and_dedup(tmp_path: Path) -> None:
    sub = tmp_path / "nested"
    sub.mkdir()
    img1 = _make_sample_image(tmp_path / "a.jpg")
    img2 = _make_sample_image(sub / "b.png")
    (tmp_path / "notes.txt").write_text("not an image", encoding="utf-8")

    found_recursive = scan_image_files([tmp_path, img1], recursive=True)
    assert [p.resolve() for p in found_recursive] == [img1.resolve(), img2.resolve()]

    found_flat = scan_image_files([tmp_path], recursive=False)
    assert [p.resolve() for p in found_flat] == [img1.resolve()]


def test_text_watermark_chinese_multiline_and_opacity_zero() -> None:
    base = Image.new("RGBA", (600, 400), (20, 40, 80, 255))

    cfg_zero = WatermarkConfig(text="测试水印\n第二行", opacity=0)
    out_zero = apply_watermark(base, cfg_zero)
    assert _diff_pixel_count(base, out_zero) == 0

    cfg_visible = WatermarkConfig(
        text="测试水印\nBatchWatermark",
        opacity=85,
        layout_mode=LayoutMode.SINGLE,
        anchor=AnchorPosition.CENTER,
        stroke_enabled=True,
        shadow_enabled=True,
    )
    out_visible = apply_watermark(base, cfg_visible)
    assert _diff_pixel_count(base, out_visible) > 500


def test_single_mode_anchor_regions() -> None:
    base = Image.new("RGBA", (600, 600), (15, 20, 30, 255))

    cfg_tl = WatermarkConfig(
        text="TL",
        font_size=70,
        opacity=100,
        rotation=0,
        layout_mode=LayoutMode.SINGLE,
        anchor=AnchorPosition.TOP_LEFT,
        margin_x_percent=3.0,
        margin_y_percent=3.0,
    )
    out_tl = apply_watermark(base, cfg_tl)
    top_left_diff = _diff_pixel_count(base.crop((0, 0, 300, 300)), out_tl.crop((0, 0, 300, 300)))
    bot_right_diff = _diff_pixel_count(base.crop((300, 300, 600, 600)), out_tl.crop((300, 300, 600, 600)))
    assert top_left_diff > 100
    assert bot_right_diff == 0

    cfg_br = cfg_tl.clone()
    cfg_br.anchor = AnchorPosition.BOTTOM_RIGHT
    out_br = apply_watermark(base, cfg_br)
    assert _diff_pixel_count(base.crop((300, 300, 600, 600)), out_br.crop((300, 300, 600, 600))) > 100
    assert _diff_pixel_count(base.crop((0, 0, 300, 300)), out_br.crop((0, 0, 300, 300))) == 0


def test_tiled_rotated_staggered_covers_all_quadrants() -> None:
    base = Image.new("RGBA", (800, 600), (25, 35, 50, 255))
    cfg = WatermarkConfig(
        text="版权保护",
        font_size=50,
        opacity=75,
        rotation=-30,
        layout_mode=LayoutMode.TILED,
        tile_spacing_x=110,
        tile_spacing_y=90,
        tile_stagger=True,
    )
    out = apply_watermark(base, cfg)
    quadrants = [
        (0, 0, 400, 300),
        (400, 0, 800, 300),
        (0, 300, 400, 600),
        (400, 300, 800, 600),
    ]
    for box in quadrants:
        assert _diff_pixel_count(base.crop(box), out.crop(box)) > 200


def test_logo_image_watermark(tmp_path: Path) -> None:
    logo_path = tmp_path / "logo.png"
    logo = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    for y in range(10, 50):
        for x in range(10, 110):
            logo.putpixel((x, y), (255, 80, 40, 230))
    logo.save(logo_path)

    base = Image.new("RGBA", (500, 400), (20, 25, 30, 255))
    cfg = WatermarkConfig(
        watermark_type=WatermarkType.IMAGE,
        logo_path=str(logo_path),
        logo_scale_percent=25,
        opacity=80,
        rotation=0,
        layout_mode=LayoutMode.SINGLE,
        anchor=AnchorPosition.CENTER,
    )
    out = apply_watermark(base, cfg)
    assert _diff_pixel_count(base, out) > 1000


def test_wysiwyg_preview_matches_full_res_ratio() -> None:
    full = Image.new("RGBA", (1600, 1200), (30, 30, 40, 255))
    preview = full.resize((640, 480))

    cfg = WatermarkConfig(
        text="WYSIWYG",
        font_size=60,
        proportional_size=True,
        stroke_enabled=False,
        shadow_enabled=False,
        opacity=100,
        rotation=0,
        layout_mode=LayoutMode.SINGLE,
        anchor=AnchorPosition.BOTTOM_RIGHT,
        margin_x_percent=5.0,
        margin_y_percent=5.0,
    )
    full_wm = apply_watermark(full, cfg, reference_size=full.size)
    prev_wm = apply_watermark(preview, cfg, reference_size=full.size)

    full_bbox = ImageChops.difference(full.convert("RGB"), full_wm.convert("RGB")).getbbox()
    prev_bbox = ImageChops.difference(preview.convert("RGB"), prev_wm.convert("RGB")).getbbox()
    assert full_bbox is not None and prev_bbox is not None

    # Normalized bounding boxes (x0/w, y0/h, x1/w, y1/h) must closely align between preview and full-res
    full_norm = (
        full_bbox[0] / full.width,
        full_bbox[1] / full.height,
        full_bbox[2] / full.width,
        full_bbox[3] / full.height,
    )
    prev_norm = (
        prev_bbox[0] / preview.width,
        prev_bbox[1] / preview.height,
        prev_bbox[2] / preview.width,
        prev_bbox[3] / preview.height,
    )
    for fn, pn in zip(full_norm, prev_norm):
        assert abs(fn - pn) < 0.02

    # Mean ink intensity per pixel (insensitive to 1px anti-aliasing threshold bias)
    full_diff = ImageChops.difference(full.convert("RGB"), full_wm.convert("RGB")).tobytes()
    prev_diff = ImageChops.difference(preview.convert("RGB"), prev_wm.convert("RGB")).tobytes()
    full_mean = sum(full_diff) / len(full_diff)
    prev_mean = sum(prev_diff) / len(prev_diff)
    assert full_mean > 0.3
    assert abs(full_mean - prev_mean) / full_mean < 0.12


def test_exif_orientation_normalized_on_export(tmp_path: Path) -> None:
    # Create a 300x200 JPEG tagged with EXIF Orientation=6 (90 deg CW -> should display as 200x300)
    src = tmp_path / "rotated.jpg"
    raw = Image.new("RGB", (300, 200), (50, 90, 140))
    exif = raw.getexif()
    exif[274] = 6  # Rotate 90 CW
    raw.save(src, format="JPEG", exif=exif.tobytes())

    oriented, fmt, normalized_exif = load_image_oriented(src)
    assert fmt == "JPEG"
    assert oriented.size == (200, 300)
    assert normalized_exif is not None

    out_dir = tmp_path / "out"
    out_path = export_single_image(
        src,
        WatermarkConfig(text="EXIF OK", opacity=70),
        ExportConfig(output_dir=str(out_dir), output_format=OutputFormat.KEEP_ORIGINAL, keep_exif=True),
    )
    with Image.open(out_path) as exported:
        assert exported.size == (200, 300)
        exported_exif = exported.getexif()
        assert exported_exif.get(274, 1) == 1


def test_export_formats_naming_and_conflict_policies(tmp_path: Path) -> None:
    # Source RGBA PNG with transparency
    src = tmp_path / "hero.png"
    img = Image.new("RGBA", (320, 240), (40, 120, 200, 180))
    img.save(src)

    out_dir = tmp_path / "exports"
    wm = WatermarkConfig(text="导出测试", opacity=80)

    # Export to JPEG with prefix/suffix
    exp_cfg = ExportConfig(
        output_dir=str(out_dir),
        filename_prefix="pre_",
        filename_suffix="_wm",
        output_format=OutputFormat.JPEG,
        quality=90,
        conflict_policy=ConflictPolicy.AUTO_RENAME,
    )
    out1 = export_single_image(src, wm, exp_cfg)
    assert out1.name == "pre_hero_wm.jpg"
    assert out1.exists()

    # Second export with AUTO_RENAME produces _1
    out2 = export_single_image(src, wm, exp_cfg)
    assert out2.name == "pre_hero_wm_1.jpg"
    assert out2.exists()

    # OVERWRITE reuses base name
    exp_cfg.conflict_policy = ConflictPolicy.OVERWRITE
    out3 = export_single_image(src, wm, exp_cfg)
    assert out3 == out1

    # Export to WebP
    exp_cfg.output_format = OutputFormat.WEBP
    out_webp = export_single_image(src, wm, exp_cfg)
    assert out_webp.suffix == ".webp"
    assert out_webp.exists()

    # Preview base helper sanity
    rgba, ow, oh, ofmt, fsize = create_preview_base(src, max_edge=160)
    assert (ow, oh) == (320, 240)
    assert rgba.size == (160, 120)
    assert ofmt == "PNG"
    assert fsize > 0
