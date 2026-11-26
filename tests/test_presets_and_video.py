"""Tests for custom preset persistence/import/export, orientation-isolated export, and video watermarking."""

from __future__ import annotations

from pathlib import Path
import subprocess

from PIL import Image, ImageChops
import pytest

from batch_watermark.engine import export_single_image, scan_media_files
from batch_watermark.models import (
    AnchorPosition,
    ExportConfig,
    LayoutMode,
    OutputFormat,
    WatermarkConfig,
)
from batch_watermark.presets import PresetStore
from batch_watermark.video_engine import (
    export_single_video,
    extract_video_frame,
    find_ffmpeg_executable,
)


def _generate_test_mp4(dest: Path, width: int, height: int, duration_sec: float = 1.0, with_audio: bool = True) -> Path:
    ffmpeg = find_ffmpeg_executable()
    assert ffmpeg is not None, "FFmpeg must be available for video tests"
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x1E3A5F:s={width}x{height}:r=15:d={duration_sec}",
    ]
    if with_audio:
        cmd.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_sec}"])
    cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if with_audio:
        cmd.extend(["-c:a", "aac", "-shortest"])
    cmd.append(str(dest))
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Failed to synthesize test video: {res.stderr}"
    return dest


def _mean_rgb_diff(img_a: Image.Image, img_b: Image.Image) -> float:
    diff = ImageChops.difference(img_a.convert("RGB"), img_b.convert("RGB")).tobytes()
    return sum(diff) / max(1, len(diff))


# ---- Preset Store Tests ----


def test_preset_store_local_save_reload_and_delete(tmp_path: Path) -> None:
    storage = tmp_path / "app_data" / "custom_presets.json"
    store = PresetStore(storage_path=storage)
    assert store.list_custom() == {}

    cfg = WatermarkConfig(
        text="我的专属品牌",
        font_size=52,
        text_color="#F59E0B",
        opacity=88,
        rotation=-15,
        layout_mode=LayoutMode.SINGLE,
        anchor=AnchorPosition.TOP_RIGHT,
    )
    saved_name = store.save_custom("品牌右上角", cfg)
    assert saved_name == "品牌右上角"
    assert storage.is_file()

    # Fresh PresetStore simulating app restart loads saved custom preset from local disk
    reloaded_store = PresetStore(storage_path=storage)
    loaded = reloaded_store.get_custom("品牌右上角")
    assert loaded is not None
    assert loaded.text == "我的专属品牌"
    assert loaded.font_size == 52
    assert loaded.text_color == "#F59E0B"
    assert loaded.anchor == AnchorPosition.TOP_RIGHT
    assert loaded.layout_mode == LayoutMode.SINGLE

    assert reloaded_store.delete_custom("品牌右上角") is True
    assert PresetStore(storage_path=storage).list_custom() == {}


def test_preset_store_json_export_import_single_bundle_and_collision(tmp_path: Path) -> None:
    store_a = PresetStore(storage_path=tmp_path / "store_a.json")
    cfg1 = WatermarkConfig(text="横版样片", opacity=70, layout_mode=LayoutMode.TILED)
    cfg2 = WatermarkConfig(text="竖版抖音", opacity=90, layout_mode=LayoutMode.SINGLE, anchor=AnchorPosition.BOTTOM_CENTER)
    store_a.save_custom("横版模板", cfg1)
    store_a.save_custom("竖版模板", cfg2)

    # Export single preset
    single_file = tmp_path / "single_export.json"
    store_a.export_single_to_file(single_file, "分享预设", cfg1)
    assert single_file.is_file()

    # Export all custom presets bundle
    bundle_file = tmp_path / "all_bundle.json"
    store_a.export_all_custom_to_file(bundle_file)
    assert bundle_file.is_file()

    # Import into another clean store
    store_b = PresetStore(storage_path=tmp_path / "store_b.json")
    imported_single = store_b.import_from_file(single_file)
    assert imported_single == ["分享预设"]
    assert store_b.get_custom("分享预设").text == "横版样片"

    # Importing same file again without overwrite auto-numbers to avoid clobbering
    imported_dup = store_b.import_from_file(single_file, overwrite=False)
    assert imported_dup == ["分享预设 (2)"]

    imported_bundle = store_b.import_from_file(bundle_file)
    assert set(imported_bundle) == {"横版模板", "竖版模板"}
    assert store_b.get_custom("竖版模板").anchor == AnchorPosition.BOTTOM_CENTER

    # Also supports importing a flat raw dict JSON
    flat_file = tmp_path / "raw_flat.json"
    flat_file.write_text('{"text": "扁平JSON", "opacity": 65}', encoding="utf-8")
    imported_flat = store_b.import_from_file(flat_file)
    assert imported_flat == ["raw_flat"]
    assert store_b.get_custom("raw_flat").text == "扁平JSON"

    # Invalid file raises ValueError
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"unrelated": 123}', encoding="utf-8")
    with pytest.raises(ValueError):
        store_b.import_from_file(bad_file)


# ---- Orientation-Isolated Image Export Test ----


def test_orientation_isolated_image_export_subfolders(tmp_path: Path) -> None:
    land_src = tmp_path / "wide.png"
    port_src = tmp_path / "tall.png"
    sq_src = tmp_path / "square.png"

    Image.new("RGB", (600, 400), (40, 80, 120)).save(land_src)
    Image.new("RGB", (400, 600), (80, 40, 120)).save(port_src)
    Image.new("RGB", (500, 500), (40, 120, 80)).save(sq_src)

    out_dir = tmp_path / "isolated_out"
    exp_cfg = ExportConfig(
        output_dir=str(out_dir),
        filename_suffix="_wm",
        output_format=OutputFormat.PNG,
        isolate_orientation=True,
    )
    wm = WatermarkConfig(text="横竖隔离测试", opacity=85)

    p_land = export_single_image(land_src, wm, exp_cfg)
    p_port = export_single_image(port_src, wm, exp_cfg)
    p_sq = export_single_image(sq_src, wm, exp_cfg)

    assert p_land.parent == out_dir / "横版"
    assert p_sq.parent == out_dir / "横版"
    assert p_port.parent == out_dir / "竖版"
    assert p_land.exists() and p_port.exists() and p_sq.exists()


# ---- Video Watermarking Engine Tests ----


def test_video_frame_extraction_and_isolated_export(tmp_path: Path) -> None:
    land_vid = _generate_test_mp4(tmp_path / "clip_land.mp4", 640, 360, duration_sec=1.0, with_audio=True)
    port_vid = _generate_test_mp4(tmp_path / "clip_port.mp4", 360, 640, duration_sec=0.8, with_audio=False)

    found = scan_media_files([tmp_path], recursive=False, include_videos=True)
    assert len(found) == 2

    # Frame extraction & metadata
    frame_l, wl, hl, dur_l = extract_video_frame(land_vid)
    assert (wl, hl) == (640, 360)
    assert dur_l >= 0.8

    frame_p, wp, hp, dur_p = extract_video_frame(port_vid)
    assert (wp, hp) == (360, 640)
    assert dur_p >= 0.6

    out_dir = tmp_path / "vid_out"
    exp_cfg = ExportConfig(
        output_dir=str(out_dir),
        filename_suffix="_marked",
        quality=85,
        isolate_orientation=True,
        video_keep_audio=True,
    )
    wm_land = WatermarkConfig(
        text="横版视频水印",
        font_size=70,
        text_color="#FFFFFF",
        opacity=95,
        rotation=0,
        layout_mode=LayoutMode.SINGLE,
        anchor=AnchorPosition.CENTER,
    )
    wm_port = WatermarkConfig(
        text="竖版视频水印",
        font_size=65,
        text_color="#F59E0B",
        opacity=95,
        rotation=-25,
        layout_mode=LayoutMode.TILED,
    )

    progress_events: list[float] = []
    out_land = export_single_video(
        land_vid,
        wm_land,
        exp_cfg,
        progress_callback=progress_events.append,
    )
    out_port = export_single_video(port_vid, wm_port, exp_cfg)

    assert out_land.parent == out_dir / "横版"
    assert out_port.parent == out_dir / "竖版"
    assert out_land.suffix == ".mp4" and out_land.exists()
    assert out_port.suffix == ".mp4" and out_port.exists()
    assert progress_events and progress_events[-1] == 1.0

    # Verify watermark is visibly burned onto exported video frames
    out_frame_l, owl, ohl, _ = extract_video_frame(out_land, timestamp_sec=0.3)
    assert (owl, ohl) == (640, 360)
    assert _mean_rgb_diff(frame_l, out_frame_l) > 1.0

    out_frame_p, owp, ohp, _ = extract_video_frame(out_port, timestamp_sec=0.2)
    assert (owp, ohp) == (360, 640)
    assert _mean_rgb_diff(frame_p, out_frame_p) > 2.0

    # Verify audio stream was preserved in landscape video
    ffmpeg = find_ffmpeg_executable()
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(out_land)], capture_output=True, text=True)
    assert "Audio:" in probe.stderr
