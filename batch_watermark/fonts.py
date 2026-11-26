"""System font discovery and cached Pillow font loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys
from PIL import ImageFont


# Curated friendly font labels mapped to candidate filenames (Windows / macOS / Linux)
_CURATED_FONT_CANDIDATES: list[tuple[str, tuple[str, ...]]] = [
    ("微软雅黑", ("msyh.ttc", "msyh.ttf")),
    ("微软雅黑 粗体", ("msyhbd.ttc", "msyhbd.ttf")),
    ("黑体", ("simhei.ttf",)),
    ("宋体", ("simsun.ttc", "simsun.ttf")),
    ("楷体", ("simkai.ttf", "STKAITI.TTF")),
    ("仿宋", ("simfang.ttf", "STFANGSO.TTF")),
    ("等线", ("Deng.ttf",)),
    ("等线 粗体", ("Dengb.ttf",)),
    ("Segoe UI", ("segoeui.ttf",)),
    ("Segoe UI Bold", ("segoeuib.ttf",)),
    ("Arial", ("arial.ttf", "Arial.ttf")),
    ("Arial Bold", ("arialbd.ttf", "Arial Bold.ttf")),
    ("Calibri", ("calibri.ttf",)),
    ("Calibri Bold", ("calibrib.ttf",)),
    ("PingFang SC", ("PingFang.ttc",)),
    ("Noto Sans CJK", ("NotoSansCJK-Regular.ttc", "NotoSansSC-Regular.otf")),
    ("DejaVu Sans", ("DejaVuSans.ttf",)),
]


def _font_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        dirs.append(Path("C:/Windows/Fonts"))
        local_fonts = Path.home() / "AppData/Local/Microsoft/Windows/Fonts"
        if local_fonts.exists():
            dirs.append(local_fonts)
    elif sys.platform == "darwin":
        dirs.extend([
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
        ])
    else:
        dirs.extend([
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".local/share/fonts",
        ])
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=1)
def discover_system_fonts() -> dict[str, str]:
    """Return an ordered mapping of {display_name: absolute_font_path}."""
    search_dirs = _font_search_dirs()
    # Index files in top-level font directories (case-insensitive)
    index: dict[str, Path] = {}
    for folder in search_dirs:
        try:
            for item in folder.iterdir():
                if item.is_file() and item.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                    index.setdefault(item.name.lower(), item)
        except OSError:
            continue

    found: dict[str, str] = {}
    for display_name, filenames in _CURATED_FONT_CANDIDATES:
        for fname in filenames:
            match = index.get(fname.lower())
            if match is not None:
                found[display_name] = str(match)
                break

    # Fallback: if none of the curated fonts exist (e.g. minimal Linux), pick up to 10 discovered fonts
    if not found:
        for fname, path in list(index.items())[:10]:
            found[path.stem] = str(path)

    return found


def resolve_font_path(font_name: str, custom_font_path: str = "") -> str | None:
    """Resolve a font path from custom path or system font catalog."""
    if custom_font_path:
        p = Path(custom_font_path)
        if p.is_file():
            return str(p)

    fonts = discover_system_fonts()
    if font_name in fonts:
        return fonts[font_name]

    # Fallback to first available system font
    if fonts:
        return next(iter(fonts.values()))
    return None


@lru_cache(maxsize=256)
def load_truetype_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load and cache a TrueType/OpenType font at a given pixel size."""
    clamped_size = max(6, min(int(round(size)), 2000))
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=clamped_size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=clamped_size)
    except TypeError:
        return ImageFont.load_default()
