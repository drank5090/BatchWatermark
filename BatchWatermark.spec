# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building standalone BatchWatermark.exe (Images + Videos + FFmpeg)."""

from pathlib import Path
import imageio_ffmpeg

ROOT = Path(SPECPATH)
ICON_PATH = ROOT / "assets" / "app_icon.ico"
FFMPEG_SRC = Path(imageio_ffmpeg.get_ffmpeg_exe())

# Exclude heavy unrelated libraries and unused PySide6 modules to keep the .exe lean
EXCLUDES = [
    "torch",
    "torchvision",
    "transformers",
    "scipy",
    "sklearn",
    "scikit-learn",
    "numpy",
    "matplotlib",
    "pandas",
    "cv2",
    "ultralytics",
    "chromadb",
    "faiss",
    "fastapi",
    "flask",
    "django",
    "sqlalchemy",
    "weasyprint",
    "pytest",
    "unittest",
    "tkinter",
    "tcl",
    "tk",
    "IPython",
    "jupyter",
    "PyQt5",
    "PyQt6",
    # Unused PySide6 modules
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtConcurrent",
    "PySide6.QtDataVisualization",
    "PySide6.QtDBus",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]

# Bundle standalone ffmpeg.exe under bin/ffmpeg.exe for zero-dependency video watermarking
EXTRA_BINARIES = []
if FFMPEG_SRC.is_file():
    EXTRA_BINARIES.append((str(FFMPEG_SRC), "bin"))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=EXTRA_BINARIES,
    datas=[(str(ICON_PATH), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)

# Normalize bundled ffmpeg binary target name to bin/ffmpeg.exe so find_ffmpeg_executable() locates it directly
normalized_binaries = []
for dest, src, kind in a.binaries:
    if Path(src).resolve() == FFMPEG_SRC.resolve():
        normalized_binaries.append(("bin\\ffmpeg.exe", src, kind))
    else:
        normalized_binaries.append((dest, src, kind))

_DROP_BINARY_FRAGMENTS = (
    "opengl32sw.dll",
    "d3dcompiler_",
    "qt6pdf",
    "qt6quick",
    "qt6qml",
    "qt6network",
    "qt6virtualkeyboard",
    "qt6svg",
    "qsvgicon",
    "qsvg",
    "qpdf",
    "qgif",
)

a.binaries = [
    b for b in normalized_binaries
    if not any(frag in b[0].lower() for frag in _DROP_BINARY_FRAGMENTS)
]

a.datas = [
    d for d in a.datas
    if "translations" not in d[0].lower()
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BatchWatermark",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
)
