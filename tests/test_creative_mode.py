"""Unit and offscreen GUI integration tests for BatchWatermark v2.0 Creative Mode."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageChops, ImageDraw
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from batch_watermark.creative_engine import (
    apply_creative_watermarks,
    compute_saliency_grid,
    export_creative_image,
    generate_aesthetic_layout,
)
from batch_watermark.creative_library import (
    CreativeLibraryStore,
    get_builtin_creative_assets,
    image_file_to_asset,
)
from batch_watermark.creative_models import AutoLayoutConfig, CreativeAsset, CreativePlacement
from batch_watermark.models import ExportConfig, OutputFormat
from batch_watermark.presets import PresetStore
from batch_watermark.ui.main_window import MainWindow
from batch_watermark.ui.theme import STUDIO_DARK_QSS


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STUDIO_DARK_QSS)
    return app


def _make_portrait_photo(path: Path, size: tuple[int, int] = (900, 1100)) -> Path:
    w, h = size
    img = Image.new("RGB", (w, h), (22, 26, 38))
    draw = ImageDraw.Draw(img)
    # Bright detailed portrait face/subject near upper-center
    draw.ellipse((w * 0.30, h * 0.22, w * 0.70, h * 0.60), fill=(225, 205, 198), outline=(40, 30, 35), width=6)
    draw.ellipse((w * 0.40, h * 0.36, w * 0.46, h * 0.42), fill=(30, 35, 50))
    draw.ellipse((w * 0.54, h * 0.36, w * 0.60, h * 0.42), fill=(30, 35, 50))
    draw.rectangle((w * 0.24, h * 0.60, w * 0.76, h * 0.96), fill=(115, 128, 152))
    img.save(path, format="PNG")
    return path


def _make_sticker_png(path: Path) -> Path:
    im = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.ellipse((40, 40, 140, 140), fill=(255, 255, 255, 230), outline=(147, 197, 253, 255), width=6)
    im.save(path, format="PNG")
    return path


def test_creative_library_persistence_trim_and_pack_io(tmp_path: Path) -> None:
    storage = tmp_path / "creative_lib.json"
    store = CreativeLibraryStore(storage_path=storage)
    builtins = store.list_assets()
    assert len(builtins) >= 6
    assert any(a.kind == "image" for a in builtins)
    assert any(a.kind == "text" for a in builtins)

    # Import custom PNG sticker (verifies transparent border trimming)
    sticker_path = _make_sticker_png(tmp_path / "custom_badge.png")
    img_asset = image_file_to_asset(sticker_path)
    assert img_asset.kind == "image"
    assert img_asset.image_data_url.startswith("data:image/png;base64,")
    saved_img = store.add_asset(img_asset)

    # Add custom text asset
    txt_asset = CreativeAsset(kind="text", name="画师签名", text="@Artist · 约稿展示", role="hero")
    saved_txt = store.add_asset(txt_asset)
    assert storage.is_file()

    # Export JSON pack and re-import into a brand-new store
    pack_file = tmp_path / "shared_pack.json"
    exported_n = store.export_pack(pack_file)
    assert exported_n == len(builtins) + 2

    store2 = CreativeLibraryStore(storage_path=tmp_path / "creative_lib2.json")
    store2.clear_all()
    imported = store2.import_pack(pack_file, replace=True)
    assert len(imported) == exported_n
    ids = {a.id for a in store2.list_assets()}
    assert saved_img.id in ids and saved_txt.id in ids


def test_aesthetic_layout_varied_sizes_reproducible_and_preserves_locked(tmp_path: Path) -> None:
    photo_path = _make_portrait_photo(tmp_path / "anime_portrait.png")
    img = Image.open(photo_path).convert("RGBA")
    assets = get_builtin_creative_assets()
    cfg = AutoLayoutConfig(
        style="artistic_scatter",
        density=65,
        scale_variation=80,
        subject_avoidance=85,
        global_opacity=80,
        seed=424242,
    )

    grid = compute_saliency_grid(img)
    assert len(grid) == 48 and len(grid[0]) == 48
    # Portrait upper-center saliency should be higher than quiet outer corner
    assert grid[18][24] > grid[2][2]

    locked = CreativePlacement(
        id="locked_hero",
        asset_id=assets[0].id,
        x=0.12,
        y=0.12,
        scale=0.16,
        rotation=10.0,
        opacity=90,
        locked=True,
        auto_generated=False,
    )

    layout1 = generate_aesthetic_layout(img.size, assets, cfg, base_image=img, existing_locked=[locked])
    layout2 = generate_aesthetic_layout(img.size, assets, cfg, base_image=img, existing_locked=[locked])

    assert len(layout1) >= 12
    assert any(p.id == "locked_hero" and p.locked for p in layout1)
    # Deterministic with same seed
    assert [(p.asset_id, p.x, p.y, p.scale) for p in layout1] == [
        (p.asset_id, p.x, p.y, p.scale) for p in layout2
    ]
    # Rich multi-scale variety ("大小不一")
    scales = [p.scale for p in layout1]
    assert max(scales) / max(0.001, min(scales)) >= 2.0

    # Render & export full resolution
    assets_map = {a.id: a for a in assets}
    composited = apply_creative_watermarks(img, layout1, assets_map)
    assert composited.size == img.size
    diff = ImageChops.difference(img.convert("RGB"), composited.convert("RGB"))
    assert diff.getbbox() is not None

    out_dir = tmp_path / "creative_out"
    out_path = export_creative_image(
        photo_path,
        layout1,
        assets_map,
        ExportConfig(output_dir=str(out_dir), filename_suffix="_art", output_format=OutputFormat.PNG),
    )
    assert out_path.is_file()
    with Image.open(out_path) as exported:
        assert exported.size == img.size


def test_mainwindow_dual_mode_independence_and_creative_workflow(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    p1 = _make_portrait_photo(tmp_path / "pic1.png", (800, 1000))
    p2 = _make_portrait_photo(tmp_path / "pic2.png", (1000, 700))

    win = MainWindow(
        preset_store=PresetStore(storage_path=tmp_path / "work_presets.json"),
        creative_library_store=CreativeLibraryStore(storage_path=tmp_path / "creative_lib.json"),
    )
    win.show()
    try:
        # Starts in Work Mode
        assert win.current_mode == "work"
        assert win.add_paths([p1]) == 1
        assert len(win._item_order) == 1

        # Switch to Creative Mode -> completely independent empty queue
        win.switch_mode("creative")
        QCoreApplication.processEvents()
        assert win.current_mode == "creative"
        assert len(win.creative_workspace._doc_order) == 0

        # Import 2 images in Creative Mode -> Work Mode stays at 1 item!
        assert win.creative_workspace.add_image_paths([p1, p2]) == 2
        assert len(win._item_order) == 1
        assert len(win.creative_workspace._doc_order) == 2

        # Run auto aesthetic layout on current image
        n_layers = win.creative_workspace.run_auto_layout_current(new_seed=False)
        assert n_layers >= 10

        # Manually drop an asset onto canvas & verify selection + undo/redo
        first_asset_id = win.creative_workspace.library_store.list_assets()[0].id
        dropped = win.creative_workspace.drop_asset_onto_current(first_asset_id, 0.22, 0.78)
        assert dropped is not None
        assert win.creative_workspace.canvas.selected_id == dropped.id
        assert len(win.creative_workspace._active_doc().placements) == n_layers + 1

        # Sync hand-tuned layout to all images
        win.creative_workspace.sync_current_layout_to_all()
        second_doc = win.creative_workspace._docs[win.creative_workspace._doc_order[1]]
        assert len(second_doc.placements) == n_layers + 1

        # Undo restores previous layer count on current doc
        win.creative_workspace.undo()
        assert len(win.creative_workspace._active_doc().placements) == n_layers
        win.creative_workspace.redo()
        assert len(win.creative_workspace._active_doc().placements) == n_layers + 1

        # Switching back to Work Mode preserves Work Mode state untouched
        win.switch_mode("work")
        QCoreApplication.processEvents()
        assert win.current_mode == "work"
        assert len(win._item_order) == 1
    finally:
        win.close()
