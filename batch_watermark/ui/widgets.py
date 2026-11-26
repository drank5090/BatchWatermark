"""Reusable polished PySide6 widgets for watermark controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import AnchorPosition


class SectionCard(QFrame):
    """Styled container card with a header title."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SectionCard")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(12, 10, 12, 12)
        self._root.setSpacing(8)

        header = QLabel(title)
        header.setObjectName("SectionTitle")
        self._root.addWidget(header)

        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 2, 0, 0)
        self.body_layout.setSpacing(8)
        self._root.addLayout(self.body_layout)


class SliderSpinRow(QWidget):
    """Synchronized label + slider + integer spinbox row."""

    value_changed = Signal(int)

    def __init__(
        self,
        label: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str = "",
        label_width: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._label = QLabel(label)
        self._label.setFixedWidth(label_width)
        layout.addWidget(self._label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        layout.addWidget(self.slider, 1)

        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        if suffix:
            self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(68)
        layout.addWidget(self.spin)

        self.slider.valueChanged.connect(self._on_slider_changed)
        self.spin.valueChanged.connect(self._on_spin_changed)

    def _on_slider_changed(self, val: int) -> None:
        if self.spin.value() != val:
            self.spin.blockSignals(True)
            self.spin.setValue(val)
            self.spin.blockSignals(False)
        self.value_changed.emit(val)

    def _on_spin_changed(self, val: int) -> None:
        if self.slider.value() != val:
            self.slider.blockSignals(True)
            self.slider.setValue(val)
            self.slider.blockSignals(False)
        self.value_changed.emit(val)

    def value(self) -> int:
        return self.spin.value()

    def set_value(self, val: int, emit: bool = False) -> None:
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(val)
        self.spin.setValue(val)
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)
        if emit:
            self.value_changed.emit(self.spin.value())

    def set_label(self, text: str) -> None:
        self._label.setText(text)


class DoubleSliderSpinRow(QWidget):
    """Synchronized label + slider + float spinbox row (1 decimal precision)."""

    value_changed = Signal(float)

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        value: float,
        step: float = 0.5,
        suffix: str = "",
        label_width: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scale = 10  # 0.1 resolution on slider
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel(label)
        lbl.setFixedWidth(label_width)
        layout.addWidget(lbl)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(round(minimum * self._scale)), int(round(maximum * self._scale)))
        self.slider.setValue(int(round(value * self._scale)))
        layout.addWidget(self.slider, 1)

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(1)
        self.spin.setSingleStep(step)
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        if suffix:
            self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(68)
        layout.addWidget(self.spin)

        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)

    def _on_slider(self, raw: int) -> None:
        val = round(raw / self._scale, 1)
        if abs(self.spin.value() - val) > 1e-4:
            self.spin.blockSignals(True)
            self.spin.setValue(val)
            self.spin.blockSignals(False)
        self.value_changed.emit(val)

    def _on_spin(self, val: float) -> None:
        raw = int(round(val * self._scale))
        if self.slider.value() != raw:
            self.slider.blockSignals(True)
            self.slider.setValue(raw)
            self.slider.blockSignals(False)
        self.value_changed.emit(val)

    def value(self) -> float:
        return self.spin.value()

    def set_value(self, val: float, emit: bool = False) -> None:
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(int(round(val * self._scale)))
        self.spin.setValue(val)
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)
        if emit:
            self.value_changed.emit(self.spin.value())


class ColorPickerRow(QWidget):
    """Color swatch picker button with hex display and quick preset swatches."""

    color_changed = Signal(str)

    PRESETS: tuple[tuple[str, str], ...] = (
        ("#FFFFFF", "纯白"),
        ("#000000", "纯黑"),
        ("#E5E7EB", "浅灰"),
        ("#EF4444", "红色"),
        ("#3B82F6", "蓝色"),
        ("#F59E0B", "金黄"),
    )

    def __init__(
        self,
        label: str,
        initial_hex: str = "#FFFFFF",
        show_presets: bool = True,
        label_width: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color_hex = initial_hex.upper()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        if label:
            lbl = QLabel(label)
            lbl.setFixedWidth(label_width)
            layout.addWidget(lbl)

        self._btn = QPushButton()
        self._btn.setFixedHeight(26)
        self._btn.setMinimumWidth(78)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._open_dialog)
        layout.addWidget(self._btn)

        if show_presets:
            for hex_code, tip in self.PRESETS:
                swatch = QPushButton()
                swatch.setFixedSize(22, 22)
                swatch.setToolTip(f"{tip} ({hex_code})")
                swatch.setCursor(Qt.CursorShape.PointingHandCursor)
                swatch.setStyleSheet(
                    f"QPushButton {{ background-color: {hex_code}; border: 1px solid #4B5568; border-radius: 4px; padding: 0; }}"
                    f"QPushButton:hover {{ border: 2px solid #60A5FA; }}"
                )
                swatch.clicked.connect(lambda _checked=False, c=hex_code: self.set_color(c, emit=True))
                layout.addWidget(swatch)

        layout.addStretch(1)
        self._refresh_button()

    def _refresh_button(self) -> None:
        qcol = QColor(self._color_hex)
        # Choose readable foreground text based on perceived luminance
        lum = 0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()
        fg = "#111827" if lum > 150 else "#F9FAFB"
        self._btn.setText(self._color_hex)
        self._btn.setStyleSheet(
            f"QPushButton {{ background-color: {self._color_hex}; color: {fg}; "
            f"border: 1px solid #4B5568; border-radius: 5px; font-weight: 600; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: #60A5FA; }}"
        )

    def _open_dialog(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color_hex), self, "选择水印颜色")
        if chosen.isValid():
            self.set_color(chosen.name().upper(), emit=True)

    def color(self) -> str:
        return self._color_hex

    def set_color(self, hex_color: str, emit: bool = False) -> None:
        cleaned = hex_color.upper()
        if cleaned == self._color_hex and not emit:
            return
        self._color_hex = cleaned
        self._refresh_button()
        if emit:
            self.color_changed.emit(self._color_hex)


class AnchorGridWidget(QWidget):
    """Interactive 3x3 nine-grid anchor selector for single watermark mode."""

    anchor_changed = Signal(AnchorPosition)

    _GRID_SPEC: tuple[tuple[int, int, AnchorPosition, str, str], ...] = (
        (0, 0, AnchorPosition.TOP_LEFT, "↖", "左上角"),
        (0, 1, AnchorPosition.TOP_CENTER, "↑", "顶部居中"),
        (0, 2, AnchorPosition.TOP_RIGHT, "↗", "右上角"),
        (1, 0, AnchorPosition.MIDDLE_LEFT, "←", "左侧居中"),
        (1, 1, AnchorPosition.CENTER, "●", "正中心"),
        (1, 2, AnchorPosition.MIDDLE_RIGHT, "→", "右侧居中"),
        (2, 0, AnchorPosition.BOTTOM_LEFT, "↙", "左下角"),
        (2, 1, AnchorPosition.BOTTOM_CENTER, "↓", "底部居中"),
        (2, 2, AnchorPosition.BOTTOM_RIGHT, "↘", "右下角"),
    )

    def __init__(
        self,
        initial: AnchorPosition = AnchorPosition.BOTTOM_RIGHT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._current = initial
        self._buttons: dict[AnchorPosition, QPushButton] = {}

        group = QButtonGroup(self)
        group.setExclusive(True)
        self._group = group

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(5)

        for row, col, pos, glyph, tip in self._GRID_SPEC:
            btn = QPushButton(glyph)
            btn.setCheckable(True)
            btn.setObjectName("AnchorBtn")
            btn.setFixedSize(38, 32)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, p=pos: self._select(p, emit=True))
            group.addButton(btn)
            grid.addWidget(btn, row, col)
            self._buttons[pos] = btn

        self.set_anchor(initial, emit=False)

    def _select(self, pos: AnchorPosition, emit: bool) -> None:
        self._current = pos
        btn = self._buttons[pos]
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)
        if emit:
            self.anchor_changed.emit(pos)

    def anchor(self) -> AnchorPosition:
        return self._current

    def set_anchor(self, pos: AnchorPosition, emit: bool = False) -> None:
        self._select(pos, emit=emit)
