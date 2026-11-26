"""Right-side watermark parameter, custom preset management, and batch export control panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..fonts import discover_system_fonts
from ..models import (
    AnchorPosition,
    ConflictPolicy,
    ExportConfig,
    LayoutMode,
    OrientationGroup,
    OutputFormat,
    WatermarkConfig,
    WatermarkType,
)
from ..presets import PresetStore, get_builtin_presets
from .widgets import (
    AnchorGridWidget,
    ColorPickerRow,
    DoubleSliderSpinRow,
    SectionCard,
    SliderSpinRow,
)


class ControlPanel(QWidget):
    """Parameter controls, local/JSON presets, orientation-isolated configs, and export settings."""

    config_changed = Signal(WatermarkConfig)
    export_requested = Signal()

    def __init__(
        self,
        preset_store: PresetStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preset_store = preset_store if preset_store is not None else PresetStore()
        self._builtin_presets = get_builtin_presets()

        # Orientation isolation config states
        self._orientation_isolated = False
        self._independent_orientation_params = False
        self._editing_orientation = OrientationGroup.LANDSCAPE
        self._landscape_config = WatermarkConfig()
        self._portrait_config = WatermarkConfig()

        self._config = self._landscape_config.clone()
        self._updating_ui = False

        self.setMinimumWidth(395)
        self.setMaximumWidth(485)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("PanelBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(12, 12, 12, 14)
        self._body_layout.setSpacing(10)

        self._build_orientation_param_card()
        self._build_preset_section()
        self._build_content_section()
        self._build_appearance_section()
        self._build_layout_section()
        self._build_export_section()
        self._body_layout.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Sticky export footer
        footer = QFrame()
        footer.setObjectName("ExportFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 10, 12, 12)
        footer_layout.setSpacing(6)

        self._btn_export = QPushButton("⬇ 批量导出全部媒体 (0 项)")
        self._btn_export.setObjectName("PrimaryButton")
        self._btn_export.setFixedHeight(40)
        self._btn_export.setEnabled(False)
        self._btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_export.clicked.connect(self.export_requested.emit)
        footer_layout.addWidget(self._btn_export)

        root.addWidget(footer)

        self._rebuild_preset_combo()
        self.apply_config_to_ui(self._config, emit=False)

    # ---- Section builders ----

    def _build_orientation_param_card(self) -> None:
        self._orientation_card = QFrame()
        self._orientation_card.setObjectName("OrientationCard")
        self._orientation_card.setVisible(False)
        ol = QVBoxLayout(self._orientation_card)
        ol.setContentsMargins(12, 10, 12, 10)
        ol.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("横竖隔离 · 参数模式")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("color: #93C5FD;")
        head.addWidget(title)
        head.addStretch(1)
        ol.addLayout(head)

        self._chk_independent_params = QCheckBox("横版与竖版使用独立水印参数")
        self._chk_independent_params.setToolTip(
            "关闭时横竖共用同一套参数；开启后可分别调节横版与竖版的字号、位置或文字"
        )
        self._chk_independent_params.toggled.connect(self._on_independent_toggled)
        ol.addWidget(self._chk_independent_params)

        self._orient_switch_host = QWidget()
        self._orient_switch_host.setVisible(False)
        sw_lay = QVBoxLayout(self._orient_switch_host)
        sw_lay.setContentsMargins(0, 0, 0, 0)
        sw_lay.setSpacing(6)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        self._orient_btn_group = QButtonGroup(self)
        self._orient_btn_group.setExclusive(True)

        self._btn_edit_landscape = QPushButton("编辑横版参数")
        self._btn_edit_landscape.setCheckable(True)
        self._btn_edit_landscape.setChecked(True)
        self._btn_edit_landscape.setObjectName("SegmentedBtn")
        self._btn_edit_landscape.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_edit_portrait = QPushButton("编辑竖版参数")
        self._btn_edit_portrait.setCheckable(True)
        self._btn_edit_portrait.setObjectName("SegmentedBtn")
        self._btn_edit_portrait.setCursor(Qt.CursorShape.PointingHandCursor)

        self._orient_btn_group.addButton(self._btn_edit_landscape)
        self._orient_btn_group.addButton(self._btn_edit_portrait)
        tab_row.addWidget(self._btn_edit_landscape, 1)
        tab_row.addWidget(self._btn_edit_portrait, 1)
        sw_lay.addLayout(tab_row)

        self._btn_edit_landscape.clicked.connect(
            lambda: self._switch_editing_orientation(OrientationGroup.LANDSCAPE)
        )
        self._btn_edit_portrait.clicked.connect(
            lambda: self._switch_editing_orientation(OrientationGroup.PORTRAIT)
        )

        sync_row = QHBoxLayout()
        self._btn_sync_other = QPushButton("将当前参数同步复制到另一方向")
        self._btn_sync_other.setObjectName("GhostButton")
        self._btn_sync_other.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sync_other.clicked.connect(self._copy_config_to_other_orientation)
        sync_row.addWidget(self._btn_sync_other)
        sw_lay.addLayout(sync_row)

        ol.addWidget(self._orient_switch_host)
        self._body_layout.addWidget(self._orientation_card)

    def _build_preset_section(self) -> None:
        card = SectionCard("水印预设管理（支持本机保存与导入导出）")

        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self._preset_combo = QComboBox()
        self._preset_combo.currentIndexChanged.connect(self._on_preset_index_changed)
        top_row.addWidget(self._preset_combo, 1)

        btn_reset = QPushButton("重置")
        btn_reset.setObjectName("GhostButton")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.clicked.connect(self._reset_defaults)
        top_row.addWidget(btn_reset)
        card.body_layout.addLayout(top_row)

        # Custom preset action buttons: Save, Delete, Import, Export
        act_row = QHBoxLayout()
        act_row.setSpacing(5)

        self._btn_save_preset = QPushButton("保存预设")
        self._btn_save_preset.setObjectName("GhostButton")
        self._btn_save_preset.setToolTip("将当前水印参数保存到本机预设库")
        self._btn_save_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save_preset.clicked.connect(self._on_save_preset_clicked)
        act_row.addWidget(self._btn_save_preset, 1)

        self._btn_delete_preset = QPushButton("删除")
        self._btn_delete_preset.setObjectName("GhostButton")
        self._btn_delete_preset.setEnabled(False)
        self._btn_delete_preset.setToolTip("删除当前选中的自定义预设")
        self._btn_delete_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_delete_preset.clicked.connect(self._on_delete_preset_clicked)
        act_row.addWidget(self._btn_delete_preset)

        self._btn_import_preset = QPushButton("导入")
        self._btn_import_preset.setObjectName("GhostButton")
        self._btn_import_preset.setToolTip("从 JSON 文件导入预设并保存到本机")
        self._btn_import_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_import_preset.clicked.connect(self._on_import_preset_clicked)
        act_row.addWidget(self._btn_import_preset)

        self._btn_export_preset = QPushButton("导出")
        self._btn_export_preset.setObjectName("GhostButton")
        self._btn_export_preset.setToolTip("导出当前参数或全部本机自定义预设为 JSON 文件")
        self._btn_export_preset.setCursor(Qt.CursorShape.PointingHandCursor)

        export_menu = QMenu(self)
        act_exp_cur = export_menu.addAction("导出当前水印参数 (.json)")
        act_exp_cur.triggered.connect(self._on_export_current_preset)
        act_exp_all = export_menu.addAction("导出全部本机自定义预设 (.json)")
        act_exp_all.triggered.connect(self._on_export_all_presets)
        self._btn_export_preset.setMenu(export_menu)
        act_row.addWidget(self._btn_export_preset)

        card.body_layout.addLayout(act_row)
        self._body_layout.addWidget(card)

    def _build_content_section(self) -> None:
        card = SectionCard("水印内容")

        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        self._type_group = QButtonGroup(self)
        self._type_group.setExclusive(True)

        self._btn_type_text = QPushButton("文字水印")
        self._btn_type_text.setCheckable(True)
        self._btn_type_text.setObjectName("SegmentedBtn")
        self._btn_type_text.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_type_image = QPushButton("图片 / Logo")
        self._btn_type_image.setCheckable(True)
        self._btn_type_image.setObjectName("SegmentedBtn")
        self._btn_type_image.setCursor(Qt.CursorShape.PointingHandCursor)

        self._type_group.addButton(self._btn_type_text)
        self._type_group.addButton(self._btn_type_image)
        type_row.addWidget(self._btn_type_text, 1)
        type_row.addWidget(self._btn_type_image, 1)
        card.body_layout.addLayout(type_row)

        self._btn_type_text.clicked.connect(lambda: self._on_type_changed(WatermarkType.TEXT))
        self._btn_type_image.clicked.connect(lambda: self._on_type_changed(WatermarkType.IMAGE))

        self._type_stack = QStackedWidget()
        card.body_layout.addWidget(self._type_stack)

        # ---- Text page ----
        text_page = QWidget()
        tl = QVBoxLayout(text_page)
        tl.setContentsMargins(0, 4, 0, 0)
        tl.setSpacing(8)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("输入水印文字（支持多行换行）...")
        self._text_edit.setFixedHeight(64)
        self._text_edit.textChanged.connect(self._emit_from_ui)
        tl.addWidget(self._text_edit)

        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        lbl_font = QLabel("字体")
        lbl_font.setFixedWidth(44)
        font_row.addWidget(lbl_font)

        self._font_combo = QComboBox()
        for font_label in discover_system_fonts():
            self._font_combo.addItem(font_label)
        self._font_combo.currentTextChanged.connect(self._on_system_font_chosen)
        font_row.addWidget(self._font_combo, 1)

        self._btn_custom_font = QPushButton("导入字体")
        self._btn_custom_font.setObjectName("GhostButton")
        self._btn_custom_font.setToolTip("选择本地 .ttf / .otf / .ttc 字体文件")
        self._btn_custom_font.clicked.connect(self._choose_custom_font)
        font_row.addWidget(self._btn_custom_font)
        tl.addLayout(font_row)

        self._custom_font_label = QLabel("")
        self._custom_font_label.setObjectName("MutedLabel")
        self._custom_font_label.setVisible(False)
        tl.addWidget(self._custom_font_label)

        self._font_size_row = SliderSpinRow("字号大小", 10, 220, 44)
        self._font_size_row.value_changed.connect(self._emit_from_ui)
        tl.addWidget(self._font_size_row)

        self._chk_proportional_text = QCheckBox("按媒体尺寸自适应比例")
        self._chk_proportional_text.setToolTip("开启后，不同分辨率的图片和视频将按比例缩放水印，保持视觉大小一致")
        self._chk_proportional_text.setChecked(True)
        self._chk_proportional_text.toggled.connect(self._on_proportional_toggled)
        tl.addWidget(self._chk_proportional_text)

        self._line_spacing_row = DoubleSliderSpinRow("行间距", 1.0, 2.5, 1.2, step=0.1, suffix="×")
        self._line_spacing_row.value_changed.connect(self._emit_from_ui)
        tl.addWidget(self._line_spacing_row)

        self._text_color_row = ColorPickerRow("文字颜色", "#FFFFFF", show_presets=True)
        self._text_color_row.color_changed.connect(self._emit_from_ui)
        tl.addWidget(self._text_color_row)

        stroke_top = QHBoxLayout()
        self._chk_stroke = QCheckBox("文字描边")
        self._chk_stroke.toggled.connect(self._on_effects_toggled)
        stroke_top.addWidget(self._chk_stroke)
        self._stroke_color_row = ColorPickerRow("", "#000000", show_presets=False)
        self._stroke_color_row.color_changed.connect(self._emit_from_ui)
        stroke_top.addWidget(self._stroke_color_row, 1)
        tl.addLayout(stroke_top)

        self._stroke_width_row = SliderSpinRow("描边粗细", 1, 16, 2, suffix="px")
        self._stroke_width_row.value_changed.connect(self._emit_from_ui)
        tl.addWidget(self._stroke_width_row)

        shadow_top = QHBoxLayout()
        self._chk_shadow = QCheckBox("投影阴影")
        self._chk_shadow.toggled.connect(self._on_effects_toggled)
        shadow_top.addWidget(self._chk_shadow)
        self._shadow_color_row = ColorPickerRow("", "#000000", show_presets=False)
        self._shadow_color_row.color_changed.connect(self._emit_from_ui)
        shadow_top.addWidget(self._shadow_color_row, 1)
        tl.addLayout(shadow_top)

        self._shadow_offset_row = SliderSpinRow("阴影偏移", 1, 20, 3, suffix="px")
        self._shadow_offset_row.value_changed.connect(self._emit_from_ui)
        tl.addWidget(self._shadow_offset_row)

        self._type_stack.addWidget(text_page)

        # ---- Image / Logo page ----
        img_page = QWidget()
        il = QVBoxLayout(img_page)
        il.setContentsMargins(0, 4, 0, 0)
        il.setSpacing(8)

        logo_picker_row = QHBoxLayout()
        logo_picker_row.setSpacing(8)

        self._logo_thumb = QLabel("无Logo")
        self._logo_thumb.setFixedSize(48, 48)
        self._logo_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_thumb.setStyleSheet(
            "background-color: #15181E; border: 1px solid #323846; border-radius: 6px; font-size: 11px; color: #9CA3AF;"
        )
        logo_picker_row.addWidget(self._logo_thumb)

        logo_btn_col = QVBoxLayout()
        logo_btn_col.setSpacing(4)
        self._logo_path_label = QLabel("请选择带透明背景的 PNG / WebP Logo")
        self._logo_path_label.setObjectName("MutedLabel")
        self._logo_path_label.setWordWrap(True)
        logo_btn_col.addWidget(self._logo_path_label)

        btn_pick_logo = QPushButton("选择水印图片...")
        btn_pick_logo.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_pick_logo.clicked.connect(self._choose_logo_file)
        logo_btn_col.addWidget(btn_pick_logo)

        logo_picker_row.addLayout(logo_btn_col, 1)
        il.addLayout(logo_picker_row)

        self._logo_scale_row = SliderSpinRow("缩放比例", 3, 100, 22, suffix="%")
        self._logo_scale_row.value_changed.connect(self._emit_from_ui)
        il.addWidget(self._logo_scale_row)

        self._chk_proportional_logo = QCheckBox("按目标媒体宽度百分比缩放")
        self._chk_proportional_logo.setChecked(True)
        self._chk_proportional_logo.toggled.connect(self._on_proportional_toggled)
        il.addWidget(self._chk_proportional_logo)
        il.addStretch(1)

        self._type_stack.addWidget(img_page)
        self._body_layout.addWidget(card)

    def _build_appearance_section(self) -> None:
        card = SectionCard("透明度与角度")

        self._opacity_row = SliderSpinRow("不透明度", 0, 100, 55, suffix="%")
        self._opacity_row.value_changed.connect(self._emit_from_ui)
        card.body_layout.addWidget(self._opacity_row)

        self._rotation_row = SliderSpinRow("旋转角度", -180, 180, -25, suffix="°")
        self._rotation_row.value_changed.connect(self._emit_from_ui)
        card.body_layout.addWidget(self._rotation_row)

        angle_pills = QHBoxLayout()
        angle_pills.setSpacing(5)
        lbl_q = QLabel("快捷角度")
        lbl_q.setObjectName("MutedLabel")
        lbl_q.setFixedWidth(60)
        angle_pills.addWidget(lbl_q)
        for deg in (0, -25, -45, 30, 45):
            pill = QPushButton(f"{deg}°")
            pill.setObjectName("PillBtn")
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.clicked.connect(lambda _c=False, d=deg: self._rotation_row.set_value(d, emit=True))
            angle_pills.addWidget(pill)
        angle_pills.addStretch(1)
        card.body_layout.addLayout(angle_pills)

        self._body_layout.addWidget(card)

    def _build_layout_section(self) -> None:
        card = SectionCard("位置与排布")

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self._btn_mode_tiled = QPushButton("全图平铺")
        self._btn_mode_tiled.setCheckable(True)
        self._btn_mode_tiled.setObjectName("SegmentedBtn")
        self._btn_mode_tiled.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_mode_single = QPushButton("单点定位")
        self._btn_mode_single.setCheckable(True)
        self._btn_mode_single.setObjectName("SegmentedBtn")
        self._btn_mode_single.setCursor(Qt.CursorShape.PointingHandCursor)

        self._mode_group.addButton(self._btn_mode_tiled)
        self._mode_group.addButton(self._btn_mode_single)
        mode_row.addWidget(self._btn_mode_tiled, 1)
        mode_row.addWidget(self._btn_mode_single, 1)
        card.body_layout.addLayout(mode_row)

        self._btn_mode_tiled.clicked.connect(lambda: self._on_layout_mode_changed(LayoutMode.TILED))
        self._btn_mode_single.clicked.connect(lambda: self._on_layout_mode_changed(LayoutMode.SINGLE))

        self._layout_stack = QStackedWidget()
        card.body_layout.addWidget(self._layout_stack)

        # ---- Tiled page ----
        tiled_page = QWidget()
        tpl = QVBoxLayout(tiled_page)
        tpl.setContentsMargins(0, 4, 0, 0)
        tpl.setSpacing(8)

        self._tile_x_row = SliderSpinRow("水平间距", 10, 500, 120)
        self._tile_x_row.value_changed.connect(self._emit_from_ui)
        tpl.addWidget(self._tile_x_row)

        self._tile_y_row = SliderSpinRow("垂直间距", 10, 500, 100)
        self._tile_y_row.value_changed.connect(self._emit_from_ui)
        tpl.addWidget(self._tile_y_row)

        self._chk_stagger = QCheckBox("奇偶行交错排布（砖墙错位）")
        self._chk_stagger.setChecked(True)
        self._chk_stagger.toggled.connect(self._emit_from_ui)
        tpl.addWidget(self._chk_stagger)
        tpl.addStretch(1)
        self._layout_stack.addWidget(tiled_page)

        # ---- Single page ----
        single_page = QWidget()
        spl = QVBoxLayout(single_page)
        spl.setContentsMargins(0, 4, 0, 0)
        spl.setSpacing(8)

        anchor_row = QHBoxLayout()
        lbl_a = QLabel("九宫格")
        lbl_a.setFixedWidth(60)
        anchor_row.addWidget(lbl_a, 0, Qt.AlignmentFlag.AlignTop)
        self._anchor_grid = AnchorGridWidget(AnchorPosition.BOTTOM_RIGHT)
        self._anchor_grid.anchor_changed.connect(self._emit_from_ui)
        anchor_row.addWidget(self._anchor_grid)
        anchor_row.addStretch(1)
        spl.addLayout(anchor_row)

        self._margin_x_row = DoubleSliderSpinRow("水平边距", 0.0, 30.0, 4.0, step=0.5, suffix="%")
        self._margin_x_row.value_changed.connect(self._emit_from_ui)
        spl.addWidget(self._margin_x_row)

        self._margin_y_row = DoubleSliderSpinRow("垂直边距", 0.0, 30.0, 4.0, step=0.5, suffix="%")
        self._margin_y_row.value_changed.connect(self._emit_from_ui)
        spl.addWidget(self._margin_y_row)

        self._layout_stack.addWidget(single_page)

        self._offset_x_row = DoubleSliderSpinRow("水平微调", -40.0, 40.0, 0.0, step=0.5, suffix="%")
        self._offset_x_row.value_changed.connect(self._emit_from_ui)
        card.body_layout.addWidget(self._offset_x_row)

        self._offset_y_row = DoubleSliderSpinRow("垂直微调", -40.0, 40.0, 0.0, step=0.5, suffix="%")
        self._offset_y_row.value_changed.connect(self._emit_from_ui)
        card.body_layout.addWidget(self._offset_y_row)

        self._body_layout.addWidget(card)

    def _build_export_section(self) -> None:
        card = SectionCard("批量导出设置")

        self._isolation_export_hint = QLabel("已开启横竖隔离：将自动分别导出至「横版」和「竖版」子文件夹")
        self._isolation_export_hint.setObjectName("InfoHintBadge")
        self._isolation_export_hint.setWordWrap(True)
        self._isolation_export_hint.setVisible(False)
        card.body_layout.addWidget(self._isolation_export_hint)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self._out_dir_edit = QLineEdit()
        self._out_dir_edit.setPlaceholderText("选择导出目标文件夹（未选时导出前弹窗询问）")
        dir_row.addWidget(self._out_dir_edit, 1)

        btn_browse = QPushButton("浏览...")
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self._choose_output_dir)
        dir_row.addWidget(btn_browse)
        card.body_layout.addLayout(dir_row)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_row.addWidget(QLabel("前缀"))
        self._prefix_edit = QLineEdit("")
        self._prefix_edit.setPlaceholderText("可选")
        name_row.addWidget(self._prefix_edit, 1)

        name_row.addWidget(QLabel("后缀"))
        self._suffix_edit = QLineEdit("_watermarked")
        self._suffix_edit.setPlaceholderText("如 _wm")
        name_row.addWidget(self._suffix_edit, 1)
        card.body_layout.addLayout(name_row)

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        lbl_fmt = QLabel("图片格式")
        lbl_fmt.setFixedWidth(56)
        fmt_row.addWidget(lbl_fmt)

        self._format_combo = QComboBox()
        self._format_combo.addItem("保持原格式", OutputFormat.KEEP_ORIGINAL)
        self._format_combo.addItem("JPEG (.jpg)", OutputFormat.JPEG)
        self._format_combo.addItem("PNG (.png)", OutputFormat.PNG)
        self._format_combo.addItem("WebP (.webp)", OutputFormat.WEBP)
        self._format_combo.currentIndexChanged.connect(self._sync_quality_enabled)
        fmt_row.addWidget(self._format_combo, 1)

        self._conflict_combo = QComboBox()
        self._conflict_combo.addItem("重名自动编号", ConflictPolicy.AUTO_RENAME)
        self._conflict_combo.addItem("覆盖同名文件", ConflictPolicy.OVERWRITE)
        fmt_row.addWidget(self._conflict_combo, 1)
        card.body_layout.addLayout(fmt_row)

        self._quality_row = SliderSpinRow("导出质量", 50, 100, 92, suffix="%")
        card.body_layout.addWidget(self._quality_row)

        self._chk_keep_exif = QCheckBox("图片保留原 EXIF 信息（JPEG / WebP）")
        self._chk_keep_exif.setChecked(True)
        card.body_layout.addWidget(self._chk_keep_exif)

        self._chk_video_audio = QCheckBox("视频保留原声（导出为 MP4 / H.264）")
        self._chk_video_audio.setChecked(True)
        card.body_layout.addWidget(self._chk_video_audio)

        self._body_layout.addWidget(card)

    # ---- Orientation Isolation Controls ----

    def set_orientation_isolated(self, enabled: bool) -> None:
        self._orientation_isolated = enabled
        self._orientation_card.setVisible(enabled)
        self._isolation_export_hint.setVisible(enabled)
        if not enabled and self._independent_orientation_params:
            # Keep active config unified when turning off isolation
            self._independent_orientation_params = False
            self._chk_independent_params.blockSignals(True)
            self._chk_independent_params.setChecked(False)
            self._chk_independent_params.blockSignals(False)
            self._orient_switch_host.setVisible(False)
            self._landscape_config = self._config.clone()
            self._portrait_config = self._config.clone()
            self.config_changed.emit(self._config.clone())

    def _on_independent_toggled(self, checked: bool) -> None:
        self._independent_orientation_params = checked
        self._orient_switch_host.setVisible(checked)
        if checked:
            # Seed both orientations from current config so switching is smooth
            self._landscape_config = self._config.clone()
            self._portrait_config = self._config.clone()
            self._editing_orientation = OrientationGroup.LANDSCAPE
            self._btn_edit_landscape.setChecked(True)
        else:
            # Unify both orientations to currently displayed config
            cur = self.get_watermark_config()
            self._landscape_config = cur.clone()
            self._portrait_config = cur.clone()
        self.config_changed.emit(self.get_watermark_config())

    def _switch_editing_orientation(self, orient: OrientationGroup) -> None:
        if orient == self._editing_orientation:
            return
        # Persist current UI edits to the previous orientation slot first
        current_ui = self.get_watermark_config()
        if self._editing_orientation == OrientationGroup.LANDSCAPE:
            self._landscape_config = current_ui
        else:
            self._portrait_config = current_ui

        self._editing_orientation = orient
        target = self._landscape_config if orient == OrientationGroup.LANDSCAPE else self._portrait_config
        self.apply_config_to_ui(target, emit=False)

    def _copy_config_to_other_orientation(self) -> None:
        cur = self.get_watermark_config()
        self._landscape_config = cur.clone()
        self._portrait_config = cur.clone()
        self.config_changed.emit(cur)

    def is_independent_orientation_enabled(self) -> bool:
        return self._orientation_isolated and self._independent_orientation_params

    def get_config_for_orientation(self, orientation: OrientationGroup) -> WatermarkConfig:
        if self.is_independent_orientation_enabled():
            if orientation == OrientationGroup.PORTRAIT:
                return self._portrait_config.clone()
            return self._landscape_config.clone()
        return self._config.clone()

    # ---- Preset Management (Built-in + Local Custom + JSON Import/Export) ----

    def _rebuild_preset_combo(self, select_kind: str | None = None, select_name: str | None = None) -> None:
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem("选择预设模板...", ("none", ""))

        custom_map = self._preset_store.list_custom()
        for name in custom_map:
            self._preset_combo.addItem(f"[自定义] {name}", ("custom", name))
        for name in self._builtin_presets:
            self._preset_combo.addItem(f"[内置] {name}", ("builtin", name))

        target_idx = 0
        if select_kind and select_name:
            for idx in range(self._preset_combo.count()):
                data = self._preset_combo.itemData(idx)
                if data == (select_kind, select_name):
                    target_idx = idx
                    break

        self._preset_combo.setCurrentIndex(target_idx)
        self._preset_combo.blockSignals(False)
        self._update_delete_preset_enabled()

    def _update_delete_preset_enabled(self) -> None:
        data = self._preset_combo.currentData()
        is_custom = isinstance(data, tuple) and data[0] == "custom"
        self._btn_delete_preset.setEnabled(is_custom)

    def _on_preset_index_changed(self, _index: int) -> None:
        self._update_delete_preset_enabled()
        if self._updating_ui:
            return
        data = self._preset_combo.currentData()
        if not isinstance(data, tuple):
            return
        kind, name = data
        if kind == "builtin" and name in self._builtin_presets:
            self.apply_config_to_ui(self._builtin_presets[name].clone(), emit=True)
        elif kind == "custom":
            cfg = self._preset_store.get_custom(name)
            if cfg is not None:
                self.apply_config_to_ui(cfg, emit=True)

    def select_preset_by_name(self, name: str) -> bool:
        """Programmatically select a custom or built-in preset by its raw name."""
        for idx in range(self._preset_combo.count()):
            data = self._preset_combo.itemData(idx)
            if isinstance(data, tuple) and data[1] == name:
                self._preset_combo.setCurrentIndex(idx)
                return True
        return False

    def save_current_as_custom_preset(self, name: str) -> str:
        """Save current active watermark parameters to local disk preset storage."""
        saved_name = self._preset_store.save_custom(name, self.get_watermark_config())
        self._rebuild_preset_combo(select_kind="custom", select_name=saved_name)
        return saved_name

    def _on_save_preset_clicked(self) -> None:
        data = self._preset_combo.currentData()
        default_name = data[1] if isinstance(data, tuple) and data[0] == "custom" else ""
        name, ok = QInputDialog.getText(
            self,
            "保存自定义预设",
            "请输入预设名称（将保存到本机，下次启动自动加载）：",
            text=default_name,
        )
        if not ok:
            return
        clean = name.strip()
        if not clean:
            QMessageBox.warning(self, "提示", "预设名称不能为空。")
            return
        if self._preset_store.has_custom(clean):
            reply = QMessageBox.question(
                self,
                "覆盖预设",
                f"本机已存在名为「{clean}」的预设，是否覆盖保存？",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.save_current_as_custom_preset(clean)

    def _on_delete_preset_clicked(self) -> None:
        data = self._preset_combo.currentData()
        if not (isinstance(data, tuple) and data[0] == "custom"):
            return
        name = data[1]
        reply = QMessageBox.question(self, "删除预设", f"确定删除本机自定义预设「{name}」吗？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._preset_store.delete_custom(name)
        self._rebuild_preset_combo()

    def _on_import_preset_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入水印预设 JSON 文件",
            "",
            "JSON 预设文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            imported_names = self._preset_store.import_from_file(Path(path), overwrite=False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", f"无法解析预设文件：\n{exc}")
            return

        first = imported_names[0]
        self._rebuild_preset_combo(select_kind="custom", select_name=first)
        cfg = self._preset_store.get_custom(first)
        if cfg is not None:
            self.apply_config_to_ui(cfg, emit=True)
        QMessageBox.information(
            self,
            "导入成功",
            f"已成功导入 {len(imported_names)} 个预设并保存到本机：\n" + "、".join(imported_names),
        )

    def _on_export_current_preset(self) -> None:
        data = self._preset_combo.currentData()
        suggested_name = data[1] if isinstance(data, tuple) and data[1] else "我的水印预设"
        safe_stem = "".join(ch for ch in suggested_name if ch not in r'\/:*?"<>|').strip() or "watermark_preset"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前水印参数",
            f"{safe_stem}.json",
            "JSON 预设文件 (*.json)",
        )
        if not path:
            return
        try:
            self._preset_store.export_single_to_file(Path(path), suggested_name, self.get_watermark_config())
            QMessageBox.information(self, "导出成功", f"当前水印预设已导出到：\n{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))

    def _on_export_all_presets(self) -> None:
        if not self._preset_store.list_custom():
            QMessageBox.information(self, "提示", "当前还没有已保存的本机自定义预设，请先点击「保存预设」。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出全部本机自定义预设",
            "BatchWatermark_presets.json",
            "JSON 预设文件 (*.json)",
        )
        if not path:
            return
        try:
            self._preset_store.export_all_custom_to_file(Path(path))
            count = len(self._preset_store.list_custom())
            QMessageBox.information(self, "导出成功", f"已导出全部 {count} 个本机自定义预设到：\n{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))

    def _reset_defaults(self) -> None:
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)
        self._update_delete_preset_enabled()
        self.apply_config_to_ui(WatermarkConfig(), emit=True)

    # ---- Other Handlers & State sync ----

    def _on_type_changed(self, wm_type: WatermarkType) -> None:
        self._type_stack.setCurrentIndex(0 if wm_type == WatermarkType.TEXT else 1)
        self._emit_from_ui()

    def _on_layout_mode_changed(self, mode: LayoutMode) -> None:
        self._layout_stack.setCurrentIndex(0 if mode == LayoutMode.TILED else 1)
        self._emit_from_ui()

    def _on_system_font_chosen(self, _font_name: str) -> None:
        if self._updating_ui:
            return
        self._config.custom_font_path = ""
        self._custom_font_label.setVisible(False)
        self._emit_from_ui()

    def _choose_custom_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择字体文件",
            "",
            "字体文件 (*.ttf *.otf *.ttc);;所有文件 (*.*)",
        )
        if path:
            self._config.custom_font_path = path
            self._custom_font_label.setText(f"自定义字体: {Path(path).name}")
            self._custom_font_label.setVisible(True)
            self._emit_from_ui()

    def _choose_logo_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Logo 水印图片",
            "",
            "图片文件 (*.png *.webp *.jpg *.jpeg *.bmp);;所有文件 (*.*)",
        )
        if path:
            self._set_logo_path_ui(path)
            self._emit_from_ui()

    def _set_logo_path_ui(self, path: str) -> None:
        self._config.logo_path = path
        if path and Path(path).is_file():
            self._logo_path_label.setText(Path(path).name)
            self._logo_path_label.setToolTip(path)
            pix = QPixmap(path)
            if not pix.isNull():
                scaled = pix.scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self._logo_thumb.setPixmap(scaled)
                return
        self._logo_thumb.setPixmap(QPixmap())
        self._logo_thumb.setText("无Logo")
        self._logo_path_label.setText("请选择带透明背景的 PNG / WebP Logo")

    def _on_proportional_toggled(self, checked: bool) -> None:
        if self._updating_ui:
            return
        self._updating_ui = True
        self._chk_proportional_text.setChecked(checked)
        self._chk_proportional_logo.setChecked(checked)
        self._updating_ui = False
        self._emit_from_ui()

    def _on_effects_toggled(self) -> None:
        self._stroke_width_row.setEnabled(self._chk_stroke.isChecked())
        self._stroke_color_row.setEnabled(self._chk_stroke.isChecked())
        self._shadow_offset_row.setEnabled(self._chk_shadow.isChecked())
        self._shadow_color_row.setEnabled(self._chk_shadow.isChecked())
        self._emit_from_ui()

    def _sync_quality_enabled(self) -> None:
        # Quality still controls video CRF even when image output is PNG, so keep enabled
        self._quality_row.setEnabled(True)

    def _choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择批量导出目标文件夹", self._out_dir_edit.text())
        if folder:
            self._out_dir_edit.setText(folder)

    def set_output_dir(self, folder: str) -> None:
        self._out_dir_edit.setText(folder)

    def set_image_count(self, count: int) -> None:
        self._btn_export.setText(f"⬇ 批量导出全部媒体 ({count} 项)")
        self._btn_export.setEnabled(count > 0)

    def _store_into_orientation_slots(self, cfg: WatermarkConfig) -> None:
        self._config = cfg.clone()
        if self.is_independent_orientation_enabled():
            if self._editing_orientation == OrientationGroup.LANDSCAPE:
                self._landscape_config = cfg.clone()
            else:
                self._portrait_config = cfg.clone()
        else:
            self._landscape_config = cfg.clone()
            self._portrait_config = cfg.clone()

    def _emit_from_ui(self, *_args) -> None:  # noqa: ANN002
        if self._updating_ui:
            return
        cfg = self.get_watermark_config()
        self._store_into_orientation_slots(cfg)
        self.config_changed.emit(cfg.clone())

    def get_watermark_config(self) -> WatermarkConfig:
        return WatermarkConfig(
            watermark_type=WatermarkType.TEXT if self._btn_type_text.isChecked() else WatermarkType.IMAGE,
            text=self._text_edit.toPlainText(),
            font_name=self._font_combo.currentText(),
            custom_font_path=self._config.custom_font_path,
            font_size=self._font_size_row.value(),
            proportional_size=self._chk_proportional_text.isChecked(),
            text_color=self._text_color_row.color(),
            line_spacing=self._line_spacing_row.value(),
            stroke_enabled=self._chk_stroke.isChecked(),
            stroke_width=self._stroke_width_row.value(),
            stroke_color=self._stroke_color_row.color(),
            shadow_enabled=self._chk_shadow.isChecked(),
            shadow_offset=self._shadow_offset_row.value(),
            shadow_color=self._shadow_color_row.color(),
            logo_path=self._config.logo_path,
            logo_scale_percent=self._logo_scale_row.value(),
            opacity=self._opacity_row.value(),
            rotation=self._rotation_row.value(),
            layout_mode=LayoutMode.TILED if self._btn_mode_tiled.isChecked() else LayoutMode.SINGLE,
            anchor=self._anchor_grid.anchor(),
            margin_x_percent=self._margin_x_row.value(),
            margin_y_percent=self._margin_y_row.value(),
            offset_x_percent=self._offset_x_row.value(),
            offset_y_percent=self._offset_y_row.value(),
            tile_spacing_x=self._tile_x_row.value(),
            tile_spacing_y=self._tile_y_row.value(),
            tile_stagger=self._chk_stagger.isChecked(),
        )

    def get_export_config(self) -> ExportConfig:
        return ExportConfig(
            output_dir=self._out_dir_edit.text().strip(),
            filename_prefix=self._prefix_edit.text(),
            filename_suffix=self._suffix_edit.text(),
            output_format=self._format_combo.currentData(),
            quality=self._quality_row.value(),
            keep_exif=self._chk_keep_exif.isChecked(),
            conflict_policy=self._conflict_combo.currentData(),
            isolate_orientation=self._orientation_isolated,
            video_keep_audio=self._chk_video_audio.isChecked(),
        )

    def apply_config_to_ui(self, cfg: WatermarkConfig, emit: bool = False) -> None:
        self._updating_ui = True
        self._store_into_orientation_slots(cfg)

        is_text = cfg.watermark_type == WatermarkType.TEXT
        self._btn_type_text.setChecked(is_text)
        self._btn_type_image.setChecked(not is_text)
        self._type_stack.setCurrentIndex(0 if is_text else 1)

        self._text_edit.setPlainText(cfg.text)
        idx = self._font_combo.findText(cfg.font_name)
        if idx >= 0:
            self._font_combo.setCurrentIndex(idx)
        if cfg.custom_font_path:
            self._custom_font_label.setText(f"自定义字体: {Path(cfg.custom_font_path).name}")
            self._custom_font_label.setVisible(True)
        else:
            self._custom_font_label.setVisible(False)

        self._font_size_row.set_value(cfg.font_size)
        self._chk_proportional_text.setChecked(cfg.proportional_size)
        self._chk_proportional_logo.setChecked(cfg.proportional_size)
        self._line_spacing_row.set_value(cfg.line_spacing)
        self._text_color_row.set_color(cfg.text_color)

        self._chk_stroke.setChecked(cfg.stroke_enabled)
        self._stroke_width_row.set_value(cfg.stroke_width)
        self._stroke_color_row.set_color(cfg.stroke_color)
        self._stroke_width_row.setEnabled(cfg.stroke_enabled)
        self._stroke_color_row.setEnabled(cfg.stroke_enabled)

        self._chk_shadow.setChecked(cfg.shadow_enabled)
        self._shadow_offset_row.set_value(cfg.shadow_offset)
        self._shadow_color_row.set_color(cfg.shadow_color)
        self._shadow_offset_row.setEnabled(cfg.shadow_enabled)
        self._shadow_color_row.setEnabled(cfg.shadow_enabled)

        self._set_logo_path_ui(cfg.logo_path)
        self._logo_scale_row.set_value(cfg.logo_scale_percent)

        self._opacity_row.set_value(cfg.opacity)
        self._rotation_row.set_value(cfg.rotation)

        is_tiled = cfg.layout_mode == LayoutMode.TILED
        self._btn_mode_tiled.setChecked(is_tiled)
        self._btn_mode_single.setChecked(not is_tiled)
        self._layout_stack.setCurrentIndex(0 if is_tiled else 1)

        self._anchor_grid.set_anchor(cfg.anchor)
        self._margin_x_row.set_value(cfg.margin_x_percent)
        self._margin_y_row.set_value(cfg.margin_y_percent)
        self._offset_x_row.set_value(cfg.offset_x_percent)
        self._offset_y_row.set_value(cfg.offset_y_percent)

        self._tile_x_row.set_value(cfg.tile_spacing_x)
        self._tile_y_row.set_value(cfg.tile_spacing_y)
        self._chk_stagger.setChecked(cfg.tile_stagger)

        self._updating_ui = False
        if emit:
            self.config_changed.emit(self._config.clone())
