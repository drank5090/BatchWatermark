"""Independent Creative Mode workspace (水印库 + 智能美观排版 + 自由拖拽画布 + 批量导出)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import random
from typing import Iterable

from PIL import Image
from PySide6.QtCore import QByteArray, QMimeData, QPoint, Qt, QThread, Signal
from PySide6.QtGui import QDrag, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..creative_engine import (
    export_creative_image,
    generate_aesthetic_layout,
    render_asset_stamp,
)
from ..creative_library import CreativeLibraryStore, image_file_to_asset
from ..creative_models import (
    AutoLayoutConfig,
    CreativeAsset,
    CreativePlacement,
    new_id,
)
from ..engine import create_preview_base, scan_image_files
from ..fonts import discover_system_fonts
from ..models import (
    ConflictPolicy,
    ExportConfig,
    OutputFormat,
    SUPPORTED_INPUT_EXTENSIONS,
)
from .creative_canvas import CreativeCanvasWidget, MIME_CREATIVE_ASSET, pil_to_qpixmap
from .widgets import ColorPickerRow, DoubleSliderSpinRow, SectionCard, SliderSpinRow

ROLE_LABELS = {
    "auto": "智能",
    "hero": "主视觉",
    "accent": "装饰",
    "micro": "微底纹",
}

STYLE_OPTIONS = (
    ("artistic_scatter", "艺术错落 · 示例同款（推荐）"),
    ("frame_halo", "边框环绕 · 中心人物通透"),
    ("full_anti_theft", "全图防盗 · 多尺寸防抠图"),
    ("magazine_editorial", "杂志海报 · 主标题+点缀"),
)


@dataclass
class CreativeImageDoc:
    """One loaded image document inside Creative Mode with its own layer list & undo stack."""

    id: str
    path: Path
    filename: str
    orig_width: int
    orig_height: int
    preview_base: Image.Image
    placements: list[CreativePlacement] = field(default_factory=list)
    undo_stack: list[list[CreativePlacement]] = field(default_factory=list)
    redo_stack: list[list[CreativePlacement]] = field(default_factory=list)

    def push_undo(self) -> None:
        snap = [p.clone() for p in self.placements]
        self.undo_stack.append(snap)
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append([p.clone() for p in self.placements])
        self.placements = self.undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append([p.clone() for p in self.placements])
        self.placements = self.redo_stack.pop()
        return True


class CreativeBatchExportThread(QThread):
    """Background worker exporting full-resolution Creative Mode compositions."""

    progress = Signal(int, int, str)
    finished_summary = Signal(int, int, list, bool)

    def __init__(
        self,
        docs: list[CreativeImageDoc],
        assets_by_id: dict[str, CreativeAsset],
        export_config: ExportConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._docs = docs
        self._assets_by_id = {k: v.clone() for k, v in assets_by_id.items()}
        self._export_config = export_config
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._docs)
        success = 0
        fail = 0
        errors: list[tuple[str, str]] = []
        for idx, doc in enumerate(self._docs, start=1):
            if self._cancelled:
                break
            self.progress.emit(idx - 1, total, f"正在渲染导出：{doc.filename} ({idx}/{total})")
            try:
                export_creative_image(
                    doc.path,
                    [p.clone() for p in doc.placements],
                    self._assets_by_id,
                    self._export_config,
                )
                success += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                errors.append((doc.filename, str(exc)))
            self.progress.emit(idx, total, f"已完成：{doc.filename} ({idx}/{total})")
        self.finished_summary.emit(success, fail, errors, self._cancelled)


class AddTextAssetDialog(QDialog):
    """Dialog for adding a new text watermark item into the Creative Watermark Library."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加文字水印到水印库")
        self.setModal(True)
        self.resize(440, 390)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("留空则自动使用文字前 12 个字")
        form.addRow("素材名称：", self._name_edit)

        self._text_edit = QPlainTextEdit("© 原创画作 · 禁止二改搬运")
        self._text_edit.setFixedHeight(74)
        form.addRow("水印文字：", self._text_edit)

        self._role_combo = QComboBox()
        for key, label in (
            ("auto", "智能分级（自动大小错落）"),
            ("hero", "主视觉标题（大号醒目，如底部主标题）"),
            ("accent", "中号装饰/配文（边缘空白错落）"),
            ("micro", "微型防盗底纹（细密低透明防盗）"),
        ):
            self._role_combo.addItem(label, key)
        form.addRow("排版角色：", self._role_combo)

        self._font_combo = QComboBox()
        for name in discover_system_fonts():
            self._font_combo.addItem(name)
        idx = self._font_combo.findText("宋体")
        if idx >= 0:
            self._font_combo.setCurrentIndex(idx)
        form.addRow("字体：", self._font_combo)

        self._color_row = ColorPickerRow("", "#FFFFFF", show_presets=True)
        form.addRow("文字颜色：", self._color_row)

        self._stroke_chk = QCheckBox("开启细描边（增强亮暗背景可读性）")
        self._stroke_chk.setChecked(True)
        form.addRow("描边：", self._stroke_chk)

        self._glow_chk = QCheckBox("开启柔和外发光（梦境/艺术画风推荐）")
        self._glow_chk.setChecked(True)
        form.addRow("外发光：", self._glow_chk)

        self._scale_row = SliderSpinRow("默认比例", 6, 48, 22, suffix="%", label_width=58)
        form.addRow("基础大小：", self._scale_row)

        self._opacity_row = SliderSpinRow("默认透明", 15, 100, 78, suffix="%", label_width=58)
        form.addRow("不透明度：", self._opacity_row)

        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("添加到水印库")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self._text_edit.toPlainText().strip():
            QMessageBox.warning(self, "提示", "请输入水印文字内容。")
            return
        self.accept()

    def build_asset(self) -> CreativeAsset:
        raw_text = self._text_edit.toPlainText().strip()
        first_line = raw_text.splitlines()[0].strip() if raw_text else "文字水印"
        name = self._name_edit.text().strip() or first_line[:16]
        role = str(self._role_combo.currentData() or "auto")
        return CreativeAsset(
            id=new_id("txt"),
            kind="text",
            name=name,
            role=role,
            enabled=True,
            weight=1.0,
            text=raw_text,
            font_name=self._font_combo.currentText() or "宋体",
            color=self._color_row.color(),
            stroke_enabled=self._stroke_chk.isChecked(),
            stroke_color="#1E293B",
            stroke_width=2,
            glow_enabled=self._glow_chk.isChecked(),
            glow_color="#FFFFFF",
            glow_radius=6,
            base_scale=round(self._scale_row.value() / 100.0, 3),
            opacity=self._opacity_row.value(),
            rotation_range=6 if role != "micro" else 12,
            builtin=False,
        )


class DraggableAssetCard(QFrame):
    """Watermark Library item card supporting click-to-drop AND mouse drag onto CreativeCanvasWidget."""

    toggled_enabled = Signal(str, bool)
    role_changed = Signal(str, str)
    add_to_canvas = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, asset: CreativeAsset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.asset = asset
        self._drag_origin: QPoint | None = None

        self.setObjectName("CreativeAssetCard")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("按住并拖拽到中间画布任意位置，或点击右侧「＋」直接放上画布")

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(8)

        self._chk = QCheckBox()
        self._chk.setChecked(asset.enabled)
        self._chk.setToolTip("勾选后参与自动美观排版")
        self._chk.toggled.connect(lambda v: self.toggled_enabled.emit(self.asset.id, v))
        root.addWidget(self._chk)

        # Thumbnail preview
        self._thumb = QLabel()
        self._thumb.setFixedSize(46, 46)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setObjectName("AssetThumb")
        self._render_thumb()
        root.addWidget(self._thumb)

        # Info & role selector
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(3)

        title = QLabel(asset.name)
        title.setObjectName("AssetTitle")
        title.setMaximumWidth(120)
        info.addWidget(title)

        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(0, 0, 0, 0)
        sub_row.setSpacing(4)

        kind_tag = QLabel("图" if asset.kind == "image" else "字")
        kind_tag.setObjectName("KindBadgeImg" if asset.kind == "image" else "KindBadgeTxt")
        sub_row.addWidget(kind_tag)

        self._role_combo = QComboBox()
        self._role_combo.setObjectName("MiniCombo")
        self._role_combo.setFixedHeight(22)
        for rk, rlabel in ROLE_LABELS.items():
            self._role_combo.addItem(rlabel, rk)
        r_idx = self._role_combo.findData(asset.role)
        if r_idx >= 0:
            self._role_combo.setCurrentIndex(r_idx)
        self._role_combo.currentIndexChanged.connect(
            lambda _i: self.role_changed.emit(self.asset.id, str(self._role_combo.currentData()))
        )
        sub_row.addWidget(self._role_combo, 1)
        info.addLayout(sub_row)
        root.addLayout(info, 1)

        # Quick add & delete buttons
        btn_col = QVBoxLayout()
        btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(4)

        btn_add = QPushButton("＋")
        btn_add.setObjectName("CardActionBtn")
        btn_add.setFixedSize(22, 22)
        btn_add.setToolTip("添加到当前画布")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(lambda: self.add_to_canvas.emit(self.asset.id))
        btn_col.addWidget(btn_add)

        btn_del = QPushButton("✕")
        btn_del.setObjectName("CardRemoveBtn")
        btn_del.setFixedSize(22, 22)
        btn_del.setToolTip("从水印库删除")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.clicked.connect(lambda: self.delete_requested.emit(self.asset.id))
        btn_col.addWidget(btn_del)

        root.addLayout(btn_col)

    def _render_thumb(self) -> None:
        stamp = render_asset_stamp(self.asset, 42, opacity=95, glow_enabled=False)
        if stamp is not None:
            pm = pil_to_qpixmap(stamp).scaled(
                42,
                42,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._thumb.setPixmap(pm)
        else:
            self._thumb.setText("字" if self.asset.kind == "text" else "图")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._drag_origin is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and (event.position().toPoint() - self._drag_origin).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(MIME_CREATIVE_ASSET, QByteArray(self.asset.id.encode("utf-8")))
            drag.setMimeData(mime)
            pm = self._thumb.pixmap()
            if pm and not pm.isNull():
                drag.setPixmap(pm)
                drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
            self._drag_origin = None
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)


class FilmstripItemCard(QFrame):
    """Compact bottom filmstrip thumbnail for switching between images in Creative Mode."""

    clicked = Signal(str)
    remove_clicked = Signal(str)

    def __init__(self, doc: CreativeImageDoc, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc_id = doc.id
        self.setObjectName("FilmstripCard")
        self.setFixedSize(112, 82)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 4, 5, 4)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(2)
        self._badge = QLabel("0 层")
        self._badge.setObjectName("GroupCountBadge")
        top.addWidget(self._badge)
        top.addStretch(1)

        btn_x = QPushButton("✕")
        btn_x.setObjectName("CardRemoveBtn")
        btn_x.setFixedSize(18, 18)
        btn_x.clicked.connect(lambda: self.remove_clicked.emit(self.doc_id))
        top.addWidget(btn_x)
        lay.addLayout(top)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setFixedHeight(38)
        pm = pil_to_qpixmap(doc.preview_base).scaled(
            98, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self._img_lbl.setPixmap(pm)
        lay.addWidget(self._img_lbl)

        name = QLabel(doc.filename)
        name.setObjectName("MutedLabel")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setToolTip(doc.filename)
        lay.addWidget(name)

        self.set_layer_count(len(doc.placements))

    def set_layer_count(self, count: int) -> None:
        self._badge.setText(f"{count} 层")

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.doc_id)
        super().mousePressEvent(event)


class CreativeWorkspaceWidget(QWidget):
    """Completely independent Creative Mode Studio workspace."""

    status_message = Signal(str)

    def __init__(
        self,
        library_store: CreativeLibraryStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.library_store = library_store or CreativeLibraryStore()
        self._docs: dict[str, CreativeImageDoc] = {}
        self._doc_order: list[str] = []
        self._path_index: set[str] = set()
        self._active_doc_id: str = ""
        self._filmstrip_cards: dict[str, FilmstripItemCard] = {}

        self._auto_config = AutoLayoutConfig()
        self._updating_inspector = False
        self._last_import_dir = ""

        self._build_ui()
        self._connect_signals()
        self._rebuild_library_ui()
        self._refresh_toolbar_state()

    # ---- UI Construction ----

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top Creative Action Bar
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(52)
        tb = QHBoxLayout(top)
        tb.setContentsMargins(14, 6, 14, 6)
        tb.setSpacing(7)

        self._btn_add_images = QPushButton("＋ 添加图片")
        self._btn_add_images.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(self._btn_add_images)

        self._btn_add_folder = QPushButton("📂 添加文件夹")
        self._btn_add_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(self._btn_add_folder)

        self._btn_clear_docs = QPushButton("✕ 清空图片")
        self._btn_clear_docs.setObjectName("DangerButton")
        self._btn_clear_docs.setEnabled(False)
        tb.addWidget(self._btn_clear_docs)

        self._doc_count_badge = QLabel("共 0 张")
        self._doc_count_badge.setObjectName("CountBadge")
        tb.addWidget(self._doc_count_badge)

        tb.addSpacing(8)

        self._btn_auto_current = QPushButton("✨ 智能排版")
        self._btn_auto_current.setObjectName("PrimaryButton")
        self._btn_auto_current.setEnabled(False)
        self._btn_auto_current.setToolTip("使用避让主体的多尺度美学算法，自动为当前图片生成美观的大小不一水印")
        tb.addWidget(self._btn_auto_current)

        self._btn_shuffle = QPushButton("🎲 换一版")
        self._btn_shuffle.setEnabled(False)
        self._btn_shuffle.setToolTip("更换随机种子重新生成（已锁定的水印图层会保留）")
        tb.addWidget(self._btn_shuffle)

        self._btn_auto_all = QPushButton("⚡ 全部智能排版")
        self._btn_auto_all.setEnabled(False)
        self._btn_auto_all.setToolTip("为所有已导入图片各自生成适配其构图的智能水印排版")
        tb.addWidget(self._btn_auto_all)

        self._btn_sync_all = QPushButton("📋 套用当前到全部")
        self._btn_sync_all.setEnabled(False)
        self._btn_sync_all.setToolTip("将当前图片手工精修好的排版按相对比例同步套用到全部图片")
        tb.addWidget(self._btn_sync_all)

        tb.addStretch(1)

        self._btn_undo = QPushButton("↶ 撤销")
        self._btn_undo.setObjectName("GhostButton")
        self._btn_undo.setEnabled(False)
        tb.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("↷ 重做")
        self._btn_redo.setObjectName("GhostButton")
        self._btn_redo.setEnabled(False)
        tb.addWidget(self._btn_redo)

        self._btn_export_all = QPushButton("⬇ 导出创作图片")
        self._btn_export_all.setObjectName("PrimaryButton")
        self._btn_export_all.setEnabled(False)
        tb.addWidget(self._btn_export_all)

        root.addWidget(top)

        # 3-Pane Splitter: Left Library | Center Canvas + Filmstrip | Right Algorithm + Inspector
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        splitter.addWidget(self._build_library_pane())
        splitter.addWidget(self._build_center_pane())
        splitter.addWidget(self._build_right_pane())

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([285, 760, 345])

        root.addWidget(splitter, 1)

    def _build_library_pane(self) -> QWidget:
        pane = QFrame()
        pane.setObjectName("CreativeSidePane")
        pane.setMinimumWidth(250)
        pane.setMaximumWidth(360)

        lay = QVBoxLayout(pane)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        hdr = QHBoxLayout()
        title = QLabel("🎨 水印素材库（图片 + 文字）")
        title.setObjectName("SectionTitle")
        hdr.addWidget(title)
        hdr.addStretch(1)
        self._lib_count_lbl = QLabel("0 项")
        self._lib_count_lbl.setObjectName("GroupCountBadge")
        hdr.addWidget(self._lib_count_lbl)
        lay.addLayout(hdr)

        hint = QLabel("勾选参与自动排版；按住卡片拖到画布任意位置即可自由打水印")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._btn_upload_img_asset = QPushButton("＋ 上传图片水印")
        self._btn_upload_img_asset.setObjectName("PrimaryButton")
        self._btn_upload_img_asset.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._btn_upload_img_asset, 1)

        self._btn_add_text_asset = QPushButton("＋ 文字水印")
        self._btn_add_text_asset.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._btn_add_text_asset, 1)
        lay.addLayout(add_row)

        pack_row = QHBoxLayout()
        pack_row.setSpacing(4)
        self._btn_import_pack = QPushButton("导入库")
        self._btn_import_pack.setObjectName("GhostButton")
        self._btn_export_pack = QPushButton("导出库")
        self._btn_export_pack.setObjectName("GhostButton")
        self._btn_reset_lib = QPushButton("恢复默认")
        self._btn_reset_lib.setObjectName("GhostButton")
        pack_row.addWidget(self._btn_import_pack)
        pack_row.addWidget(self._btn_export_pack)
        pack_row.addWidget(self._btn_reset_lib)
        lay.addLayout(pack_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._lib_host = QWidget()
        self._lib_host.setObjectName("PanelBody")
        self._lib_layout = QVBoxLayout(self._lib_host)
        self._lib_layout.setContentsMargins(0, 2, 2, 2)
        self._lib_layout.setSpacing(6)
        self._lib_layout.addStretch(1)
        scroll.setWidget(self._lib_host)
        lay.addWidget(scroll, 1)

        return pane

    def _build_center_pane(self) -> QWidget:
        pane = QWidget()
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.canvas = CreativeCanvasWidget()
        lay.addWidget(self.canvas, 1)

        # Bottom filmstrip bar
        strip_bar = QFrame()
        strip_bar.setObjectName("GalleryFilterBar")
        strip_bar.setFixedHeight(98)
        s_lay = QHBoxLayout(strip_bar)
        s_lay.setContentsMargins(8, 6, 8, 6)

        self._filmstrip_scroll = QScrollArea()
        self._filmstrip_scroll.setWidgetResizable(True)
        self._filmstrip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._filmstrip_host = QWidget()
        self._filmstrip_host.setObjectName("GridHost")
        self._filmstrip_layout = QHBoxLayout(self._filmstrip_host)
        self._filmstrip_layout.setContentsMargins(2, 0, 2, 0)
        self._filmstrip_layout.setSpacing(8)
        self._filmstrip_layout.addStretch(1)
        self._filmstrip_scroll.setWidget(self._filmstrip_host)

        s_lay.addWidget(self._filmstrip_scroll)
        lay.addWidget(strip_bar)
        return pane

    def _build_right_pane(self) -> QWidget:
        container = QWidget()
        container.setMinimumWidth(310)
        container.setMaximumWidth(420)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("PanelBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)

        # ---- Card 1: Auto Aesthetic Layout ----
        auto_card = SectionCard("✨ 自动美学排版算法")
        ab = auto_card.body_layout

        style_row = QHBoxLayout()
        style_lbl = QLabel("风格")
        style_lbl.setFixedWidth(56)
        self._style_combo = QComboBox()
        for key, label in STYLE_OPTIONS:
            self._style_combo.addItem(label, key)
        style_row.addWidget(style_lbl)
        style_row.addWidget(self._style_combo, 1)
        ab.addLayout(style_row)

        self._density_slider = SliderSpinRow("分布密度", 10, 100, self._auto_config.density, suffix="%", label_width=62)
        self._scale_var_slider = SliderSpinRow("大小差异", 0, 100, self._auto_config.scale_variation, suffix="%", label_width=62)
        self._avoid_slider = SliderSpinRow("主体避让", 0, 100, self._auto_config.subject_avoidance, suffix="%", label_width=62)
        self._global_op_slider = SliderSpinRow("整体透明", 15, 100, self._auto_config.global_opacity, suffix="%", label_width=62)
        self._rot_jitter_slider = SliderSpinRow("随机倾斜", 0, 45, self._auto_config.rotation_jitter, suffix="°", label_width=62)
        for w in (
            self._density_slider,
            self._scale_var_slider,
            self._avoid_slider,
            self._global_op_slider,
            self._rot_jitter_slider,
        ):
            ab.addWidget(w)

        self._chk_soft_glow = QCheckBox("柔和外发光（亮暗背景均通透清晰）")
        self._chk_soft_glow.setChecked(self._auto_config.soft_glow)
        ab.addWidget(self._chk_soft_glow)

        self._chk_micro_grid = QCheckBox("补充微型防盗底纹（示例图同款细纹）")
        self._chk_micro_grid.setChecked(self._auto_config.include_micro_grid)
        ab.addWidget(self._chk_micro_grid)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_panel_generate = QPushButton("✨ 生成美观排版")
        self._btn_panel_generate.setObjectName("PrimaryButton")
        self._btn_panel_shuffle = QPushButton("🎲 换一版")
        self._btn_clear_layers = QPushButton("清空图层")
        self._btn_clear_layers.setObjectName("GhostButton")
        btn_row.addWidget(self._btn_panel_generate, 2)
        btn_row.addWidget(self._btn_panel_shuffle, 1)
        btn_row.addWidget(self._btn_clear_layers)
        ab.addLayout(btn_row)
        bl.addWidget(auto_card)

        # ---- Card 2: Selected Layer Inspector ----
        insp_card = SectionCard("🖐️ 选中水印精修（自由拖拽/缩放/旋转）")
        ib = insp_card.body_layout

        self._insp_empty_lbl = QLabel("在画布中点击任意水印，或从左侧拖入水印后，可单独精修属性；支持键盘 Delete 删除与 Ctrl+Z 撤销。")
        self._insp_empty_lbl.setObjectName("MutedLabel")
        self._insp_empty_lbl.setWordWrap(True)
        ib.addWidget(self._insp_empty_lbl)

        self._insp_controls = QWidget()
        ic = QVBoxLayout(self._insp_controls)
        ic.setContentsMargins(0, 0, 0, 0)
        ic.setSpacing(6)

        self._insp_name_lbl = QLabel("")
        self._insp_name_lbl.setObjectName("InfoHintBadge")
        ic.addWidget(self._insp_name_lbl)

        self._layer_scale_row = DoubleSliderSpinRow("大小比例", 3.0, 80.0, 14.0, step=1.0, suffix="%", label_width=62)
        self._layer_op_row = SliderSpinRow("不透明度", 5, 100, 75, suffix="%", label_width=62)
        self._layer_rot_row = DoubleSliderSpinRow("旋转角度", -180.0, 180.0, 0.0, step=1.0, suffix="°", label_width=62)
        ic.addWidget(self._layer_scale_row)
        ic.addWidget(self._layer_op_row)
        ic.addWidget(self._layer_rot_row)

        chk_row = QHBoxLayout()
        self._layer_glow_chk = QCheckBox("柔和外发光")
        self._layer_lock_chk = QCheckBox("🔒 锁定（换一版保留）")
        chk_row.addWidget(self._layer_glow_chk)
        chk_row.addWidget(self._layer_lock_chk)
        ic.addLayout(chk_row)

        act_row = QHBoxLayout()
        act_row.setSpacing(4)
        self._btn_layer_up = QPushButton("上移")
        self._btn_layer_up.setObjectName("GhostButton")
        self._btn_layer_down = QPushButton("下移")
        self._btn_layer_down.setObjectName("GhostButton")
        self._btn_layer_dup = QPushButton("复制")
        self._btn_layer_dup.setObjectName("GhostButton")
        self._btn_layer_del = QPushButton("删除")
        self._btn_layer_del.setObjectName("DangerButton")
        for b in (self._btn_layer_up, self._btn_layer_down, self._btn_layer_dup, self._btn_layer_del):
            act_row.addWidget(b, 1)
        ic.addLayout(act_row)

        self._insp_controls.setVisible(False)
        ib.addWidget(self._insp_controls)
        bl.addWidget(insp_card)

        # ---- Card 3: Creative Export Settings ----
        exp_card = SectionCard("⬇ 导出设置")
        eb = exp_card.body_layout

        fmt_row = QHBoxLayout()
        fmt_lbl = QLabel("输出格式")
        fmt_lbl.setFixedWidth(62)
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItem("保持原格式", OutputFormat.KEEP_ORIGINAL)
        self._fmt_combo.addItem("PNG（无损）", OutputFormat.PNG)
        self._fmt_combo.addItem("JPEG", OutputFormat.JPEG)
        self._fmt_combo.addItem("WebP", OutputFormat.WEBP)
        fmt_row.addWidget(fmt_lbl)
        fmt_row.addWidget(self._fmt_combo, 1)
        eb.addLayout(fmt_row)

        self._quality_row = SliderSpinRow("导出质量", 50, 100, 94, suffix="%", label_width=62)
        eb.addWidget(self._quality_row)

        suf_row = QHBoxLayout()
        suf_lbl = QLabel("文件后缀")
        suf_lbl.setFixedWidth(62)
        self._suffix_edit = QLineEdit("_creative")
        suf_row.addWidget(suf_lbl)
        suf_row.addWidget(self._suffix_edit, 1)
        eb.addLayout(suf_row)

        dir_row = QHBoxLayout()
        self._out_dir_edit = QLineEdit()
        self._out_dir_edit.setPlaceholderText("选择导出目标文件夹...")
        self._btn_browse_out = QPushButton("浏览")
        self._btn_browse_out.setObjectName("GhostButton")
        dir_row.addWidget(self._out_dir_edit, 1)
        dir_row.addWidget(self._btn_browse_out)
        eb.addLayout(dir_row)

        bl.addWidget(exp_card)
        bl.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # Sticky bottom export footer
        footer = QFrame()
        footer.setObjectName("ExportFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(10, 8, 10, 10)
        fl.setSpacing(6)
        self._btn_export_cur = QPushButton("导出当前图")
        self._btn_export_cur.setEnabled(False)
        self._btn_footer_export_all = QPushButton("⬇ 批量导出全部")
        self._btn_footer_export_all.setObjectName("PrimaryButton")
        self._btn_footer_export_all.setEnabled(False)
        fl.addWidget(self._btn_export_cur, 1)
        fl.addWidget(self._btn_footer_export_all, 2)
        outer.addWidget(footer)

        return container

    def _connect_signals(self) -> None:
        self._btn_add_images.clicked.connect(self._open_add_images)
        self._btn_add_folder.clicked.connect(self._open_add_folder)
        self._btn_clear_docs.clicked.connect(self.clear_all_docs)
        self._btn_auto_current.clicked.connect(lambda: self.run_auto_layout_current(new_seed=False))
        self._btn_panel_generate.clicked.connect(lambda: self.run_auto_layout_current(new_seed=False))
        self._btn_shuffle.clicked.connect(lambda: self.run_auto_layout_current(new_seed=True))
        self._btn_panel_shuffle.clicked.connect(lambda: self.run_auto_layout_current(new_seed=True))
        self._btn_auto_all.clicked.connect(self.run_auto_layout_all)
        self._btn_sync_all.clicked.connect(self.sync_current_layout_to_all)
        self._btn_clear_layers.clicked.connect(self.clear_unlocked_layers)

        self._btn_undo.clicked.connect(self.undo)
        self._btn_redo.clicked.connect(self.redo)

        self._btn_upload_img_asset.clicked.connect(self._open_upload_image_assets)
        self._btn_add_text_asset.clicked.connect(self._open_add_text_asset)
        self._btn_import_pack.clicked.connect(self._import_library_pack)
        self._btn_export_pack.clicked.connect(self._export_library_pack)
        self._btn_reset_lib.clicked.connect(self._reset_library_to_builtins)

        # Auto-layout controls sync
        self._style_combo.currentIndexChanged.connect(self._sync_auto_config_from_ui)
        self._density_slider.value_changed.connect(self._sync_auto_config_from_ui)
        self._scale_var_slider.value_changed.connect(self._sync_auto_config_from_ui)
        self._avoid_slider.value_changed.connect(self._sync_auto_config_from_ui)
        self._global_op_slider.value_changed.connect(self._sync_auto_config_from_ui)
        self._rot_jitter_slider.value_changed.connect(self._sync_auto_config_from_ui)
        self._chk_soft_glow.toggled.connect(self._sync_auto_config_from_ui)
        self._chk_micro_grid.toggled.connect(self._sync_auto_config_from_ui)

        # Canvas interaction signals
        self.canvas.add_images_clicked.connect(self._open_add_images)
        self.canvas.files_dropped.connect(self.add_image_paths)
        self.canvas.asset_dropped.connect(self.drop_asset_onto_current)
        self.canvas.selection_changed.connect(self._refresh_inspector)
        self.canvas.layer_changed.connect(self._refresh_inspector)
        self.canvas.layer_committed.connect(self._on_layer_committed)
        self.canvas.delete_requested.connect(self.delete_layer)
        self.canvas.duplicate_requested.connect(self.duplicate_layer)
        self.canvas.undo_requested.connect(self.undo)
        self.canvas.redo_requested.connect(self.redo)

        # Inspector controls
        self._layer_scale_row.value_changed.connect(self._on_inspector_changed)
        self._layer_op_row.value_changed.connect(self._on_inspector_changed)
        self._layer_rot_row.value_changed.connect(self._on_inspector_changed)
        self._layer_glow_chk.toggled.connect(self._on_inspector_changed)
        self._layer_lock_chk.toggled.connect(self._on_inspector_changed)
        self._btn_layer_up.clicked.connect(lambda: self.move_selected_layer(1))
        self._btn_layer_down.clicked.connect(lambda: self.move_selected_layer(-1))
        self._btn_layer_dup.clicked.connect(lambda: self.duplicate_layer(self.canvas.selected_id))
        self._btn_layer_del.clicked.connect(lambda: self.delete_layer(self.canvas.selected_id))

        # Export
        self._btn_browse_out.clicked.connect(self._browse_output_dir)
        self._btn_export_cur.clicked.connect(lambda: self.start_export(only_current=True))
        self._btn_export_all.clicked.connect(lambda: self.start_export(only_current=False))
        self._btn_footer_export_all.clicked.connect(lambda: self.start_export(only_current=False))

    # ---- Watermark Library Operations ----

    def _rebuild_library_ui(self) -> None:
        while self._lib_layout.count() > 1:
            item = self._lib_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        assets = self.library_store.list_assets()
        for asset in assets:
            card = DraggableAssetCard(asset)
            card.toggled_enabled.connect(self._on_asset_enabled_toggled)
            card.role_changed.connect(self._on_asset_role_changed)
            card.add_to_canvas.connect(self.add_asset_to_current_center)
            card.delete_requested.connect(self._on_asset_delete)
            self._lib_layout.insertWidget(self._lib_layout.count() - 1, card)

        self._lib_count_lbl.setText(f"{len(assets)} 项")
        self.canvas.set_assets(self.library_store.asset_map())

    def _open_upload_image_assets(self) -> None:
        exts = " ".join(f"*{e}" for e in SUPPORTED_INPUT_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "上传图片水印到水印库（推荐使用透明背景 PNG / WebP）",
            self._last_import_dir,
            f"图片文件 ({exts});;所有文件 (*.*)",
        )
        if not files:
            return
        self._last_import_dir = str(Path(files[0]).parent)
        added = self.add_image_assets_from_paths([Path(f) for f in files])
        if added:
            self.status_message.emit(f"创作模式：已添加 {added} 个图片水印到水印库")

    def add_image_assets_from_paths(self, paths: Iterable[Path]) -> int:
        count = 0
        for p in paths:
            try:
                asset = image_file_to_asset(Path(p))
                self.library_store.add_asset(asset)
                count += 1
            except Exception:  # noqa: BLE001
                continue
        if count:
            self._rebuild_library_ui()
        return count

    def _open_add_text_asset(self) -> None:
        dlg = AddTextAssetDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            asset = dlg.build_asset()
            self.library_store.add_asset(asset)
            self._rebuild_library_ui()
            self.status_message.emit(f"创作模式：已添加文字水印「{asset.name}」到水印库")

    def _on_asset_enabled_toggled(self, asset_id: str, enabled: bool) -> None:
        asset = self.library_store.get_asset(asset_id)
        if asset:
            asset.enabled = enabled
            self.library_store.update_asset(asset)
            self.canvas.set_assets(self.library_store.asset_map())

    def _on_asset_role_changed(self, asset_id: str, role: str) -> None:
        asset = self.library_store.get_asset(asset_id)
        if asset:
            asset.role = role
            self.library_store.update_asset(asset)
            self.canvas.set_assets(self.library_store.asset_map())

    def _on_asset_delete(self, asset_id: str) -> None:
        if self.library_store.delete_asset(asset_id):
            self._rebuild_library_ui()
            # Also remove orphaned layers referencing deleted asset
            for doc in self._docs.values():
                doc.placements = [p for p in doc.placements if p.asset_id != asset_id]
                card = self._filmstrip_cards.get(doc.id)
                if card:
                    card.set_layer_count(len(doc.placements))
            self._sync_active_doc_to_canvas()

    def _import_library_pack(self) -> None:
        fp, _ = QFileDialog.getOpenFileName(
            self, "导入创作模式水印库 (.json)", "", "JSON 水印库 (*.json)"
        )
        if not fp:
            return
        try:
            imported = self.library_store.import_pack(Path(fp), replace=False)
            self._rebuild_library_ui()
            self.status_message.emit(f"创作模式：成功导入 {len(imported)} 个水印库素材")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", str(exc))

    def _export_library_pack(self) -> None:
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出创作模式水印库 (.json)", "creative_watermark_library.json", "JSON 水印库 (*.json)"
        )
        if not fp:
            return
        count = self.library_store.export_pack(Path(fp))
        self.status_message.emit(f"创作模式：已导出 {count} 个素材到 {fp}")

    def _reset_library_to_builtins(self) -> None:
        self.library_store.reset_to_builtins()
        self._rebuild_library_ui()
        self.status_message.emit("创作模式：已恢复默认艺术水印库（雪花/星光/初雪印章/诗意文字）")

    # ---- Image Queue Operations ----

    def _open_add_images(self) -> None:
        exts = " ".join(f"*{e}" for e in SUPPORTED_INPUT_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择创作模式图片", self._last_import_dir, f"图片文件 ({exts});;所有文件 (*.*)"
        )
        if files:
            self._last_import_dir = str(Path(files[0]).parent)
            self.add_image_paths([Path(f) for f in files])

    def _open_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择包含图片的文件夹", self._last_import_dir)
        if folder:
            self._last_import_dir = folder
            self.add_image_paths([Path(folder)])

    def add_image_paths(self, paths: Iterable[Path]) -> int:
        found = scan_image_files(paths, recursive=True)
        added = 0
        first_new_id = ""
        for p in found:
            key = str(p.resolve()).lower()
            if key in self._path_index:
                continue
            try:
                preview_base, orig_w, orig_h, _fmt, _sz = create_preview_base(p, max_edge=1100)
            except Exception:  # noqa: BLE001
                continue
            doc = CreativeImageDoc(
                id=new_id("cdoc"),
                path=p,
                filename=p.name,
                orig_width=orig_w,
                orig_height=orig_h,
                preview_base=preview_base,
            )
            self._docs[doc.id] = doc
            self._doc_order.append(doc.id)
            self._path_index.add(key)
            if not first_new_id:
                first_new_id = doc.id

            card = FilmstripItemCard(doc)
            card.clicked.connect(self.select_doc)
            card.remove_clicked.connect(self.remove_doc)
            self._filmstrip_cards[doc.id] = card
            self._filmstrip_layout.insertWidget(self._filmstrip_layout.count() - 1, card)
            added += 1

        if added:
            if not self._active_doc_id and first_new_id:
                self.select_doc(first_new_id)
            self._refresh_toolbar_state()
            self.status_message.emit(f"创作模式：已导入 {added} 张图片，可点击「✨ 智能排版」或拖入左侧水印")
        return added

    def select_doc(self, doc_id: str) -> None:
        if doc_id not in self._docs:
            return
        self._active_doc_id = doc_id
        for did, card in self._filmstrip_cards.items():
            card.set_selected(did == doc_id)
        self._sync_active_doc_to_canvas()
        self._refresh_toolbar_state()

    def remove_doc(self, doc_id: str) -> None:
        doc = self._docs.pop(doc_id, None)
        if doc is None:
            return
        self._doc_order = [i for i in self._doc_order if i != doc_id]
        self._path_index.discard(str(doc.path.resolve()).lower())
        card = self._filmstrip_cards.pop(doc_id, None)
        if card is not None:
            self._filmstrip_layout.removeWidget(card)
            card.deleteLater()

        if self._active_doc_id == doc_id:
            self._active_doc_id = self._doc_order[0] if self._doc_order else ""
        if self._active_doc_id:
            self.select_doc(self._active_doc_id)
        else:
            self.canvas.set_scene(None, (0, 0), [], self.library_store.asset_map(), "")
            self._refresh_inspector("")
            self._refresh_toolbar_state()

    def clear_all_docs(self) -> None:
        for doc_id in list(self._doc_order):
            self.remove_doc(doc_id)
        self.status_message.emit("创作模式：已清空图片队列")

    def _active_doc(self) -> CreativeImageDoc | None:
        return self._docs.get(self._active_doc_id)

    def _sync_active_doc_to_canvas(self, selected_layer_id: str | None = None) -> None:
        doc = self._active_doc()
        if doc is None:
            self.canvas.set_scene(None, (0, 0), [], self.library_store.asset_map(), "")
            self._refresh_inspector("")
            return
        sel = self.canvas.selected_id if selected_layer_id is None else selected_layer_id
        self.canvas.set_scene(
            doc.preview_base,
            (doc.orig_width, doc.orig_height),
            doc.placements,
            self.library_store.asset_map(),
            selected_id=sel,
        )
        card = self._filmstrip_cards.get(doc.id)
        if card:
            card.set_layer_count(len(doc.placements))
        self._refresh_inspector(self.canvas.selected_id)

    # ---- Auto Aesthetic Layout & Manual Drag/Drop ----

    def _sync_auto_config_from_ui(self) -> None:
        self._auto_config.style = str(self._style_combo.currentData() or "artistic_scatter")
        self._auto_config.density = self._density_slider.value()
        self._auto_config.scale_variation = self._scale_var_slider.value()
        self._auto_config.subject_avoidance = self._avoid_slider.value()
        self._auto_config.global_opacity = self._global_op_slider.value()
        self._auto_config.rotation_jitter = self._rot_jitter_slider.value()
        self._auto_config.soft_glow = self._chk_soft_glow.isChecked()
        self._auto_config.include_micro_grid = self._chk_micro_grid.isChecked()

    def run_auto_layout_current(self, *, new_seed: bool = False) -> int:
        doc = self._active_doc()
        if doc is None:
            return 0
        self._sync_auto_config_from_ui()
        assets = [a for a in self.library_store.list_assets() if a.enabled]
        if not assets:
            QMessageBox.information(self, "水印库为空", "请先在左侧勾选或上传至少 1 个图片/文字水印素材。")
            return 0
        if new_seed:
            self._auto_config.seed = random.randint(1, 999_999_999)

        doc.push_undo()
        locked_layers = [p for p in doc.placements if p.locked]
        doc.placements = generate_aesthetic_layout(
            (doc.orig_width, doc.orig_height),
            assets,
            self._auto_config,
            base_image=doc.preview_base,
            existing_locked=locked_layers,
        )
        self._sync_active_doc_to_canvas(selected_layer_id="")
        self._refresh_toolbar_state()
        self.status_message.emit(
            f"创作模式：已为「{doc.filename}」智能排版 {len(doc.placements)} 个错落水印（点击任意水印可再拖拽微调）"
        )
        return len(doc.placements)

    def run_auto_layout_all(self) -> None:
        if not self._doc_order:
            return
        self._sync_auto_config_from_ui()
        assets = [a for a in self.library_store.list_assets() if a.enabled]
        if not assets:
            QMessageBox.information(self, "水印库为空", "请先在左侧勾选或上传至少 1 个水印素材。")
            return

        for idx, doc_id in enumerate(self._doc_order):
            doc = self._docs[doc_id]
            doc.push_undo()
            cfg = self._auto_config.clone()
            cfg.seed = (cfg.seed + idx * 7919) & 0x7FFFFFFF
            locked_layers = [p for p in doc.placements if p.locked]
            doc.placements = generate_aesthetic_layout(
                (doc.orig_width, doc.orig_height),
                assets,
                cfg,
                base_image=doc.preview_base,
                existing_locked=locked_layers,
            )
            card = self._filmstrip_cards.get(doc.id)
            if card:
                card.set_layer_count(len(doc.placements))
        self._sync_active_doc_to_canvas(selected_layer_id="")
        self._refresh_toolbar_state()
        self.status_message.emit(f"创作模式：已为全部 {len(self._doc_order)} 张图片分别生成智能美学排版")

    def sync_current_layout_to_all(self) -> None:
        src = self._active_doc()
        if src is None or len(self._doc_order) < 2:
            return
        for doc_id in self._doc_order:
            if doc_id == src.id:
                continue
            dst = self._docs[doc_id]
            dst.push_undo()
            dst.placements = [p.clone(new_layer_id=True) for p in src.placements]
            card = self._filmstrip_cards.get(dst.id)
            if card:
                card.set_layer_count(len(dst.placements))
        self.status_message.emit(
            f"创作模式：已将「{src.filename}」的 {len(src.placements)} 个水印按相对坐标同步套用到全部图片"
        )

    def drop_asset_onto_current(self, asset_id: str, nx: float, ny: float) -> CreativePlacement | None:
        doc = self._active_doc()
        asset = self.library_store.get_asset(asset_id)
        if doc is None or asset is None:
            return None
        doc.push_undo()
        max_z = max((p.z_index for p in doc.placements), default=-1)
        layer = CreativePlacement(
            id=new_id("lyr"),
            asset_id=asset.id,
            x=round(nx, 5),
            y=round(ny, 5),
            scale=asset.base_scale,
            rotation=0.0,
            opacity=asset.opacity,
            glow_enabled=asset.glow_enabled,
            locked=False,
            auto_generated=False,
            z_index=max_z + 1,
        )
        doc.placements.append(layer)
        self._sync_active_doc_to_canvas(selected_layer_id=layer.id)
        self._refresh_toolbar_state()
        self.status_message.emit(f"已添加水印「{asset.name}」，可拖动位置、拉四角缩放或拉顶圆点旋转")
        return layer

    def add_asset_to_current_center(self, asset_id: str) -> CreativePlacement | None:
        doc = self._active_doc()
        if doc is None:
            QMessageBox.information(self, "请先导入图片", "请先点击左上角「＋ 添加图片」导入底图后再添加水印。")
            return None
        jitter = (len(doc.placements) % 5 - 2) * 0.03
        return self.drop_asset_onto_current(asset_id, 0.5 + jitter, 0.5 + jitter)

    def clear_unlocked_layers(self) -> None:
        doc = self._active_doc()
        if doc is None or not doc.placements:
            return
        doc.push_undo()
        doc.placements = [p for p in doc.placements if p.locked]
        self._sync_active_doc_to_canvas(selected_layer_id="")
        self._refresh_toolbar_state()

    # ---- Layer Editing & Inspector ----

    def _selected_layer(self) -> CreativePlacement | None:
        doc = self._active_doc()
        if doc is None or not self.canvas.selected_id:
            return None
        return next((p for p in doc.placements if p.id == self.canvas.selected_id), None)

    def _refresh_inspector(self, _layer_id: str = "") -> None:
        layer = self._selected_layer()
        self._updating_inspector = True
        try:
            if layer is None:
                self._insp_empty_lbl.setVisible(True)
                self._insp_controls.setVisible(False)
                return
            asset = self.library_store.get_asset(layer.asset_id)
            name = asset.name if asset else "水印图层"
            tag = "自动生成" if layer.auto_generated else "手动放置"
            self._insp_name_lbl.setText(f"当前选中：{name}（{tag}）")
            self._layer_scale_row.set_value(round(layer.scale * 100.0, 1), emit=False)
            self._layer_op_row.set_value(layer.opacity, emit=False)
            self._layer_rot_row.set_value(round(layer.rotation, 1), emit=False)
            self._layer_glow_chk.setChecked(layer.glow_enabled)
            self._layer_lock_chk.setChecked(layer.locked)
            self._insp_empty_lbl.setVisible(False)
            self._insp_controls.setVisible(True)
        finally:
            self._updating_inspector = False

    def _on_inspector_changed(self, *_args) -> None:
        if self._updating_inspector:
            return
        layer = self._selected_layer()
        if layer is None:
            return
        layer.scale = round(self._layer_scale_row.value() / 100.0, 5)
        layer.opacity = self._layer_op_row.value()
        layer.rotation = round(self._layer_rot_row.value(), 2)
        layer.glow_enabled = self._layer_glow_chk.isChecked()
        layer.locked = self._layer_lock_chk.isChecked()
        self.canvas.update()

    def _on_layer_committed(self, _layer_id: str) -> None:
        self._refresh_toolbar_state()

    def move_selected_layer(self, delta: int) -> None:
        doc = self._active_doc()
        layer = self._selected_layer()
        if doc is None or layer is None:
            return
        doc.push_undo()
        ordered = sorted(doc.placements, key=lambda p: p.z_index)
        idx = ordered.index(layer)
        new_idx = max(0, min(len(ordered) - 1, idx + delta))
        if new_idx != idx:
            ordered.insert(new_idx, ordered.pop(idx))
            for i, p in enumerate(ordered):
                p.z_index = i
            doc.placements = ordered
            self.canvas.set_placements(doc.placements, layer.id)

    def duplicate_layer(self, layer_id: str) -> None:
        doc = self._active_doc()
        if doc is None:
            return
        src = next((p for p in doc.placements if p.id == layer_id), None)
        if src is None:
            return
        doc.push_undo()
        dup = src.clone(new_layer_id=True)
        dup.x = round(min(0.95, dup.x + 0.04), 5)
        dup.y = round(min(0.95, dup.y + 0.04), 5)
        dup.auto_generated = False
        dup.z_index = max((p.z_index for p in doc.placements), default=0) + 1
        doc.placements.append(dup)
        self._sync_active_doc_to_canvas(selected_layer_id=dup.id)
        self._refresh_toolbar_state()

    def delete_layer(self, layer_id: str) -> None:
        doc = self._active_doc()
        if doc is None or not layer_id:
            return
        if not any(p.id == layer_id for p in doc.placements):
            return
        doc.push_undo()
        doc.placements = [p for p in doc.placements if p.id != layer_id]
        self._sync_active_doc_to_canvas(selected_layer_id="")
        self._refresh_toolbar_state()

    def undo(self) -> None:
        doc = self._active_doc()
        if doc and doc.undo():
            self._sync_active_doc_to_canvas(selected_layer_id="")
            self._refresh_toolbar_state()

    def redo(self) -> None:
        doc = self._active_doc()
        if doc and doc.redo():
            self._sync_active_doc_to_canvas(selected_layer_id="")
            self._refresh_toolbar_state()

    def _refresh_toolbar_state(self) -> None:
        count = len(self._doc_order)
        has_docs = count > 0
        doc = self._active_doc()
        self._doc_count_badge.setText(f"共 {count} 张")
        self._btn_clear_docs.setEnabled(has_docs)
        self._btn_auto_current.setEnabled(has_docs)
        self._btn_shuffle.setEnabled(has_docs)
        self._btn_auto_all.setEnabled(has_docs)
        self._btn_sync_all.setEnabled(count >= 2)
        self._btn_export_all.setEnabled(has_docs)
        self._btn_export_cur.setEnabled(has_docs)
        self._btn_footer_export_all.setEnabled(has_docs)
        self._btn_undo.setEnabled(bool(doc and doc.undo_stack))
        self._btn_redo.setEnabled(bool(doc and doc.redo_stack))

    # ---- Export ----

    def _browse_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择创作模式导出目录", self._out_dir_edit.text())
        if folder:
            self._out_dir_edit.setText(folder)

    def build_export_config(self) -> ExportConfig:
        return ExportConfig(
            output_dir=self._out_dir_edit.text().strip(),
            filename_suffix=self._suffix_edit.text() or "_creative",
            output_format=self._fmt_combo.currentData() or OutputFormat.KEEP_ORIGINAL,
            quality=self._quality_row.value(),
            keep_exif=True,
            conflict_policy=ConflictPolicy.AUTO_RENAME,
            isolate_orientation=False,
        )

    def start_export(self, *, only_current: bool = False) -> None:
        if not self._doc_order:
            return
        targets = [self._active_doc()] if only_current else [self._docs[i] for i in self._doc_order]
        targets = [d for d in targets if d is not None]
        if not targets:
            return

        exp_cfg = self.build_export_config()
        if not exp_cfg.output_dir:
            folder = QFileDialog.getExistingDirectory(self, "选择导出文件夹", self._last_import_dir)
            if not folder:
                return
            exp_cfg.output_dir = folder
            self._out_dir_edit.setText(folder)

        dlg = QDialog(self)
        dlg.setWindowTitle("正在导出创作模式图片")
        dlg.setModal(True)
        dlg.setFixedWidth(460)
        dl = QVBoxLayout(dlg)
        dl.setContentsMargins(16, 14, 16, 14)
        dl.setSpacing(10)
        lbl = QLabel(f"正在高分辨率渲染 {len(targets)} 张图片到：\n{exp_cfg.output_dir}")
        lbl.setWordWrap(True)
        dl.addWidget(lbl)
        status_lbl = QLabel("初始化中...")
        status_lbl.setObjectName("MutedLabel")
        dl.addWidget(status_lbl)
        pbar = QProgressBar()
        pbar.setRange(0, len(targets))
        dl.addWidget(pbar)

        result_box: list[tuple[int, int, list, bool]] = []
        worker = CreativeBatchExportThread(
            targets,
            self.library_store.asset_map(),
            exp_cfg,
            parent=dlg,
        )
        worker.progress.connect(lambda done, tot, txt: (pbar.setRange(0, max(1, tot)), pbar.setValue(done), status_lbl.setText(txt)))
        worker.finished_summary.connect(lambda s, f, e, c: (result_box.append((s, f, e, c)), dlg.accept()))
        worker.start()
        dlg.exec()
        worker.wait(5000)

        if result_box:
            s, f, errors, cancelled = result_box[0]
            if not cancelled:
                if f == 0:
                    QMessageBox.information(self, "导出完成", f"已成功导出 {s} 张高清创作水印图片到：\n{exp_cfg.output_dir}")
                else:
                    err_txt = "\n".join(f"- {fn}: {msg}" for fn, msg in errors[:5])
                    QMessageBox.warning(self, "部分导出失败", f"成功 {s} 张，失败 {f} 张：\n{err_txt}")
                self.status_message.emit(f"创作模式：已导出 {s} 张图片到 {exp_cfg.output_dir}")
