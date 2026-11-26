"""Multi-media real-time preview gallery with landscape/portrait isolation and video lightbox."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..engine import apply_watermark, load_image_oriented
from ..models import ImageItem, OrientationGroup, WatermarkConfig
from ..video_engine import extract_video_frame
from ..workers import pil_rgba_to_qimage


class CheckerboardImageCanvas(QWidget):
    """Paints an image or video frame scaled cleanly inside a dark checkerboard backdrop."""

    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._status_text: str = "加载中..."
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_qimage(self, qimg: QImage) -> None:
        self._pixmap = QPixmap.fromImage(qimg)
        self._status_text = ""
        self.update()

    def set_status_text(self, text: str) -> None:
        self._status_text = text
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect()
        tile = 12
        c1 = QColor("#181B22")
        c2 = QColor("#20242E")
        painter.fillRect(rect, c1)
        for y in range(0, rect.height(), tile):
            row_odd = (y // tile) % 2
            for x in range(0, rect.width(), tile):
                if ((x // tile) + row_odd) % 2 == 1:
                    painter.fillRect(x, y, tile, tile, c2)

        if self._pixmap and not self._pixmap.isNull():
            pad = 6
            avail_w = max(1, rect.width() - pad * 2)
            avail_h = max(1, rect.height() - pad * 2)
            scaled = self._pixmap.scaled(
                QSize(avail_w, avail_h),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        elif self._status_text:
            painter.setPen(QColor("#9CA3AF"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._status_text)

        painter.end()


class PreviewCard(QFrame):
    """Single image or video card in the multi-media preview grid."""

    remove_requested = Signal(str)
    inspect_requested = Signal(str)
    selected_changed = Signal(str)

    def __init__(self, item: ImageItem, card_width: int = 250, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item_id = item.id
        self._item = item
        self.setObjectName("PreviewCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 8)
        root.setSpacing(6)

        self._canvas = CheckerboardImageCanvas(self)
        self._canvas.double_clicked.connect(lambda: self.inspect_requested.emit(self.item_id))
        root.addWidget(self._canvas, 1)

        # Video badge pill (top-left)
        self._video_badge = QLabel("", self._canvas)
        self._video_badge.setObjectName("VideoBadge")
        self._video_badge.setVisible(item.is_video)
        if item.is_video:
            self._video_badge.setText("▶ 视频")
            self._video_badge.adjustSize()

        # Floating top-right overlay buttons
        self._btn_zoom = QPushButton("🔍", self._canvas)
        self._btn_zoom.setObjectName("CardActionBtn")
        self._btn_zoom.setFixedSize(26, 26)
        self._btn_zoom.setToolTip("高清大图预览（视频支持进度帧预览）")
        self._btn_zoom.clicked.connect(lambda: self.inspect_requested.emit(self.item_id))

        self._btn_remove = QPushButton("✕", self._canvas)
        self._btn_remove.setObjectName("CardRemoveBtn")
        self._btn_remove.setFixedSize(26, 26)
        self._btn_remove.setToolTip("从列表中移除")
        self._btn_remove.clicked.connect(lambda: self.remove_requested.emit(self.item_id))

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        footer.setSpacing(6)

        self._name_label = QLabel(item.filename)
        self._name_label.setToolTip(str(item.path))
        self._name_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #E5E7EB;")
        self._name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self._name_label, 1)

        self._meta_label = QLabel(item.resolution_text)
        self._meta_label.setObjectName("MutedLabel")
        footer.addWidget(self._meta_label)

        root.addLayout(footer)
        self.set_card_size(card_width)
        self._canvas.installEventFilter(self)

    @property
    def orientation(self) -> OrientationGroup:
        return self._item.orientation

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if watched is self._canvas and event.type() == QEvent.Type.Resize:
            self._position_overlay_buttons()
        return super().eventFilter(watched, event)

    def _position_overlay_buttons(self) -> None:
        w = self._canvas.width()
        margin = 6
        self._btn_remove.move(max(margin, w - 26 - margin), margin)
        self._btn_zoom.move(max(margin, w - 58 - margin), margin)
        self._video_badge.move(margin, margin)

    def set_card_size(self, width: int) -> None:
        height = int(round(width * 0.78)) + 34
        self.setFixedSize(width, height)
        self._position_overlay_buttons()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_metadata(self, item: ImageItem) -> None:
        self._item = item
        self._name_label.setText(item.filename)
        orient_label = "竖版" if item.orientation == OrientationGroup.PORTRAIT else "横版"
        kind_label = f"视频 · {item.duration_text}" if item.is_video else "图片"
        self._name_label.setToolTip(
            f"{item.path}\n{kind_label} · {orient_label} · {item.resolution_text}  {item.file_size_text}"
        )
        self._meta_label.setText(item.resolution_text)
        if item.is_video:
            self._video_badge.setText(f"▶ {item.duration_text}")
            self._video_badge.setVisible(True)
            self._video_badge.adjustSize()
        else:
            self._video_badge.setVisible(False)
        if item.load_error:
            self._canvas.set_status_text(f"读取失败\n{item.load_error[:36]}")
        self._position_overlay_buttons()

    def set_preview_qimage(self, qimg: QImage) -> None:
        self._canvas.set_qimage(qimg)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected_changed.emit(self.item_id)
        super().mousePressEvent(event)


class PreviewGalleryWidget(QFrame):
    """Scrollable multi-media preview grid supporting optional Landscape/Portrait isolation."""

    files_dropped = Signal(list)  # list[Path]
    add_files_clicked = Signal()
    add_folder_clicked = Signal()
    remove_item_requested = Signal(str)
    inspect_item_requested = Signal(str)
    viewport_scrolled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GalleryContainer")
        self.setAcceptDrops(True)

        self._card_width = 250
        self._ordered_ids: list[str] = []
        self._cards: dict[str, PreviewCard] = {}
        self._selected_id: str | None = None
        self._last_cols = 0
        self._orientation_isolated = False
        self._view_scope = "both"  # "both" | "landscape" | "portrait"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Orientation Isolation Scope Bar (shown only when isolated & non-empty) ----
        self._filter_bar = QFrame()
        self._filter_bar.setObjectName("GalleryFilterBar")
        self._filter_bar.setVisible(False)
        fb = QHBoxLayout(self._filter_bar)
        fb.setContentsMargins(16, 7, 16, 7)
        fb.setSpacing(8)

        lbl_iso = QLabel("横竖隔离视图：")
        lbl_iso.setStyleSheet("font-size: 12px; font-weight: 600; color: #93C5FD;")
        fb.addWidget(lbl_iso)

        self._scope_group = QButtonGroup(self)
        self._scope_group.setExclusive(True)

        self._btn_scope_both = QPushButton("分组并列显示")
        self._btn_scope_both.setCheckable(True)
        self._btn_scope_both.setChecked(True)
        self._btn_scope_both.setObjectName("PillBtn")
        self._btn_scope_both.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_scope_land = QPushButton("仅看横版 (0)")
        self._btn_scope_land.setCheckable(True)
        self._btn_scope_land.setObjectName("PillBtn")
        self._btn_scope_land.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_scope_port = QPushButton("仅看竖版 (0)")
        self._btn_scope_port.setCheckable(True)
        self._btn_scope_port.setObjectName("PillBtn")
        self._btn_scope_port.setCursor(Qt.CursorShape.PointingHandCursor)

        for btn, scope in (
            (self._btn_scope_both, "both"),
            (self._btn_scope_land, "landscape"),
            (self._btn_scope_port, "portrait"),
        ):
            self._scope_group.addButton(btn)
            btn.clicked.connect(lambda _c=False, s=scope: self._set_view_scope(s))
            fb.addWidget(btn)

        fb.addStretch(1)
        self._iso_export_tip = QLabel("导出时将自动分别保存到「横版」与「竖版」子文件夹")
        self._iso_export_tip.setObjectName("MutedLabel")
        fb.addWidget(self._iso_export_tip)
        root.addWidget(self._filter_bar)

        self._stack = QStackedWidget(self)
        root.addWidget(self._stack, 1)

        # ---- Page 0: Empty drop zone ----
        empty_wrapper = QWidget()
        empty_layout = QVBoxLayout(empty_wrapper)
        empty_layout.setContentsMargins(32, 32, 32, 32)

        self._drop_zone = QFrame()
        self._drop_zone.setObjectName("DropZone")
        self._drop_zone.setProperty("dragOver", False)
        dz_layout = QVBoxLayout(self._drop_zone)
        dz_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz_layout.setSpacing(14)

        icon_lbl = QLabel("🖼️  🎬")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 42px; background: transparent;")
        dz_layout.addWidget(icon_lbl)

        title_lbl = QLabel("拖拽多张图片、视频或整个文件夹到此处")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #F3F4F6; background: transparent;")
        dz_layout.addWidget(title_lbl)

        sub_lbl = QLabel("图片支持 JPG / PNG / WebP / BMP / TIFF  ·  视频支持 MP4 / MOV / MKV / AVI / WebM")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setStyleSheet("font-size: 13px; color: #9CA3AF; background: transparent;")
        dz_layout.addWidget(sub_lbl)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.setSpacing(12)

        btn_files = QPushButton("＋ 选择图片 / 视频")
        btn_files.setObjectName("PrimaryButton")
        btn_files.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_files.clicked.connect(self.add_files_clicked.emit)
        btn_row.addWidget(btn_files)

        btn_folder = QPushButton("📂 选择文件夹")
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.setStyleSheet("padding: 8px 16px;")
        btn_folder.clicked.connect(self.add_folder_clicked.emit)
        btn_row.addWidget(btn_folder)

        dz_layout.addLayout(btn_row)
        empty_layout.addWidget(self._drop_zone, 1)
        self._stack.addWidget(empty_wrapper)

        # ---- Page 1: Scrollable gallery (supports unified & isolated grouped sections) ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport_scrolled.emit())

        self._grid_host = QWidget()
        self._grid_host.setObjectName("GridHost")
        self._grid_outer = QVBoxLayout(self._grid_host)
        self._grid_outer.setContentsMargins(16, 16, 16, 16)
        self._grid_outer.setSpacing(14)

        # Primary section (used for ALL cards in unified mode, and LANDSCAPE cards in isolated mode)
        self._primary_section = QWidget()
        ps_layout = QVBoxLayout(self._primary_section)
        ps_layout.setContentsMargins(0, 0, 0, 0)
        ps_layout.setSpacing(10)

        self._land_header = self._make_group_header("横版媒体区（宽 ≥ 高）", "0 项")
        self._land_header.setVisible(False)
        ps_layout.addWidget(self._land_header)

        self._land_empty_lbl = QLabel("暂无横版图片或视频")
        self._land_empty_lbl.setObjectName("MutedLabel")
        self._land_empty_lbl.setContentsMargins(6, 4, 0, 8)
        self._land_empty_lbl.setVisible(False)
        ps_layout.addWidget(self._land_empty_lbl)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        ps_layout.addLayout(self._grid)
        self._grid_outer.addWidget(self._primary_section)

        # Portrait section (shown only in orientation-isolated mode)
        self._portrait_section = QWidget()
        self._portrait_section.setVisible(False)
        pt_layout = QVBoxLayout(self._portrait_section)
        pt_layout.setContentsMargins(0, 6, 0, 0)
        pt_layout.setSpacing(10)

        self._port_header = self._make_group_header("竖版媒体区（高 > 宽）", "0 项")
        pt_layout.addWidget(self._port_header)

        self._port_empty_lbl = QLabel("暂无竖版图片或视频")
        self._port_empty_lbl.setObjectName("MutedLabel")
        self._port_empty_lbl.setContentsMargins(6, 4, 0, 8)
        self._port_empty_lbl.setVisible(False)
        pt_layout.addWidget(self._port_empty_lbl)

        self._portrait_grid = QGridLayout()
        self._portrait_grid.setContentsMargins(0, 0, 0, 0)
        self._portrait_grid.setHorizontalSpacing(14)
        self._portrait_grid.setVerticalSpacing(14)
        self._portrait_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        pt_layout.addLayout(self._portrait_grid)
        self._grid_outer.addWidget(self._portrait_section)

        self._grid_outer.addStretch(1)

        self._scroll.setWidget(self._grid_host)
        self._stack.addWidget(self._scroll)
        self._stack.setCurrentIndex(0)

    def _make_group_header(self, title: str, badge_text: str) -> QFrame:
        bar = QFrame()
        bar.setObjectName("GroupHeaderBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 7, 12, 7)
        lay.setSpacing(8)

        lbl = QLabel(title)
        lbl.setObjectName("GroupHeaderTitle")
        lay.addWidget(lbl)

        badge = QLabel(badge_text)
        badge.setObjectName("GroupCountBadge")
        lay.addWidget(badge)
        lay.addStretch(1)

        bar._count_badge = badge  # type: ignore[attr-defined]
        return bar

    def set_orientation_isolated(self, enabled: bool) -> None:
        if self._orientation_isolated == enabled:
            return
        self._orientation_isolated = enabled
        self._filter_bar.setVisible(enabled and bool(self._ordered_ids))
        self._reflow_grid(force=True)

    def _set_view_scope(self, scope: str) -> None:
        self._view_scope = scope
        self._reflow_grid(force=True)

    def add_item(self, item: ImageItem) -> PreviewCard:
        card = PreviewCard(item, card_width=self._card_width, parent=self._grid_host)
        card.remove_requested.connect(self.remove_item_requested.emit)
        card.inspect_requested.connect(self.inspect_item_requested.emit)
        card.selected_changed.connect(self._on_card_selected)

        self._ordered_ids.append(item.id)
        self._cards[item.id] = card
        self._stack.setCurrentIndex(1)
        self._filter_bar.setVisible(self._orientation_isolated)
        self._reflow_grid(force=True)
        return card

    def remove_item(self, item_id: str) -> None:
        card = self._cards.pop(item_id, None)
        if card is not None:
            self._ordered_ids = [i for i in self._ordered_ids if i != item_id]
            self._grid.removeWidget(card)
            self._portrait_grid.removeWidget(card)
            card.deleteLater()
        if self._selected_id == item_id:
            self._selected_id = None
        if not self._ordered_ids:
            self._stack.setCurrentIndex(0)
            self._filter_bar.setVisible(False)
        else:
            self._reflow_grid(force=True)

    def clear_all(self) -> None:
        for card in self._cards.values():
            self._grid.removeWidget(card)
            self._portrait_grid.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._ordered_ids.clear()
        self._selected_id = None
        self._stack.setCurrentIndex(0)
        self._filter_bar.setVisible(False)

    def update_item_metadata(self, item: ImageItem) -> None:
        card = self._cards.get(item.id)
        if card is not None:
            prev_orient = card.orientation
            card.update_metadata(item)
            if self._orientation_isolated and card.orientation != prev_orient:
                self._reflow_grid(force=True)
            elif self._orientation_isolated:
                self._update_group_counts()

    def update_item_preview(self, item_id: str, qimg: QImage) -> None:
        card = self._cards.get(item_id)
        if card is not None:
            card.set_preview_qimage(qimg)

    def set_card_width(self, width: int) -> None:
        clamped = max(160, min(420, int(width)))
        if clamped == self._card_width:
            return
        self._card_width = clamped
        for card in self._cards.values():
            card.set_card_size(clamped)
        self._reflow_grid(force=True)

    def _on_card_selected(self, item_id: str) -> None:
        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(False)
        self._selected_id = item_id
        if item_id in self._cards:
            self._cards[item_id].set_selected(True)

    def _compute_columns(self) -> int:
        viewport_w = self._scroll.viewport().width() - 32
        if viewport_w <= 0:
            return 3
        spacing = self._grid.horizontalSpacing()
        return max(1, (viewport_w + spacing) // (self._card_width + spacing))

    def _clear_layout_only(self, grid: QGridLayout) -> None:
        while grid.count():
            grid.takeAt(0)

    def _update_group_counts(self) -> tuple[list[str], list[str]]:
        land_ids = [
            iid for iid in self._ordered_ids
            if iid in self._cards and self._cards[iid].orientation == OrientationGroup.LANDSCAPE
        ]
        port_ids = [
            iid for iid in self._ordered_ids
            if iid in self._cards and self._cards[iid].orientation == OrientationGroup.PORTRAIT
        ]
        self._land_header._count_badge.setText(f"{len(land_ids)} 项")  # type: ignore[attr-defined]
        self._port_header._count_badge.setText(f"{len(port_ids)} 项")  # type: ignore[attr-defined]
        self._btn_scope_land.setText(f"仅看横版 ({len(land_ids)})")
        self._btn_scope_port.setText(f"仅看竖版 ({len(port_ids)})")
        return land_ids, port_ids

    def _reflow_grid(self, force: bool = False) -> None:
        if not self._ordered_ids:
            return
        cols = self._compute_columns()
        if not force and cols == self._last_cols:
            return
        self._last_cols = cols

        self._clear_layout_only(self._grid)
        self._clear_layout_only(self._portrait_grid)

        if not self._orientation_isolated:
            self._land_header.setVisible(False)
            self._land_empty_lbl.setVisible(False)
            self._primary_section.setVisible(True)
            self._portrait_section.setVisible(False)

            for idx, item_id in enumerate(self._ordered_ids):
                card = self._cards.get(item_id)
                if card is None:
                    continue
                card.setVisible(True)
                self._grid.addWidget(card, idx // cols, idx % cols)
            return

        # Orientation-isolated grouped display
        land_ids, port_ids = self._update_group_counts()
        show_land = self._view_scope in ("both", "landscape")
        show_port = self._view_scope in ("both", "portrait")

        self._primary_section.setVisible(show_land)
        self._land_header.setVisible(show_land)
        self._land_empty_lbl.setVisible(show_land and len(land_ids) == 0)

        self._portrait_section.setVisible(show_port)
        self._port_empty_lbl.setVisible(show_port and len(port_ids) == 0)

        for idx, item_id in enumerate(land_ids):
            card = self._cards[item_id]
            card.setVisible(show_land)
            if show_land:
                self._grid.addWidget(card, idx // cols, idx % cols)

        for idx, item_id in enumerate(port_ids):
            card = self._cards[item_id]
            card.setVisible(show_port)
            if show_port:
                self._portrait_grid.addWidget(card, idx // cols, idx % cols)

    def get_visible_item_ids(self) -> list[str]:
        """Return IDs of cards currently intersecting the scroll viewport (plus small margin)."""
        if not self._ordered_ids or self._stack.currentIndex() != 1:
            return []
        vp = self._scroll.viewport()
        vp_rect = QRect(0, -200, vp.width(), vp.height() + 400)

        visible: list[str] = []
        for item_id in self._ordered_ids:
            card = self._cards.get(item_id)
            if card is None or not card.isVisible():
                continue
            top_left = card.mapTo(vp, card.rect().topLeft())
            card_rect_in_vp = QRect(top_left, card.size())
            if card_rect_in_vp.intersects(vp_rect):
                visible.append(item_id)
        return visible

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_grid(force=False)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_highlight(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drag_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drag_highlight(False)
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def _set_drag_highlight(self, active: bool) -> None:
        self._drop_zone.setProperty("dragOver", active)
        self._drop_zone.style().unpolish(self._drop_zone)
        self._drop_zone.style().polish(self._drop_zone)


class LightboxPreviewDialog(QDialog):
    """High-resolution single-item inspection modal with prev/next & video timestamp scrubber."""

    def __init__(
        self,
        items: list[ImageItem],
        start_index: int,
        get_config_for_item: Callable[[ImageItem], WatermarkConfig],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items = items
        self._index = max(0, min(start_index, len(items) - 1))
        self._get_config_for_item = get_config_for_item
        self._video_timestamp: float | None = None

        self.setWindowTitle("高清实时预览")
        self.resize(1000, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        top_bar = QHBoxLayout()
        self._info_label = QLabel()
        self._info_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        top_bar.addWidget(self._info_label, 1)

        self._btn_prev = QPushButton("◀ 上一项")
        self._btn_prev.clicked.connect(self._go_prev)
        top_bar.addWidget(self._btn_prev)

        self._btn_next = QPushButton("下一项 ▶")
        self._btn_next.clicked.connect(self._go_next)
        top_bar.addWidget(self._btn_next)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        top_bar.addWidget(btn_close)
        layout.addLayout(top_bar)

        self._canvas = CheckerboardImageCanvas(self)
        layout.addWidget(self._canvas, 1)

        # Video frame timestamp scrubber (shown only for video items)
        self._video_bar = QFrame()
        self._video_bar.setObjectName("SectionCard")
        vb = QHBoxLayout(self._video_bar)
        vb.setContentsMargins(12, 8, 12, 8)
        vb.setSpacing(8)

        vb_lbl = QLabel("视频预览帧位置")
        vb_lbl.setObjectName("MutedLabel")
        vb.addWidget(vb_lbl)

        self._time_slider = QSlider(Qt.Orientation.Horizontal)
        self._time_slider.setRange(0, 100)
        self._time_slider.setValue(0)
        self._time_slider.sliderReleased.connect(self._on_scrub_released)
        vb.addWidget(self._time_slider, 1)

        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setObjectName("MutedLabel")
        self._time_label.setFixedWidth(92)
        vb.addWidget(self._time_label)

        for pct, label in ((0, "开头"), (25, "25%"), (50, "50%"), (75, "75%")):
            pill = QPushButton(label)
            pill.setObjectName("PillBtn")
            pill.clicked.connect(lambda _c=False, p=pct: self._jump_percent(p))
            vb.addWidget(pill)

        self._video_bar.setVisible(False)
        layout.addWidget(self._video_bar)

        self._render_current()

    def _go_prev(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._video_timestamp = None
            self._render_current()

    def _go_next(self) -> None:
        if self._index < len(self._items) - 1:
            self._index += 1
            self._video_timestamp = None
            self._render_current()

    def _jump_percent(self, pct: int) -> None:
        item = self._items[self._index]
        if not item.is_video:
            return
        self._time_slider.setValue(pct)
        self._video_timestamp = max(0.0, item.duration_sec * (pct / 100.0))
        self._render_current()

    def _on_scrub_released(self) -> None:
        item = self._items[self._index]
        if not item.is_video:
            return
        pct = self._time_slider.value()
        self._video_timestamp = max(0.0, item.duration_sec * (pct / 100.0))
        self._render_current()

    @staticmethod
    def _fmt_sec(sec: float) -> str:
        s = max(0, int(round(sec)))
        m, s = divmod(s, 60)
        return f"{m:02d}:{s:02d}"

    def _render_current(self) -> None:
        item = self._items[self._index]
        orient_txt = "竖版" if item.orientation == OrientationGroup.PORTRAIT else "横版"
        kind_txt = f"视频 ({item.duration_text})" if item.is_video else "图片"
        self._info_label.setText(
            f"[{self._index + 1}/{len(self._items)}]  {item.filename}  ·  {kind_txt} · {orient_txt} · {item.resolution_text}"
        )
        self._btn_prev.setEnabled(self._index > 0)
        self._btn_next.setEnabled(self._index < len(self._items) - 1)
        self._video_bar.setVisible(item.is_video)

        cfg = self._get_config_for_item(item)
        try:
            if item.is_video:
                ts = self._video_timestamp if self._video_timestamp is not None else min(0.5, item.duration_sec * 0.1)
                frame, orig_w, orig_h, dur = extract_video_frame(item.path, timestamp_sec=ts, max_edge=1440)
                total_dur = max(dur, item.duration_sec)
                pct = int(round((ts / total_dur) * 100)) if total_dur > 0 else 0
                self._time_slider.blockSignals(True)
                self._time_slider.setValue(max(0, min(100, pct)))
                self._time_slider.blockSignals(False)
                self._time_label.setText(f"{self._fmt_sec(ts)} / {self._fmt_sec(total_dur)}")
                watermarked = apply_watermark(frame, cfg, reference_size=(orig_w, orig_h))
            else:
                img, _, _ = load_image_oriented(item.path)
                orig_size = img.size
                max_edge = 1600
                if max(orig_size) > max_edge:
                    scale = max_edge / max(orig_size)
                    img = img.resize(
                        (max(1, int(round(orig_size[0] * scale))), max(1, int(round(orig_size[1] * scale)))),
                    )
                watermarked = apply_watermark(img, cfg, reference_size=orig_size)
            self._canvas.set_qimage(pil_rgba_to_qimage(watermarked))
        except Exception as exc:  # noqa: BLE001
            self._canvas.set_status_text(f"无法渲染高清预览: {exc}")
