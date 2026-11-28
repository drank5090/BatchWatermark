"""Desktop internationalization (i18n) manager with live Qt widget tree retranslation."""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path
import re
import sys

from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QWidget,
)

from .i18n_data import REGEX_TRANSLATIONS, SUPPORTED_LOCALES, TRANSLATIONS

VALID_LOCALE_CODES = tuple(code for code, _label, _slug in SUPPORTED_LOCALES)

_COMPILED_REGEX: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (re.compile(pat), repls) for pat, repls in REGEX_TRANSLATIONS
]

_ACTIVE_LOCALE: str = "zh-CN"


def normalize_locale(code: str | None) -> str:
    if not code:
        return "zh-CN"
    c = str(code).strip().replace("_", "-").lower()
    if "hant" in c or c in ("zh-hk", "zh-mo"):
        return "zh-Hant"
    if c.startswith("zh"):
        return "zh-CN"
    if c.startswith("ja"):
        return "ja"
    if c.startswith("en"):
        return "en"
    return "zh-CN"


def detect_system_locale() -> str:
    """Detect OS UI locale mapped into supported locales (zh-CN, en, ja, zh-Hant)."""
    try:
        lang, _enc = locale.getlocale()
        if lang:
            return normalize_locale(lang)
    except Exception:  # noqa: BLE001
        pass
    return "zh-CN"


def default_settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "BatchWatermark" / "settings.json"


def load_saved_locale(settings_path: Path | None = None) -> str | None:
    path = Path(settings_path) if settings_path else default_settings_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        val = raw.get("locale")
        if val:
            return normalize_locale(val)
    except Exception:  # noqa: BLE001
        return None
    return None


def save_locale(code: str, settings_path: Path | None = None) -> None:
    path = Path(settings_path) if settings_path else default_settings_path()
    norm = normalize_locale(code)
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:  # noqa: BLE001
            data = {}
    data["locale"] = norm
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_locale() -> str:
    return _ACTIVE_LOCALE


def set_locale(code: str, *, persist: bool = False, settings_path: Path | None = None) -> str:
    global _ACTIVE_LOCALE
    _ACTIVE_LOCALE = normalize_locale(code)
    if persist:
        try:
            save_locale(_ACTIVE_LOCALE, settings_path=settings_path)
        except OSError:
            pass
    return _ACTIVE_LOCALE


def translate_text(src: str, target_locale: str | None = None) -> str:
    """Translate a canonical zh-CN UI string into `target_locale` (or current active locale)."""
    if not src:
        return src
    loc = normalize_locale(target_locale) if target_locale else _ACTIVE_LOCALE
    if loc == "zh-CN":
        return src

    entry = TRANSLATIONS.get(src)
    if entry and loc in entry:
        return entry[loc]

    for pat, repls in _COMPILED_REGEX:
        m = pat.match(src)
        if m and loc in repls:
            out = repls[loc]
            for idx, grp in enumerate(m.groups(), start=1):
                translated_grp = translate_text(grp, loc)
                out = out.replace(f"${idx}", translated_grp)
            return out

    return src


# Short alias
t = translate_text


def _remember_or_update_src(widget: QWidget, prop_name: str, current_value: str) -> str:
    """Remember original zh-CN text on a widget so switching between any languages stays lossless."""
    stored = widget.property(prop_name)
    if stored is None:
        widget.setProperty(prop_name, current_value)
        return current_value
    stored_str = str(stored)
    # If app logic dynamically changed the text to a new zh-CN string, update stored canonical source
    if current_value != translate_text(stored_str) and current_value != stored_str:
        # Check if current_value matches any known canonical zh-CN phrase/pattern
        if current_value in TRANSLATIONS or any(p.match(current_value) for p, _ in _COMPILED_REGEX):
            widget.setProperty(prop_name, current_value)
            return current_value
    return stored_str


def retranslate_widget_tree(root: QWidget, target_locale: str | None = None) -> None:
    """Walk a Qt widget tree and translate all texts, tooltips, placeholders, and combo items live."""
    loc = normalize_locale(target_locale) if target_locale else _ACTIVE_LOCALE
    widgets = [root, *root.findChildren(QWidget)]

    for w in widgets:
        if w.property("_i18n_skip"):
            continue

        # Window title
        if isinstance(w, QMainWindow) or w.isWindow():
            title = w.windowTitle()
            if title:
                src_title = _remember_or_update_src(w, "_i18n_title", title)
                w.setWindowTitle(translate_text(src_title, loc))

        # ToolTip
        tip = w.toolTip()
        if tip:
            src_tip = _remember_or_update_src(w, "_i18n_tip", tip)
            w.setToolTip(translate_text(src_tip, loc))

        # Labels & Buttons (QPushButton, QCheckBox, QRadioButton)
        if isinstance(w, (QLabel, QAbstractButton)):
            txt = w.text()
            if txt:
                src_txt = _remember_or_update_src(w, "_i18n_text", txt)
                w.setText(translate_text(src_txt, loc))

        # Placeholders
        if isinstance(w, (QLineEdit, QPlainTextEdit)):
            ph = w.placeholderText()
            if ph:
                src_ph = _remember_or_update_src(w, "_i18n_ph", ph)
                w.setPlaceholderText(translate_text(src_ph, loc))

        # ComboBox items
        if isinstance(w, QComboBox):
            stored_items = w.property("_i18n_items")
            count = w.count()
            if not isinstance(stored_items, list) or len(stored_items) != count:
                stored_items = [w.itemText(i) for i in range(count)]
                w.setProperty("_i18n_items", stored_items)
            for i in range(count):
                w.setItemText(i, translate_text(str(stored_items[i]), loc))
