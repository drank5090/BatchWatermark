"""Modern Studio Dark stylesheet and design tokens for PySide6."""

from __future__ import annotations

STUDIO_DARK_QSS = """
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: #E5E7EB;
}

QMainWindow, QDialog {
    background-color: #16181D;
}

QWidget#CentralWidget, QWidget#PanelBody {
    background-color: #16181D;
}

QWidget#GridHost {
    background-color: #14161B;
}

/* Top toolbar bar */
QFrame#TopBar {
    background-color: #1E2128;
    border-bottom: 1px solid #2C313C;
}

QLabel#AppTitle {
    font-size: 15px;
    font-weight: 700;
    color: #F9FAFB;
}

QLabel#CountBadge {
    background-color: #262B36;
    color: #93C5FD;
    border: 1px solid #354156;
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 600;
}

/* Buttons */
QPushButton {
    background-color: #2A2F3A;
    color: #E5E7EB;
    border: 1px solid #383F4E;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #343B49;
    border-color: #4B5568;
}

QPushButton:pressed {
    background-color: #232832;
}

QPushButton:disabled {
    background-color: #21242C;
    color: #6B7280;
    border-color: #2A2E37;
}

QPushButton#PrimaryButton {
    background-color: #3B82F6;
    color: #FFFFFF;
    border: 1px solid #3B82F6;
    font-weight: 600;
    padding: 8px 16px;
}

QPushButton#PrimaryButton:hover {
    background-color: #2563EB;
    border-color: #2563EB;
}

QPushButton#PrimaryButton:pressed {
    background-color: #1D4ED8;
}

QPushButton#PrimaryButton:disabled {
    background-color: #28364F;
    color: #7D95B8;
    border-color: #28364F;
}

QPushButton#IsolateToggleBtn {
    background-color: #242934;
    color: #CBD5E1;
    border: 1px solid #3B4354;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
}

QPushButton#IsolateToggleBtn:hover {
    background-color: #2F3645;
    border-color: #55627A;
}

QPushButton#IsolateToggleBtn:checked {
    background-color: #1D4ED8;
    color: #FFFFFF;
    border: 1px solid #60A5FA;
}

QPushButton#DangerButton {
    background-color: #2A2326;
    color: #FCA5A5;
    border: 1px solid #4C2C32;
}

QPushButton#DangerButton:hover {
    background-color: #7F1D1D;
    color: #FFFFFF;
    border-color: #991B1B;
}

QPushButton#GhostButton {
    background-color: transparent;
    border: 1px solid #383F4E;
    padding: 4px 8px;
    font-size: 12px;
}

QPushButton#GhostButton:hover {
    background-color: #2C313C;
}

QPushButton#GhostButton:disabled {
    color: #555D6E;
    border-color: #292E38;
}

/* Segmented toggle buttons */
QPushButton#SegmentedBtn {
    background-color: #15181E;
    color: #9CA3AF;
    border: 1px solid #323744;
    border-radius: 6px;
    padding: 6px 10px;
    font-weight: 600;
}

QPushButton#SegmentedBtn:hover {
    color: #E5E7EB;
    background-color: #252932;
}

QPushButton#SegmentedBtn:checked {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #60A5FA;
}

/* Quick pill buttons */
QPushButton#PillBtn {
    background-color: #232730;
    color: #CBD5E1;
    border: 1px solid #343A46;
    border-radius: 4px;
    padding: 3px 7px;
    font-size: 11px;
}

QPushButton#PillBtn:hover {
    background-color: #323846;
    border-color: #4F596B;
    color: #FFFFFF;
}

QPushButton#PillBtn:checked {
    background-color: #2563EB;
    border-color: #60A5FA;
    color: #FFFFFF;
}

/* Anchor 3x3 grid buttons */
QPushButton#AnchorBtn {
    background-color: #1B1E25;
    color: #9CA3AF;
    border: 1px solid #323744;
    border-radius: 5px;
    font-size: 14px;
    font-weight: 700;
    padding: 0px;
}

QPushButton#AnchorBtn:hover {
    background-color: #282D38;
    border-color: #4B5568;
    color: #F3F4F6;
}

QPushButton#AnchorBtn:checked {
    background-color: #2563EB;
    border: 1px solid #60A5FA;
    color: #FFFFFF;
}

/* Section cards in control panel */
QFrame#SectionCard {
    background-color: #1E2128;
    border: 1px solid #2C313C;
    border-radius: 8px;
}

QFrame#OrientationCard {
    background-color: #1B2333;
    border: 1px solid #324A75;
    border-radius: 8px;
}

QLabel#SectionTitle {
    font-size: 13px;
    font-weight: 700;
    color: #F3F4F6;
    padding-bottom: 2px;
}

QLabel#MutedLabel {
    color: #9CA3AF;
    font-size: 12px;
}

QLabel#InfoHintBadge {
    background-color: #1A2639;
    color: #93C5FD;
    border: 1px solid #2C4670;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 12px;
}

/* Menus */
QMenu {
    background-color: #1E2128;
    color: #E5E7EB;
    border: 1px solid #383F4E;
    padding: 4px;
}

QMenu::item {
    padding: 6px 16px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #2563EB;
    color: #FFFFFF;
}

/* Inputs */
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #15181E;
    color: #F3F4F6;
    border: 1px solid #323846;
    border-radius: 5px;
    padding: 5px 8px;
    selection-background-color: #3B82F6;
}

QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #3B82F6;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox QAbstractItemView {
    background-color: #1E2128;
    color: #E5E7EB;
    border: 1px solid #383F4E;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
}

/* Sliders */
QSlider::groove:horizontal {
    height: 4px;
    background: #2F3542;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #3B82F6;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #F3F4F6;
    border: 2px solid #3B82F6;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #FFFFFF;
    border-color: #60A5FA;
}

/* CheckBoxes */
QCheckBox {
    spacing: 7px;
    color: #D1D5DB;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #4B5568;
    background-color: #15181E;
}

QCheckBox::indicator:checked {
    background-color: #3B82F6;
    border-color: #3B82F6;
}

/* Splitter */
QSplitter::handle {
    background-color: #262A34;
    width: 2px;
}

QSplitter::handle:hover {
    background-color: #3B82F6;
}

/* ScrollAreas & ScrollBars */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:vertical {
    background: #16181D;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #343A46;
    min-height: 30px;
    border-radius: 5px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background: #4B5568;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #16181D;
    height: 10px;
}

QScrollBar::handle:horizontal {
    background: #343A46;
    min-width: 30px;
    border-radius: 5px;
    margin: 2px;
}

/* Preview Gallery & Orientation Groups */
QFrame#GalleryContainer {
    background-color: #14161B;
}

QFrame#GalleryFilterBar {
    background-color: #1A1E26;
    border-bottom: 1px solid #2A303D;
}

QFrame#GroupHeaderBar {
    background-color: #1B2029;
    border: 1px solid #2C3444;
    border-radius: 7px;
}

QLabel#GroupHeaderTitle {
    font-size: 13px;
    font-weight: 700;
    color: #F3F4F6;
}

QLabel#GroupCountBadge {
    background-color: #263145;
    color: #93C5FD;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}

QFrame#DropZone {
    background-color: #1A1D24;
    border: 2px dashed #384050;
    border-radius: 14px;
}

QFrame#DropZone[dragOver="true"] {
    background-color: #1D2738;
    border-color: #3B82F6;
}

QFrame#PreviewCard {
    background-color: #1F232B;
    border: 1px solid #2D323E;
    border-radius: 9px;
}

QFrame#PreviewCard:hover {
    border-color: #4B6B9B;
    background-color: #242934;
}

QFrame#PreviewCard[selected="true"] {
    border: 1px solid #3B82F6;
    background-color: #232B3A;
}

QLabel#VideoBadge {
    background-color: rgba(17, 24, 39, 210);
    color: #93C5FD;
    border: 1px solid rgba(96, 165, 250, 140);
    border-radius: 9px;
    padding: 2px 7px;
    font-size: 11px;
    font-weight: 700;
}

QPushButton#CardActionBtn {
    background-color: rgba(20, 22, 27, 200);
    color: #E5E7EB;
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 12px;
    padding: 0px;
    font-size: 12px;
    font-weight: 700;
}

QPushButton#CardActionBtn:hover {
    background-color: #3B82F6;
    border-color: #60A5FA;
    color: #FFFFFF;
}

QPushButton#CardRemoveBtn {
    background-color: rgba(20, 22, 27, 200);
    color: #FCA5A5;
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 12px;
    padding: 0px;
    font-size: 12px;
    font-weight: 700;
}

QPushButton#CardRemoveBtn:hover {
    background-color: #DC2626;
    border-color: #EF4444;
    color: #FFFFFF;
}

/* Control panel sticky export footer */
QFrame#ExportFooter {
    background-color: #1E2128;
    border-top: 1px solid #2C313C;
}

QStatusBar {
    background-color: #1A1D24;
    border-top: 1px solid #2A2F3A;
    color: #9CA3AF;
    font-size: 12px;
}

QProgressBar {
    background-color: #15181E;
    border: 1px solid #323846;
    border-radius: 5px;
    text-align: center;
    color: #F3F4F6;
    height: 20px;
}

QProgressBar::chunk {
    background-color: #3B82F6;
    border-radius: 4px;
}
"""
