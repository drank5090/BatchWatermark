"""Application bootstrap entry point for BatchWatermark."""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from batch_watermark import __version__
from batch_watermark.i18n import detect_system_locale, load_saved_locale, set_locale
from batch_watermark.ui.main_window import MainWindow
from batch_watermark.ui.theme import STUDIO_DARK_QSS


def resource_path(relative_path: str) -> Path:
    """Resolve resource path across source checkouts, editable installs, and PyInstaller bundles."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / relative_path)
    pkg_root = Path(__file__).resolve().parent.parent
    candidates.append(pkg_root / relative_path)
    candidates.append(Path.cwd() / relative_path)
    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    if "--version" in args[1:]:
        print(f"BatchWatermark {__version__}")
        return 0

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(args)
    app.setApplicationName("BatchWatermark")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("BatchWatermark")
    app.setStyle("Fusion")
    app.setStyleSheet(STUDIO_DARK_QSS)

    icon_file = resource_path("assets/app_icon.ico")
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))

    saved_loc = load_saved_locale()
    set_locale(saved_loc if saved_loc else detect_system_locale(), persist=False)

    initial_paths = [Path(p) for p in args[1:] if not p.startswith("-") and Path(p).exists()]
    window = MainWindow(initial_paths=initial_paths)
    window.show()

    return app.exec()
