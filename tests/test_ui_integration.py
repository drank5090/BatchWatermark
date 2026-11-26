"""Offscreen PySide6 GUI integration tests verifying multi-preview, orientation isolation, presets, and video."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from batch_watermark.models import ExportConfig, LayoutMode, OrientationGroup, OutputFormat
from batch_watermark.presets import PresetStore
from batch_watermark.ui.main_window import MainWindow
from batch_watermark.ui.theme import STUDIO_DARK_QSS
from batch_watermark.video_engine import find_ffmpeg_executable
from batch_watermark.workers import BatchExportThread


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STUDIO_DARK_QSS)
    return app


def _pump_events_until(predicate, timeout_sec: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    QCoreApplication.processEvents()
    return bool(predicate())


def _create_sample_photos(folder: Path) -> list[Path]:
    specs = [
        ("landscape_city.jpg", (900, 600), (35, 58, 92), (240, 180, 90)),
        ("portrait_studio.png", (600, 800), (62, 42, 74), (110, 200, 190)),
        ("product_shot.webp", (800, 800), (45, 78, 64), (235, 110, 100)),
        ("banner_wide.jpg", (1200, 500), (88, 52, 42), (220, 210, 160)),
    ]
    paths: list[Path] = []
    for name, (w, h), bg, accent in specs:
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([w // 8, h // 6, w * 7 // 8, h * 5 // 6], outline=accent, width=8)
        draw.ellipse([w // 3, h // 4, w * 2 // 3, h * 3 // 4], fill=accent)
        fp = folder / name
        img.save(fp)
        paths.append(fp)
    return paths


def _create_sample_video(dest: Path, width: int, height: int) -> Path:
    ffmpeg = find_ffmpeg_executable()
    assert ffmpeg is not None
    res = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x264653:s={width}x{height}:r=12:d=0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    return dest


def _card_pixmap_bytes(card) -> bytes:
    pix = card._canvas._pixmap
    if pix is None or pix.isNull():
        return b""
    qimg = pix.toImage()
    ptr = qimg.constBits()
    return bytes(ptr[: qimg.sizeInBytes()])


def test_mainwindow_live_multi_preview_and_batch_export(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    _create_sample_photos(input_dir)

    store = PresetStore(storage_path=tmp_path / "presets.json")
    win = MainWindow(preset_store=store)
    win.show()

    try:
        added = win.add_paths([input_dir])
        assert added == 4
        assert len(win._item_order) == 4

        ready = _pump_events_until(
            lambda: all(
                win.gallery._cards[iid]._canvas._pixmap is not None
                and not win.gallery._cards[iid]._canvas._pixmap.isNull()
                for iid in win._item_order
            )
            and win._pending_loads == 0
            and win._pending_renders == 0
        )
        assert ready, "All 4 preview cards should render initial previews"

        before_snapshots = {iid: _card_pixmap_bytes(win.gallery._cards[iid]) for iid in win._item_order}
        assert all(len(b) > 0 for b in before_snapshots.values())

        win.control_panel._text_edit.setPlainText("实时同步测试 · UPDATED")
        win.control_panel._text_color_row.set_color("#EF4444", emit=True)
        win.control_panel._opacity_row.set_value(95, emit=True)
        win.control_panel._btn_mode_single.click()
        assert win.control_panel.get_watermark_config().layout_mode == LayoutMode.SINGLE

        updated = _pump_events_until(
            lambda: win._pending_renders == 0
            and not win._debounce_timer.isActive()
            and all(
                _card_pixmap_bytes(win.gallery._cards[iid]) != before_snapshots[iid]
                for iid in win._item_order
            )
        )
        assert updated, "Every single preview card should update when parameters change"

        remove_id = win._item_order[-1]
        win.remove_image(remove_id)
        assert len(win._item_order) == 3

        out_dir = tmp_path / "exported"
        win.control_panel.set_output_dir(str(out_dir))
        wm_cfg = win.control_panel.get_watermark_config()
        exp_cfg = ExportConfig(
            output_dir=str(out_dir),
            filename_suffix="_marked",
            output_format=OutputFormat.PNG,
        )
        items = [win._items[i] for i in win._item_order]

        done_box: list[tuple[int, int, list, bool]] = []
        thread = BatchExportThread(items, wm_cfg, exp_cfg)
        thread.finished_summary.connect(lambda s, f, e, c: done_box.append((s, f, e, c)))
        thread.start()

        assert _pump_events_until(lambda: len(done_box) == 1, timeout_sec=10.0)
        thread.wait(2000)

        success, fail, errors, cancelled = done_box[0]
        assert (success, fail, errors, cancelled) == (3, 0, [], False)
        exported_files = sorted(out_dir.glob("*_marked.png"))
        assert len(exported_files) == 3
    finally:
        win.close()


def test_orientation_isolation_presets_and_video_in_gui(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    media_dir = tmp_path / "mixed_media"
    media_dir.mkdir()
    _create_sample_photos(media_dir)  # 3 landscape/square + 1 portrait
    _create_sample_video(media_dir / "vertical_clip.mp4", 360, 640)  # 1 portrait video

    preset_file = tmp_path / "local_presets.json"
    store1 = PresetStore(storage_path=preset_file)
    win = MainWindow(preset_store=store1)
    win.show()

    try:
        added = win.add_paths([media_dir])
        assert added == 5

        ready = _pump_events_until(
            lambda: win._pending_loads == 0
            and win._pending_renders == 0
            and all(
                win.gallery._cards[iid]._canvas._pixmap is not None
                and not win.gallery._cards[iid]._canvas._pixmap.isNull()
                for iid in win._item_order
            ),
            timeout_sec=12.0,
        )
        assert ready, "All 4 images + 1 MP4 video should load and render previews"

        # Enable Landscape / Portrait Isolation
        win.set_orientation_isolated(True)
        QCoreApplication.processEvents()

        assert win.gallery._grid.count() == 3  # landscape_city, product_shot(square), banner_wide
        assert win.gallery._portrait_grid.count() == 2  # portrait_studio.png + vertical_clip.mp4
        assert "横3 / 竖2" in win._count_badge.text()

        # Enable independent orientation params -> modify Portrait only
        win.control_panel._chk_independent_params.setChecked(True)
        win.control_panel._btn_edit_portrait.click()
        win.control_panel._text_edit.setPlainText("竖版专属水印")
        win.control_panel._text_color_row.set_color("#F59E0B", emit=True)

        assert win.control_panel.get_config_for_orientation(OrientationGroup.PORTRAIT).text == "竖版专属水印"
        assert win.control_panel.get_config_for_orientation(OrientationGroup.LANDSCAPE).text != "竖版专属水印"

        # Save custom preset locally via ControlPanel
        win.control_panel.save_current_as_custom_preset("竖版金字预设")
        assert preset_file.is_file()

        # Batch export with orientation isolation & independent portrait config (images + video!)
        out_dir = tmp_path / "isolated_export"
        win.control_panel.set_output_dir(str(out_dir))
        exp_cfg = win.control_panel.get_export_config()
        assert exp_cfg.isolate_orientation is True

        land_cfg = win.control_panel.get_config_for_orientation(OrientationGroup.LANDSCAPE)
        port_cfg = win.control_panel.get_config_for_orientation(OrientationGroup.PORTRAIT)
        items = [win._items[i] for i in win._item_order]

        done_box: list[tuple[int, int, list, bool]] = []
        thread = BatchExportThread(items, land_cfg, exp_cfg, portrait_config=port_cfg)
        thread.finished_summary.connect(lambda s, f, e, c: done_box.append((s, f, e, c)))
        thread.start()

        assert _pump_events_until(lambda: len(done_box) == 1, timeout_sec=20.0)
        thread.wait(3000)

        success, fail, errors, cancelled = done_box[0]
        assert (success, fail, errors, cancelled) == (5, 0, [], False)

        land_outputs = list((out_dir / "横版").iterdir())
        port_outputs = list((out_dir / "竖版").iterdir())
        assert len(land_outputs) == 3
        assert len(port_outputs) == 2
        assert any(p.suffix == ".mp4" for p in port_outputs)
    finally:
        win.close()

    # Launch a fresh MainWindow using the same local preset storage -> saved custom preset persists!
    win2 = MainWindow(preset_store=PresetStore(storage_path=preset_file))
    try:
        assert win2.control_panel.select_preset_by_name("竖版金字预设") is True
        assert win2.control_panel.get_watermark_config().text == "竖版专属水印"
    finally:
        win2.close()
