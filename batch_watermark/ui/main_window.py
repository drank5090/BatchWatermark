"""Main application window connecting media gallery, orientation isolation, presets, and batch export."""

from __future__ import annotations

import os
from pathlib import Path
import uuid

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..creative_library import CreativeLibraryStore
from ..engine import scan_media_files
from ..i18n import SUPPORTED_LOCALES, get_locale, retranslate_widget_tree, set_locale, t
from ..models import (
    ExportConfig,
    ImageItem,
    OrientationGroup,
    SUPPORTED_INPUT_EXTENSIONS,
    SUPPORTED_MEDIA_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    WatermarkConfig,
)
from ..presets import PresetStore
from ..workers import BatchExportThread, MediaLoadWorker, PreviewRenderWorker
from .control_panel import ControlPanel
from .creative_workspace import CreativeWorkspaceWidget
from .preview_gallery import LightboxPreviewDialog, PreviewGalleryWidget


class ExportProgressDialog(QDialog):
    """Modal progress dialog for full-resolution batch image & video export."""

    def __init__(
        self,
        items: list[ImageItem],
        wm_config: WatermarkConfig,
        export_config: ExportConfig,
        portrait_config: WatermarkConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("正在批量导出水印媒体")
        self.setModal(True)
        self.setFixedWidth(500)

        self._output_dir = export_config.output_dir
        self._result: tuple[int, int, list[tuple[str, str]], bool] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        vid_count = sum(1 for it in items if it.is_video)
        img_count = len(items) - vid_count
        summary_parts = []
        if img_count:
            summary_parts.append(f"{img_count} 张图片")
        if vid_count:
            summary_parts.append(f"{vid_count} 个视频")
        iso_note = "（按横版 / 竖版子文件夹隔离导出）" if export_config.isolate_orientation else ""

        self._title_label = QLabel(
            f"准备导出共 {' + '.join(summary_parts)}{iso_note} 到：\n{export_config.output_dir}"
        )
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._file_label = QLabel("正在初始化...")
        self._file_label.setObjectName("MutedLabel")
        layout.addWidget(self._file_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, max(1, len(items) * 100))
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_cancel = QPushButton("取消导出")
        self._btn_cancel.setObjectName("DangerButton")
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._btn_cancel)
        layout.addLayout(btn_row)

        self._thread = BatchExportThread(
            items,
            wm_config,
            export_config,
            portrait_config=portrait_config,
            parent=self,
        )
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_summary.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, done_units: int, total_units: int, status_text: str) -> None:
        self._progress.setRange(0, max(1, total_units))
        self._progress.setValue(done_units)
        self._file_label.setText(status_text)

    def _on_cancel(self) -> None:
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setText("正在停止...")
        self._thread.request_cancel()

    def _on_finished(self, success: int, fail: int, errors: list, cancelled: bool) -> None:
        self._result = (success, fail, errors, cancelled)
        self.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread.isRunning():
            self._thread.request_cancel()
            self._thread.wait(5000)
        super().closeEvent(event)

    @property
    def export_result(self) -> tuple[int, int, list[tuple[str, str]], bool] | None:
        return self._result


class MainWindow(QMainWindow):
    """Main application window for BatchWatermark (Images & Videos)."""

    def __init__(
        self,
        initial_paths: list[Path] | None = None,
        preset_store: PresetStore | None = None,
        creative_library_store: CreativeLibraryStore | None = None,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("BatchWatermark v2.0 · 工作模式 & 创作模式批量水印工具")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)

        self._preset_store = preset_store
        self._creative_library_store = creative_library_store
        self._settings_path = settings_path

        # Data state
        self._items: dict[str, ImageItem] = {}
        self._item_order: list[str] = []
        self._path_index: set[str] = set()
        self._current_config = WatermarkConfig()

        # Render orchestration
        self._render_epoch: int = 0
        self._pending_renders: int = 0
        self._pending_loads: int = 0
        self._last_import_dir: str = ""

        cpu_count = os.cpu_count() or 4
        self._load_pool = QThreadPool(self)
        self._load_pool.setMaxThreadCount(max(2, min(6, cpu_count)))

        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(max(2, min(8, cpu_count)))

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(40)
        self._debounce_timer.timeout.connect(self._render_all_previews)

        self._build_ui()
        self._connect_signals()
        if get_locale() != "zh-CN":
            retranslate_widget_tree(self, get_locale())

        if initial_paths:
            QTimer.singleShot(50, lambda: self.add_paths(initial_paths))

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Top Mode Switcher Tab Bar (Work Mode vs Creative Mode — fully independent) ----
        mode_bar = QFrame()
        mode_bar.setObjectName("ModeTabBar")
        mode_bar.setFixedHeight(44)
        mb = QHBoxLayout(mode_bar)
        mb.setContentsMargins(14, 5, 14, 5)
        mb.setSpacing(8)

        brand_lbl = QLabel("💧 BatchWatermark")
        brand_lbl.setObjectName("AppTitle")
        mb.addWidget(brand_lbl)

        mb.addSpacing(12)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self._btn_mode_work = QPushButton("🛠️ 工作模式")
        self._btn_mode_work.setObjectName("ModeTabBtn")
        self._btn_mode_work.setCheckable(True)
        self._btn_mode_work.setChecked(True)
        self._btn_mode_work.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mode_work.setToolTip("批量图片与视频水印、横竖隔离与预设管理（原经典模式）")

        self._btn_mode_creative = QPushButton("✨ 创作模式")
        self._btn_mode_creative.setObjectName("ModeTabBtn")
        self._btn_mode_creative.setCheckable(True)
        self._btn_mode_creative.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mode_creative.setToolTip("上传图文水印库，智能生成美观大小不一艺术水印，或自由拖拽精修")

        self._mode_group.addButton(self._btn_mode_work, 0)
        self._mode_group.addButton(self._btn_mode_creative, 1)
        mb.addWidget(self._btn_mode_work)
        mb.addWidget(self._btn_mode_creative)

        mb.addStretch(1)

        mode_hint = QLabel("双模式完全独立 · 切换标签页互不干扰")
        mode_hint.setObjectName("MutedLabel")
        mb.addWidget(mode_hint)

        mb.addSpacing(8)

        self._lang_combo = QComboBox()
        self._lang_combo.setProperty("_i18n_skip", True)
        self._lang_combo.setFixedWidth(124)
        self._lang_combo.setToolTip("Language / 语言 / 言語")
        for loc_code, loc_label, _slug in SUPPORTED_LOCALES:
            self._lang_combo.addItem(f"🌐 {loc_label}", loc_code)
        cur_idx = self._lang_combo.findData(get_locale())
        if cur_idx >= 0:
            self._lang_combo.setCurrentIndex(cur_idx)
        mb.addWidget(self._lang_combo)

        root.addWidget(mode_bar)

        # ---- Stacked Dual Workspaces ----
        self._mode_stack = QStackedWidget()
        root.addWidget(self._mode_stack, 1)

        # Page 0: Work Mode (original complete workflow)
        work_page = QWidget()
        work_root = QVBoxLayout(work_page)
        work_root.setContentsMargins(0, 0, 0, 0)
        work_root.setSpacing(0)

        # ---- Work Mode Top Toolbar ----
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(52)
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(14, 7, 14, 7)
        tb.setSpacing(8)

        self._btn_add_files = QPushButton("＋ 添加图片/视频")
        self._btn_add_files.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(self._btn_add_files)

        self._btn_add_folder = QPushButton("📂 添加文件夹")
        self._btn_add_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(self._btn_add_folder)

        self._chk_recursive = QCheckBox("含子目录")
        self._chk_recursive.setToolTip("导入文件夹时递归扫描所有子文件夹")
        self._chk_recursive.setChecked(True)
        tb.addWidget(self._chk_recursive)

        self._btn_isolate_orientation = QPushButton("横竖隔离")
        self._btn_isolate_orientation.setObjectName("IsolateToggleBtn")
        self._btn_isolate_orientation.setCheckable(True)
        self._btn_isolate_orientation.setToolTip(
            "开启后横版与竖版媒体分开展示、支持独立水印参数，并自动分文件夹导出"
        )
        self._btn_isolate_orientation.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(self._btn_isolate_orientation)

        self._btn_clear = QPushButton("✕ 清空")
        self._btn_clear.setObjectName("DangerButton")
        self._btn_clear.setEnabled(False)
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(self._btn_clear)

        self._count_badge = QLabel("共 0 项")
        self._count_badge.setObjectName("CountBadge")
        tb.addWidget(self._count_badge)

        tb.addStretch(1)

        size_lbl = QLabel("预览尺寸")
        size_lbl.setObjectName("MutedLabel")
        tb.addWidget(size_lbl)

        self._card_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._card_size_slider.setRange(170, 380)
        self._card_size_slider.setValue(250)
        self._card_size_slider.setFixedWidth(110)
        self._card_size_slider.setToolTip("调整多图/视频预览卡片大小")
        tb.addWidget(self._card_size_slider)

        tb.addSpacing(4)

        self._btn_top_export = QPushButton("⬇ 批量导出")
        self._btn_top_export.setObjectName("PrimaryButton")
        self._btn_top_export.setEnabled(False)
        self._btn_top_export.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(self._btn_top_export)

        work_root.addWidget(top_bar)

        # ---- Work Mode Main Split Workspace ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.gallery = PreviewGalleryWidget()
        self.control_panel = ControlPanel(preset_store=self._preset_store)

        splitter.addWidget(self.gallery)
        splitter.addWidget(self.control_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([950, 440])

        work_root.addWidget(splitter, 1)
        self._mode_stack.addWidget(work_page)

        # Page 1: Creative Mode (completely independent workspace)
        self.creative_workspace = CreativeWorkspaceWidget(
            library_store=self._creative_library_store,
            parent=self,
        )
        self._mode_stack.addWidget(self.creative_workspace)

        # ---- Status Bar ----
        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("工作模式 · 请添加图片/视频或切换至「✨ 创作模式」体验艺术水印与自由拖拽")
        status.addWidget(self._status_label, 1)

    def switch_mode(self, mode: str) -> None:
        """Switch between 'work' and 'creative' modes via the top tab switcher."""
        if mode == "creative":
            self._btn_mode_creative.setChecked(True)
            self._mode_stack.setCurrentIndex(1)
            self._set_status("创作模式 · 导入图片后可一键生成美观大小不一的水印，或从左侧水印库自由拖拽")
        else:
            self._btn_mode_work.setChecked(True)
            self._mode_stack.setCurrentIndex(0)
            self._set_status("工作模式 · 批量图片与视频水印实时预览，支持横竖隔离与 JSON 预设")

    def _set_status(self, text: str) -> None:
        self._status_label.setProperty("_i18n_text", text)
        self._status_label.setText(t(text))

    def set_language(self, locale_code: str, *, persist: bool = True) -> str:
        """Switch the entire desktop application UI language live without losing state."""
        active = set_locale(locale_code, persist=persist, settings_path=self._settings_path)
        idx = self._lang_combo.findData(active)
        if idx >= 0 and self._lang_combo.currentIndex() != idx:
            self._lang_combo.blockSignals(True)
            self._lang_combo.setCurrentIndex(idx)
            self._lang_combo.blockSignals(False)
        retranslate_widget_tree(self, active)
        self.creative_workspace.canvas.update()
        return active

    @property
    def current_mode(self) -> str:
        return "creative" if self._mode_stack.currentIndex() == 1 else "work"

    def _connect_signals(self) -> None:
        self._btn_mode_work.clicked.connect(lambda: self.switch_mode("work"))
        self._btn_mode_creative.clicked.connect(lambda: self.switch_mode("creative"))
        self._lang_combo.currentIndexChanged.connect(
            lambda _i: self.set_language(str(self._lang_combo.currentData() or "zh-CN"), persist=True)
        )
        self.creative_workspace.status_message.connect(self._set_status)

        self._btn_add_files.clicked.connect(self._open_add_files_dialog)
        self._btn_add_folder.clicked.connect(self._open_add_folder_dialog)
        self._btn_isolate_orientation.toggled.connect(self.set_orientation_isolated)
        self._btn_clear.clicked.connect(self.clear_all_images)
        self._btn_top_export.clicked.connect(self.start_batch_export)
        self._card_size_slider.valueChanged.connect(self.gallery.set_card_width)

        self.gallery.add_files_clicked.connect(self._open_add_files_dialog)
        self.gallery.add_folder_clicked.connect(self._open_add_folder_dialog)
        self.gallery.files_dropped.connect(self.add_paths)
        self.gallery.remove_item_requested.connect(self.remove_image)
        self.gallery.inspect_item_requested.connect(self._open_lightbox)

        self.control_panel.config_changed.connect(self._on_config_changed)
        self.control_panel.export_requested.connect(self.start_batch_export)

        self._current_config = self.control_panel.get_watermark_config()

    # ---- Orientation Isolation ----

    def set_orientation_isolated(self, enabled: bool) -> None:
        if self._btn_isolate_orientation.isChecked() != enabled:
            self._btn_isolate_orientation.blockSignals(True)
            self._btn_isolate_orientation.setChecked(enabled)
            self._btn_isolate_orientation.blockSignals(False)
        self.gallery.set_orientation_isolated(enabled)
        self.control_panel.set_orientation_isolated(enabled)
        self._refresh_counts()
        if enabled:
            self._status_label.setText("已开启横竖隔离：横版与竖版分开展示，导出时将自动分文件夹保存")
        else:
            self._status_label.setText("已关闭横竖隔离：全部媒体统一展示与导出")

    # ---- Media Import & Management ----

    def _open_add_files_dialog(self) -> None:
        all_ext = " ".join(f"*{ext}" for ext in SUPPORTED_MEDIA_EXTENSIONS)
        img_ext = " ".join(f"*{ext}" for ext in SUPPORTED_INPUT_EXTENSIONS)
        vid_ext = " ".join(f"*{ext}" for ext in SUPPORTED_VIDEO_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要打水印的图片或视频（可多选）",
            self._last_import_dir,
            f"图片与视频 ({all_ext});;图片文件 ({img_ext});;视频文件 ({vid_ext});;所有文件 (*.*)",
        )
        if files:
            paths = [Path(f) for f in files]
            self._last_import_dir = str(paths[0].parent)
            self.add_paths(paths)

    def _open_add_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择包含图片或视频的文件夹",
            self._last_import_dir,
        )
        if folder:
            self._last_import_dir = folder
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]) -> int:
        """Scan image & video files from paths, add unseen items to gallery, and load asynchronously."""
        discovered = scan_media_files(paths, recursive=self._chk_recursive.isChecked(), include_videos=True)
        added_items: list[ImageItem] = []

        for fp in discovered:
            try:
                norm_key = str(fp.resolve()).lower()
            except OSError:
                norm_key = str(fp).lower()
            if norm_key in self._path_index:
                continue
            self._path_index.add(norm_key)

            item = ImageItem(id=uuid.uuid4().hex, path=fp)
            self._items[item.id] = item
            self._item_order.append(item.id)
            self.gallery.add_item(item)
            added_items.append(item)

        if not added_items:
            if discovered:
                self._status_label.setText("所选媒体已在列表中（已自动去重）")
            else:
                self._status_label.setText("未找到受支持的图片或视频文件")
            return 0

        self._refresh_counts()
        self._pending_loads += len(added_items)
        self._status_label.setText(f"正在加载 {len(added_items)} 项媒体并生成实时水印预览...")

        for item in added_items:
            worker = MediaLoadWorker(item.id, item.path)
            worker.signals.loaded.connect(self._on_media_loaded)
            worker.signals.failed.connect(self._on_media_load_failed)
            self._load_pool.start(worker)

        return len(added_items)

    def _on_media_loaded(
        self,
        item_id: str,
        pil_base: object,
        orig_w: int,
        orig_h: int,
        orig_fmt: str,
        file_size: int,
        duration_sec: float,
    ) -> None:
        self._pending_loads = max(0, self._pending_loads - 1)
        item = self._items.get(item_id)
        if item is None:
            return

        item.preview_base = pil_base
        item.orig_width = orig_w
        item.orig_height = orig_h
        item.orig_format = orig_fmt
        item.file_size_bytes = file_size
        item.duration_sec = duration_sec
        self.gallery.update_item_metadata(item)
        self._refresh_counts()

        cfg = self.control_panel.get_config_for_orientation(item.orientation)
        self._schedule_single_render(item, self._render_epoch, priority=5, config_snapshot=cfg)

    def _on_media_load_failed(self, item_id: str, error_msg: str) -> None:
        self._pending_loads = max(0, self._pending_loads - 1)
        item = self._items.get(item_id)
        if item is None:
            return
        item.load_error = error_msg
        self.gallery.update_item_metadata(item)
        if self._pending_loads == 0:
            self._status_label.setText(f"部分媒体加载失败 · 当前列表共 {len(self._item_order)} 项")

    def remove_image(self, item_id: str) -> None:
        item = self._items.pop(item_id, None)
        if item is None:
            return
        self._item_order = [i for i in self._item_order if i != item_id]
        try:
            self._path_index.discard(str(item.path.resolve()).lower())
        except OSError:
            self._path_index.discard(str(item.path).lower())
        self.gallery.remove_item(item_id)
        self._refresh_counts()
        self._status_label.setText(f"已移除 {item.filename} · 剩余 {len(self._item_order)} 项")

    def clear_all_images(self) -> None:
        self._render_epoch += 1
        self._render_pool.clear()
        self._load_pool.clear()
        self._items.clear()
        self._item_order.clear()
        self._path_index.clear()
        self._pending_loads = 0
        self._pending_renders = 0
        self.gallery.clear_all()
        self._refresh_counts()
        self._status_label.setText("已清空媒体列表")

    def _refresh_counts(self) -> None:
        count = len(self._item_order)
        if count > 0 and self._btn_isolate_orientation.isChecked():
            land = sum(
                1 for i in self._item_order
                if i in self._items and self._items[i].orientation == OrientationGroup.LANDSCAPE
            )
            port = count - land
            raw_badge = f"共 {count} 项 · 横{land} / 竖{port}"
        else:
            vids = sum(1 for i in self._item_order if i in self._items and self._items[i].is_video)
            if vids > 0:
                raw_badge = f"共 {count} 项 (视频 {vids})"
            else:
                raw_badge = f"共 {count} 项"
        self._count_badge.setProperty("_i18n_text", raw_badge)
        self._count_badge.setText(t(raw_badge))
        self._btn_clear.setEnabled(count > 0)
        self._btn_top_export.setEnabled(count > 0)
        self.control_panel.set_image_count(count)
        if get_locale() != "zh-CN":
            retranslate_widget_tree(self.control_panel._btn_export, get_locale())

    # ---- Real-Time Multi-Media Preview Pipeline ----

    def _on_config_changed(self, config: WatermarkConfig) -> None:
        self._current_config = config
        if not self._item_order:
            return
        self._debounce_timer.start()

    def _is_epoch_current(self, epoch: int) -> bool:
        return epoch == self._render_epoch

    def _render_all_previews(self) -> None:
        """Re-render all loaded images and video frames simultaneously, prioritizing viewport items."""
        self._render_epoch += 1
        epoch = self._render_epoch
        self._render_pool.clear()

        ready_items = [
            self._items[i]
            for i in self._item_order
            if i in self._items and self._items[i].preview_base is not None
        ]
        if not ready_items:
            return

        visible_set = set(self.gallery.get_visible_item_ids())
        visible_items = [it for it in ready_items if it.id in visible_set]
        offscreen_items = [it for it in ready_items if it.id not in visible_set]

        self._pending_renders = len(ready_items)
        self._status_label.setText(f"正在同步刷新 {len(ready_items)} 项实时预览...")

        land_cfg = self.control_panel.get_config_for_orientation(OrientationGroup.LANDSCAPE)
        port_cfg = self.control_panel.get_config_for_orientation(OrientationGroup.PORTRAIT)

        def _cfg_for(it: ImageItem) -> WatermarkConfig:
            return port_cfg if it.orientation == OrientationGroup.PORTRAIT else land_cfg

        for item in visible_items:
            self._schedule_single_render(item, epoch, priority=10, config_snapshot=_cfg_for(item))
        for item in offscreen_items:
            self._schedule_single_render(item, epoch, priority=0, config_snapshot=_cfg_for(item))

    def _schedule_single_render(
        self,
        item: ImageItem,
        epoch: int,
        priority: int = 0,
        config_snapshot: WatermarkConfig | None = None,
    ) -> None:
        if item.preview_base is None:
            return
        cfg = (
            config_snapshot
            if config_snapshot is not None
            else self.control_panel.get_config_for_orientation(item.orientation)
        )
        worker = PreviewRenderWorker(
            item_id=item.id,
            preview_base=item.preview_base,
            orig_size=(item.orig_width, item.orig_height),
            config=cfg,
            epoch=epoch,
            is_epoch_current=self._is_epoch_current,
        )
        worker.signals.rendered.connect(self._on_preview_rendered)
        self._render_pool.start(worker, priority)

    def _on_preview_rendered(self, item_id: str, epoch: int, qimg: QImage) -> None:
        if epoch != self._render_epoch:
            return
        if item_id not in self._items:
            return
        self.gallery.update_item_preview(item_id, qimg)
        if self._pending_renders > 0:
            self._pending_renders -= 1
        if self._pending_renders == 0 and self._pending_loads == 0:
            self._status_label.setText(f"实时预览已同步更新 · 共 {len(self._item_order)} 项媒体")

    def _open_lightbox(self, item_id: str) -> None:
        if item_id not in self._items:
            return
        ordered = [self._items[i] for i in self._item_order if i in self._items]
        idx = next((k for k, it in enumerate(ordered) if it.id == item_id), 0)
        dlg = LightboxPreviewDialog(
            items=ordered,
            start_index=idx,
            get_config_for_item=lambda it: self.control_panel.get_config_for_orientation(it.orientation),
            parent=self,
        )
        dlg.exec()

    # ---- Batch Export ----

    def start_batch_export(self) -> None:
        if not self._item_order:
            QMessageBox.information(self, "提示", "请先添加至少一张图片或一个视频后再导出。")
            return

        export_cfg = self.control_panel.get_export_config()
        land_cfg = self.control_panel.get_config_for_orientation(OrientationGroup.LANDSCAPE)
        port_cfg = (
            self.control_panel.get_config_for_orientation(OrientationGroup.PORTRAIT)
            if self.control_panel.is_independent_orientation_enabled()
            else None
        )

        if not export_cfg.output_dir:
            chosen = QFileDialog.getExistingDirectory(
                self,
                "选择批量导出目标文件夹",
                self._last_import_dir,
            )
            if not chosen:
                return
            export_cfg.output_dir = chosen
            self.control_panel.set_output_dir(chosen)

        export_items = [self._items[i] for i in self._item_order if i in self._items]
        dlg = ExportProgressDialog(export_items, land_cfg, export_cfg, portrait_config=port_cfg, parent=self)
        dlg.exec()

        result = dlg.export_result
        if result is None:
            return

        success, fail, errors, cancelled = result
        out_dir = export_cfg.output_dir

        if cancelled:
            self._status_label.setText(f"批量导出已取消 · 已完成 {success} 项")
        elif fail == 0:
            self._status_label.setText(f"批量导出成功 · 共导出 {success} 项到 {out_dir}")
        else:
            self._status_label.setText(f"批量导出完成 · 成功 {success} 项，失败 {fail} 项")

        msg = QMessageBox(self)
        msg.setWindowTitle("导出完成" if not cancelled else "导出已中止")
        msg.setIcon(QMessageBox.Icon.Information if fail == 0 else QMessageBox.Icon.Warning)

        summary = f"成功导出：{success} 项"
        if fail > 0:
            summary += f"\n失败：{fail} 项"
            detail_lines = "\n".join(f"• {name}: {err}" for name, err in errors[:8])
            if len(errors) > 8:
                detail_lines += f"\n... 其余 {len(errors) - 8} 条错误省略"
            msg.setDetailedText(detail_lines)
        if cancelled:
            summary += "\n（任务已被用户取消）"
        if export_cfg.isolate_orientation:
            summary += f"\n\n已按横竖隔离分别保存至「{export_cfg.landscape_subfolder}」和「{export_cfg.portrait_subfolder}」子文件夹。"
        summary += f"\n保存路径：{out_dir}"
        msg.setText(summary)

        btn_open = msg.addButton("📂 打开输出文件夹", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()

        if msg.clickedButton() is btn_open and Path(out_dir).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out_dir).resolve())))

    def closeEvent(self, event: QCloseEvent) -> None:
        self._debounce_timer.stop()
        self._render_epoch += 1
        self._load_pool.clear()
        self._render_pool.clear()
        self._load_pool.waitForDone(2000)
        self._render_pool.waitForDone(2000)
        super().closeEvent(event)
