"""Interactive direct-manipulation canvas for Creative Mode (drag, resize, rotate, drop)."""

from __future__ import annotations

from collections import OrderedDict
import math
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QWidget

from ..creative_engine import render_asset_stamp
from ..creative_models import CreativeAsset, CreativePlacement
from ..i18n import t

MIME_CREATIVE_ASSET = "application/x-bw-creative-asset"


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgba = img if img.mode == "RGBA" else img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class CreativeCanvasWidget(QWidget):
    """Interactive WYSIWYG stage supporting drag-move, corner resize, top-handle rotate, and drops."""

    selection_changed = Signal(str)  # selected layer_id or ""
    layer_changed = Signal(str)      # live change during drag/resize/rotate
    layer_committed = Signal(str)    # mouse released -> snapshot for Undo
    asset_dropped = Signal(str, float, float)  # asset_id, norm_x, norm_y
    files_dropped = Signal(list)     # list[Path]
    delete_requested = Signal(str)   # layer_id
    duplicate_requested = Signal(str)
    undo_requested = Signal()
    redo_requested = Signal()
    add_images_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(360, 320)

        self._base_pixmap: QPixmap | None = None
        self._orig_size: tuple[int, int] = (0, 0)
        self._placements: list[CreativePlacement] = []
        self._assets_by_id: dict[str, CreativeAsset] = {}
        self._selected_id: str = ""

        # Stamp pixmap LRU cache: key -> (QPixmap, base_w, base_h)
        self._stamp_cache: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._max_cache = 140

        # Active interaction state
        self._drag_mode: str = ""  # "" | "move" | "resize" | "rotate"
        self._drag_start_pos: QPointF = QPointF()
        self._drag_orig_x: float = 0.5
        self._drag_orig_y: float = 0.5
        self._drag_orig_scale: float = 0.14
        self._drag_orig_rot: float = 0.0
        self._drag_start_dist: float = 1.0
        self._drag_start_angle: float = 0.0
        self._snap_v: bool = False
        self._snap_h: bool = False
        self._drag_over_drop: bool = False

    # ---- Public API ----

    def set_scene(
        self,
        base_image: Image.Image | None,
        orig_size: tuple[int, int],
        placements: list[CreativePlacement],
        assets_by_id: dict[str, CreativeAsset],
        selected_id: str = "",
    ) -> None:
        self._base_pixmap = pil_to_qpixmap(base_image) if base_image is not None else None
        self._orig_size = orig_size
        self._placements = placements
        self._assets_by_id = assets_by_id
        self._selected_id = selected_id if any(p.id == selected_id for p in placements) else ""
        self.update()

    def set_placements(self, placements: list[CreativePlacement], selected_id: str | None = None) -> None:
        self._placements = placements
        if selected_id is not None:
            self._selected_id = selected_id if any(p.id == selected_id for p in placements) else ""
        elif self._selected_id and not any(p.id == self._selected_id for p in placements):
            self._selected_id = ""
        self.update()

    def set_assets(self, assets_by_id: dict[str, CreativeAsset]) -> None:
        self._assets_by_id = assets_by_id
        self._stamp_cache.clear()
        self.update()

    def select_layer(self, layer_id: str) -> None:
        if layer_id and any(p.id == layer_id for p in self._placements):
            self._selected_id = layer_id
        else:
            self._selected_id = ""
        self.update()

    @property
    def selected_id(self) -> str:
        return self._selected_id

    # ---- Coordinate & Geometry Helpers ----

    def _image_rect(self) -> QRectF:
        if self._base_pixmap is None or self._base_pixmap.isNull():
            return QRectF()
        pad = 22.0
        avail_w = max(40.0, self.width() - pad * 2)
        avail_h = max(40.0, self.height() - pad * 2)
        pw = float(self._base_pixmap.width())
        ph = float(self._base_pixmap.height())
        if pw <= 0 or ph <= 0:
            return QRectF()
        fit = min(avail_w / pw, avail_h / ph)
        dw = pw * fit
        dh = ph * fit
        return QRectF((self.width() - dw) / 2.0, (self.height() - dh) / 2.0, dw, dh)

    def _get_stamp_pixmap(self, layer: CreativePlacement, short_edge_px: float) -> QPixmap | None:
        asset = self._assets_by_id.get(layer.asset_id)
        if asset is None:
            return None
        raw_w = max(8, int(round(layer.scale * short_edge_px)))
        # Quantize width to multiples of 4px during interactive scaling for fast smooth caching
        q_w = max(8, ((raw_w + 2) // 4) * 4)
        key = (
            asset.id,
            asset.text if asset.kind == "text" else len(asset.image_data_url),
            asset.color,
            asset.font_name,
            q_w,
            layer.opacity,
            layer.glow_enabled,
        )
        cached = self._stamp_cache.get(key)
        if cached is not None:
            self._stamp_cache.move_to_end(key)
            return cached

        pil_stamp = render_asset_stamp(
            asset,
            q_w,
            opacity=layer.opacity,
            glow_enabled=layer.glow_enabled,
        )
        if pil_stamp is None:
            return None
        pm = pil_to_qpixmap(pil_stamp)
        self._stamp_cache[key] = pm
        if len(self._stamp_cache) > self._max_cache:
            self._stamp_cache.popitem(last=False)
        return pm

    def _layer_geometry(self, layer: CreativePlacement, rect: QRectF) -> tuple[QPointF, float, float] | None:
        short_edge = min(rect.width(), rect.height())
        pm = self._get_stamp_pixmap(layer, short_edge)
        if pm is None or pm.isNull():
            return None
        cx = rect.left() + layer.x * rect.width()
        cy = rect.top() + layer.y * rect.height()
        # Scale displayed size precisely to exact target width (correcting 4px quantization)
        exact_w = max(8.0, layer.scale * short_edge)
        # Note: pm includes glow/stroke padding, so ratio is proportional to exact_w / quantized_w
        q_w = max(8, ((int(round(exact_w)) + 2) // 4) * 4)
        ratio = exact_w / float(q_w)
        return QPointF(cx, cy), pm.width() * ratio, pm.height() * ratio

    def _to_local_point(self, pt: QPointF, center: QPointF, rotation_ccw_deg: float) -> QPointF:
        dx = pt.x() - center.x()
        dy = pt.y() - center.y()
        # Canvas Qt rotation is -rotation_ccw_deg (CW), so inverse rotation is +rotation_ccw_deg
        rad = math.radians(rotation_ccw_deg)
        c, s = math.cos(rad), math.sin(rad)
        return QPointF(dx * c - dy * s, dx * s + dy * c)

    def _from_local_point(self, local: QPointF, center: QPointF, rotation_ccw_deg: float) -> QPointF:
        rad = math.radians(-rotation_ccw_deg)
        c, s = math.cos(rad), math.sin(rad)
        return QPointF(center.x() + local.x() * c - local.y() * s, center.y() + local.x() * s + local.y() * c)

    def _hit_handles(self, pos: QPointF, layer: CreativePlacement, rect: QRectF) -> str:
        geom = self._layer_geometry(layer, rect)
        if geom is None:
            return ""
        center, w, h = geom
        hw, hh = max(14.0, w / 2.0), max(14.0, h / 2.0)

        rot_handle = self._from_local_point(QPointF(0.0, -(hh + 24.0)), center, layer.rotation)
        if math.hypot(pos.x() - rot_handle.x(), pos.y() - rot_handle.y()) <= 11.0:
            return "rotate"

        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                corner = self._from_local_point(QPointF(sx * hw, sy * hh), center, layer.rotation)
                if math.hypot(pos.x() - corner.x(), pos.y() - corner.y()) <= 10.0:
                    return "resize"
        return ""

    def _hit_layer(self, pos: QPointF, rect: QRectF) -> CreativePlacement | None:
        ordered = sorted(self._placements, key=lambda p: p.z_index, reverse=True)
        for layer in ordered:
            geom = self._layer_geometry(layer, rect)
            if geom is None:
                continue
            center, w, h = geom
            local = self._to_local_point(pos, center, layer.rotation)
            hw, hh = max(12.0, w / 2.0 + 4.0), max(12.0, h / 2.0 + 4.0)
            if abs(local.x()) <= hw and abs(local.y()) <= hh:
                return layer
        return None

    # ---- Painting ----

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Stage background
        painter.fillRect(self.rect(), QColor("#12141A"))

        if self._base_pixmap is None or self._base_pixmap.isNull():
            self._paint_empty_state(painter)
            return

        rect = self._image_rect()
        if rect.isEmpty():
            return

        # Subtle checkerboard behind image (for transparent PNGs)
        painter.save()
        painter.setClipRect(rect)
        tile = 12
        c1, c2 = QColor("#1F2430"), QColor("#293040")
        x0, y0 = int(rect.left()), int(rect.top())
        x1, y1 = int(math.ceil(rect.right())), int(math.ceil(rect.bottom()))
        for yy in range(y0, y1, tile):
            for xx in range(x0, x1, tile):
                even = ((xx - x0) // tile + (yy - y0) // tile) % 2 == 0
                painter.fillRect(xx, yy, tile, tile, c1 if even else c2)

        # Base photo
        painter.drawPixmap(rect, self._base_pixmap, QRectF(self._base_pixmap.rect()))

        # Watermark layers sorted by z_index
        short_edge = min(rect.width(), rect.height())
        ordered = sorted(self._placements, key=lambda p: p.z_index)
        for layer in ordered:
            pm = self._get_stamp_pixmap(layer, short_edge)
            if pm is None or pm.isNull():
                continue
            geom = self._layer_geometry(layer, rect)
            if geom is None:
                continue
            center, draw_w, draw_h = geom
            painter.save()
            painter.translate(center)
            painter.rotate(-layer.rotation)
            target = QRectF(-draw_w / 2.0, -draw_h / 2.0, draw_w, draw_h)
            painter.drawPixmap(target, pm, QRectF(pm.rect()))
            painter.restore()

        # Snap center guide lines while moving
        if self._drag_mode == "move":
            guide_pen = QPen(QColor(56, 189, 248, 190), 1.2, Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            if self._snap_v:
                mx = rect.center().x()
                painter.drawLine(QPointF(mx, rect.top()), QPointF(mx, rect.bottom()))
            if self._snap_h:
                my = rect.center().y()
                painter.drawLine(QPointF(rect.left(), my), QPointF(rect.right(), my))

        painter.restore()

        # Crisp border around canvas image
        border_color = QColor("#3B82F6") if self._drag_over_drop else QColor("#323846")
        painter.setPen(QPen(border_color, 2.0 if self._drag_over_drop else 1.0))
        painter.drawRect(rect)

        # Draw selection bounding box + resize/rotate handles (unclipped so handles near edges stay reachable)
        selected = next((p for p in self._placements if p.id == self._selected_id), None)
        if selected is not None:
            geom = self._layer_geometry(selected, rect)
            if geom is not None:
                self._paint_selection_gizmo(painter, selected, *geom)

    def _paint_empty_state(self, painter: QPainter) -> None:
        box = QRectF(
            max(28.0, (self.width() - 460) / 2.0),
            max(28.0, (self.height() - 220) / 2.0),
            min(460.0, self.width() - 56.0),
            min(220.0, self.height() - 56.0),
        )
        pen = QPen(QColor("#3B82F6" if self._drag_over_drop else "#384050"), 2.0, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor("#1B2333" if self._drag_over_drop else "#1A1D24"))
        painter.drawRoundedRect(box, 14, 14)

        painter.setPen(QColor("#F3F4F6"))
        f = painter.font()
        f.setPointSize(13)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(
            box.adjusted(18, 36, -18, -90),
            Qt.AlignmentFlag.AlignCenter,
            t("✨ 创作模式画布 · 点击或拖入图片开始"),
        )

        painter.setPen(QColor("#9CA3AF"))
        f.setPointSize(10)
        f.setBold(False)
        painter.setFont(f)
        painter.drawText(
            box.adjusted(24, 96, -24, -24),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            t("导入图片后，可一键运行「算法智能美观排版」\n或直接从左侧水印库拖入贴纸与文字，自由拖拽、缩放、旋转！"),
        )

    def _paint_selection_gizmo(
        self,
        painter: QPainter,
        layer: CreativePlacement,
        center: QPointF,
        w: float,
        h: float,
    ) -> None:
        hw, hh = max(14.0, w / 2.0), max(14.0, h / 2.0)
        painter.save()
        painter.translate(center)
        painter.rotate(-layer.rotation)

        accent = QColor("#F59E0B") if layer.locked else QColor("#38BDF8")
        painter.setPen(QPen(accent, 1.5, Qt.PenStyle.SolidLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(-hw, -hh, hw * 2.0, hh * 2.0))

        # Rotation stem + handle
        painter.drawLine(QPointF(0.0, -hh), QPointF(0.0, -(hh + 24.0)))
        painter.setBrush(QBrush(QColor("#0F172A")))
        painter.setPen(QPen(accent, 2.0))
        painter.drawEllipse(QPointF(0.0, -(hh + 24.0)), 6.5, 6.5)

        # 4 corner resize handles
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.setPen(QPen(accent, 2.0))
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                painter.drawEllipse(QPointF(sx * hw, sy * hh), 5.5, 5.5)

        painter.restore()

        # Subtle HUD readout while actively dragging
        if self._drag_mode:
            hud_raw = (
                f"角度 {layer.rotation:.1f}°"
                if self._drag_mode == "rotate"
                else (
                    f"比例 {layer.scale * 100:.1f}%"
                    if self._drag_mode == "resize"
                    else f"位置 ({layer.x * 100:.0f}%, {layer.y * 100:.0f}%)"
                )
            )
            hud_text = t(hud_raw)
            badge = QRectF(center.x() - 56, center.y() + hh + 12, 112, 22)
            painter.setPen(QPen(QColor("#38BDF8"), 1.0))
            painter.setBrush(QColor(15, 23, 42, 220))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor("#F8FAFC"))
            f = painter.font()
            f.setPointSize(9)
            painter.setFont(f)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, hud_text)

    # ---- Mouse Events ----

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        if self._base_pixmap is None:
            self.add_images_clicked.emit()
            return

        rect = self._image_rect()
        pos = event.position()

        # Check handles of currently selected layer first
        cur_selected = next((p for p in self._placements if p.id == self._selected_id), None)
        if cur_selected is not None:
            handle = self._hit_handles(pos, cur_selected, rect)
            if handle:
                self._start_drag(handle, cur_selected, pos, rect)
                return

        hit = self._hit_layer(pos, rect)
        if hit is not None:
            if hit.id != self._selected_id:
                self._selected_id = hit.id
                self.selection_changed.emit(hit.id)
            self._start_drag("move", hit, pos, rect)
            self.update()
            return

        if self._selected_id:
            self._selected_id = ""
            self.selection_changed.emit("")
            self.update()

    def _start_drag(self, mode: str, layer: CreativePlacement, pos: QPointF, rect: QRectF) -> None:
        self._drag_mode = mode
        self._drag_start_pos = pos
        self._drag_orig_x = layer.x
        self._drag_orig_y = layer.y
        self._drag_orig_scale = layer.scale
        self._drag_orig_rot = layer.rotation
        center = QPointF(rect.left() + layer.x * rect.width(), rect.top() + layer.y * rect.height())
        self._drag_start_dist = max(8.0, math.hypot(pos.x() - center.x(), pos.y() - center.y()))
        self._drag_start_angle = math.degrees(math.atan2(pos.y() - center.y(), pos.x() - center.x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        rect = self._image_rect()
        pos = event.position()
        if rect.isEmpty():
            return

        if not self._drag_mode:
            # Update hover cursor hints
            cur_selected = next((p for p in self._placements if p.id == self._selected_id), None)
            if cur_selected is not None:
                h = self._hit_handles(pos, cur_selected, rect)
                if h == "rotate":
                    self.setCursor(Qt.CursorShape.CrossCursor)
                    return
                if h == "resize":
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                    return
            hit = self._hit_layer(pos, rect)
            self.setCursor(Qt.CursorShape.OpenHandCursor if hit else Qt.CursorShape.ArrowCursor)
            return

        layer = next((p for p in self._placements if p.id == self._selected_id), None)
        if layer is None:
            return

        self._snap_v = False
        self._snap_h = False

        if self._drag_mode == "move":
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            dx = (pos.x() - self._drag_start_pos.x()) / max(1.0, rect.width())
            dy = (pos.y() - self._drag_start_pos.y()) / max(1.0, rect.height())
            nx = max(-0.08, min(1.08, self._drag_orig_x + dx))
            ny = max(-0.08, min(1.08, self._drag_orig_y + dy))
            if abs(nx - 0.5) < 0.012:
                nx = 0.5
                self._snap_v = True
            if abs(ny - 0.5) < 0.012:
                ny = 0.5
                self._snap_h = True
            layer.x = round(nx, 5)
            layer.y = round(ny, 5)
        elif self._drag_mode == "resize":
            center = QPointF(rect.left() + layer.x * rect.width(), rect.top() + layer.y * rect.height())
            dist = max(6.0, math.hypot(pos.x() - center.x(), pos.y() - center.y()))
            ratio = dist / max(8.0, self._drag_start_dist)
            layer.scale = round(max(0.025, min(0.85, self._drag_orig_scale * ratio)), 5)
        elif self._drag_mode == "rotate":
            center = QPointF(rect.left() + layer.x * rect.width(), rect.top() + layer.y * rect.height())
            cur_angle = math.degrees(math.atan2(pos.y() - center.y(), pos.x() - center.x()))
            delta_cw = cur_angle - self._drag_start_angle
            # Convert CW delta to CCW rotation field
            new_rot = self._drag_orig_rot - delta_cw
            while new_rot > 180.0:
                new_rot -= 360.0
            while new_rot < -180.0:
                new_rot += 360.0
            # Gentle snap to 0°, ±45°, ±90°
            for snap_a in (-90.0, -45.0, 0.0, 45.0, 90.0):
                if abs(new_rot - snap_a) < 2.2:
                    new_rot = snap_a
                    break
            layer.rotation = round(new_rot, 2)

        self.layer_changed.emit(layer.id)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            lid = self._selected_id
            self._drag_mode = ""
            self._snap_v = False
            self._snap_h = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
            if lid:
                self.layer_committed.emit(lid)

    # ---- Keyboard Shortcuts ----

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()

        if mods & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self.redo_requested.emit()
                else:
                    self.undo_requested.emit()
                return
            if key == Qt.Key.Key_Y:
                self.redo_requested.emit()
                return
            if key == Qt.Key.Key_D and self._selected_id:
                self.duplicate_requested.emit(self._selected_id)
                return

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._selected_id:
            self.delete_requested.emit(self._selected_id)
            return

        if self._selected_id and key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            layer = next((p for p in self._placements if p.id == self._selected_id), None)
            if layer is not None:
                step = 0.02 if (mods & Qt.KeyboardModifier.ShiftModifier) else 0.005
                if key == Qt.Key.Key_Left:
                    layer.x = round(max(-0.08, layer.x - step), 5)
                elif key == Qt.Key.Key_Right:
                    layer.x = round(min(1.08, layer.x + step), 5)
                elif key == Qt.Key.Key_Up:
                    layer.y = round(max(-0.08, layer.y - step), 5)
                elif key == Qt.Key.Key_Down:
                    layer.y = round(min(1.08, layer.y + step), 5)
                self.layer_changed.emit(layer.id)
                self.layer_committed.emit(layer.id)
                self.update()
                return

        super().keyPressEvent(event)

    # ---- Drag & Drop (Library Asset OR Image Files) ----

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        md = event.mimeData()
        if md.hasFormat(MIME_CREATIVE_ASSET) or md.hasUrls():
            self._drag_over_drop = True
            event.acceptProposedAction()
            self.update()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        del event
        self._drag_over_drop = False
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._drag_over_drop = False
        md = event.mimeData()
        if md.hasFormat(MIME_CREATIVE_ASSET):
            asset_id = bytes(md.data(MIME_CREATIVE_ASSET)).decode("utf-8", "ignore").strip()
            rect = self._image_rect()
            if asset_id and not rect.isEmpty():
                pos = event.position()
                nx = max(0.03, min(0.97, (pos.x() - rect.left()) / max(1.0, rect.width())))
                ny = max(0.03, min(0.97, (pos.y() - rect.top()) / max(1.0, rect.height())))
                self.asset_dropped.emit(asset_id, nx, ny)
                event.acceptProposedAction()
                self.update()
                return
        if md.hasUrls():
            paths = [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                self.update()
                return
        self.update()
