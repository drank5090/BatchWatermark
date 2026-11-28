"""Unit, GUI, and multi-language SEO tests for BatchWatermark i18n (zh-CN / en / ja / zh-Hant)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from batch_watermark.creative_library import CreativeLibraryStore
from batch_watermark.i18n import (
    get_locale,
    load_saved_locale,
    normalize_locale,
    save_locale,
    set_locale,
    t,
)
from batch_watermark.i18n_data import SUPPORTED_LOCALES
from batch_watermark.presets import PresetStore
from batch_watermark.ui.main_window import MainWindow
from batch_watermark.ui.theme import STUDIO_DARK_QSS
from scripts.deploy_safeline import collect_web_assets
from scripts.inject_site_tags import BODY_MARKER, HEAD_MARKER, inject_site_tags

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STUDIO_DARK_QSS)
    return app


def test_strict_no_sensitive_terms_or_legacy_region_codes() -> None:
    """Verify strictly zero forbidden terms, legacy region codes, or hardcoded publisher/GTM IDs."""
    bad_patterns = [
        re.compile(r"\u53f0\u6e7e|\u53f0\u7063|\u81fa\u7063"),
        re.compile(r"zh[-_]tw", re.IGNORECASE),
        re.compile(r"hreflang\s*=\s*['\"][^'\"]*tw", re.IGNORECASE),
        re.compile(r"(?:ca-)?pub-\d{10,}", re.IGNORECASE),
        re.compile(r"\bGTM-[A-Z0-9]{4,}\b"),
    ]
    scan_roots = [ROOT / "batch_watermark", ROOT / "web", ROOT / "scripts", ROOT / "tests"]
    violations: list[str] = []
    for base in scan_roots:
        for fp in base.rglob("*"):
            if not fp.is_file() or fp.suffix.lower() in {".png", ".ico", ".jpg", ".webp", ".pyc"}:
                continue
            if "__pycache__" in fp.parts or fp.name == "test_i18n_and_seo.py":
                continue
            txt = fp.read_text(encoding="utf-8", errors="ignore")
            for pat in bad_patterns:
                if pat.search(txt):
                    violations.append(f"{fp.relative_to(ROOT)}: matched {pat.pattern}")
    assert not (WEB_DIR / "ads.txt").exists(), "web/ads.txt must be CI-injected, not committed"
    assert not violations, f"Forbidden terms/codes/IDs found: {violations}"


def test_desktop_i18n_translations_and_persistence(tmp_path: Path) -> None:
    assert [c for c, _, _ in SUPPORTED_LOCALES] == ["zh-CN", "en", "ja", "zh-Hant"]
    assert normalize_locale("zh_Hant") == "zh-Hant"
    assert normalize_locale("ja_JP") == "ja"
    assert normalize_locale("en_US") == "en"

    assert t("✨ 创作模式", "en") == "✨ Creative Mode"
    assert t("✨ 创作模式", "ja") == "✨ クリエイティブ"
    assert t("✨ 创作模式", "zh-Hant") == "✨ 創作模式"
    assert t("共 5 项 · 横3 / 竖2", "en") == "5 items · 3L / 2P"
    assert t("共 5 项 · 横3 / 竖2", "ja") == "5 件 · 横3 / 縦2"
    assert t("12 层", "en") == "12 layers"

    settings_file = tmp_path / "settings.json"
    save_locale("ja", settings_path=settings_file)
    assert load_saved_locale(settings_path=settings_file) == "ja"


def test_desktop_mainwindow_live_language_switching(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    settings_file = tmp_path / "settings.json"
    set_locale("zh-CN", persist=False)

    win = MainWindow(
        preset_store=PresetStore(storage_path=tmp_path / "presets.json"),
        creative_library_store=CreativeLibraryStore(storage_path=tmp_path / "creative.json"),
        settings_path=settings_file,
    )
    win.show()
    try:
        assert win._btn_mode_work.text() == "🛠️ 工作模式"
        assert win._btn_mode_creative.text() == "✨ 创作模式"

        win.set_language("en", persist=True)
        QCoreApplication.processEvents()
        assert get_locale() == "en"
        assert win._btn_mode_work.text() == "🛠️ Work Mode"
        assert win._btn_mode_creative.text() == "✨ Creative Mode"
        assert load_saved_locale(settings_path=settings_file) == "en"

        win.set_language("ja", persist=True)
        QCoreApplication.processEvents()
        assert win._btn_mode_work.text() == "🛠️ ワークモード"
        assert win._btn_mode_creative.text() == "✨ クリエイティブ"

        win.set_language("zh-Hant", persist=True)
        QCoreApplication.processEvents()
        assert win._btn_mode_creative.text() == "✨ 創作模式"

        # Restore back to zh-CN cleanly so subsequent tests keep default locale
        win.set_language("zh-CN", persist=False)
        QCoreApplication.processEvents()
        assert win._btn_mode_creative.text() == "✨ 创作模式"
    finally:
        set_locale("zh-CN", persist=False)
        win.close()


def test_web_multilingual_seo_pages_hreflang_sitemap_and_safeline_assets() -> None:
    expected_pages = {
        "zh-CN": (WEB_DIR / "index.html", "https://watermark.zak-cloud.top/", "zh_CN", ""),
        "en": (WEB_DIR / "en" / "index.html", "https://watermark.zak-cloud.top/en/", "en_US", "../"),
        "ja": (WEB_DIR / "ja" / "index.html", "https://watermark.zak-cloud.top/ja/", "ja_JP", "../"),
        "zh-Hant": (WEB_DIR / "zh-hant" / "index.html", "https://watermark.zak-cloud.top/zh-hant/", "zh_Hant", "../"),
    }

    for loc, (fp, canonical, og_loc, prefix) in expected_pages.items():
        assert fp.is_file(), f"Missing localized SEO page: {fp}"
        text = fp.read_text(encoding="utf-8")

        assert f'<html lang="{loc}">' in text
        assert f'<link rel="canonical" href="{canonical}" />' in text
        assert f'<meta property="og:locale" content="{og_loc}" />' in text

        # Bidirectional hreflang cluster on every page
        for hl, href in (
            ("zh-CN", "https://watermark.zak-cloud.top/"),
            ("en", "https://watermark.zak-cloud.top/en/"),
            ("ja", "https://watermark.zak-cloud.top/ja/"),
            ("zh-Hant", "https://watermark.zak-cloud.top/zh-hant/"),
            ("x-default", "https://watermark.zak-cloud.top/"),
        ):
            assert f'<link rel="alternate" hreflang="{hl}" href="{href}" />' in text

        # Relative assets & script paths work on both custom root & GitHub Pages subpath
        assert f'href="{prefix}styles.css"' in text
        assert f'src="{prefix}js/app.js"' in text

        # Clean CI injection placeholders (no hardcoded personal GTM/AdSense IDs in public repo)
        assert HEAD_MARKER in text
        assert BODY_MARKER in text
        assert "gtm.js?id=" not in text
        assert "adsbygoogle.js?client=" not in text

        # Valid localized JSON-LD @graph
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
        assert m, f"Missing JSON-LD in {fp}"
        ld = json.loads(m.group(1))
        types = {node["@type"] for node in ld["@graph"]}
        assert types == {"WebSite", "WebApplication", "HowTo", "FAQPage", "BreadcrumbList"}

    # Validate multilingual sitemap.xml with xhtml:link alternates
    sitemap_tree = ET.parse(WEB_DIR / "sitemap.xml")
    sitemap_xml = (WEB_DIR / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap_tree.getroot().tag.endswith("urlset")
    for url in (
        "https://watermark.zak-cloud.top/",
        "https://watermark.zak-cloud.top/en/",
        "https://watermark.zak-cloud.top/ja/",
        "https://watermark.zak-cloud.top/zh-hant/",
    ):
        assert f"<loc>{url}</loc>" in sitemap_xml
        assert f'href="{url}"' in sitemap_xml

    # Validate SafeLine WAF deploy script automatically picks up /en, /ja, /zh-hant
    dirs, files = collect_web_assets(WEB_DIR)
    for d in ("/en", "/ja", "/zh-hant"):
        assert d in dirs
    file_paths = {rp for rp, _ in files}
    for rp in ("/index.html", "/en/index.html", "/ja/index.html", "/zh-hant/index.html", "/js/i18n.js", "/js/i18n-data.js"):
        assert rp in file_paths


def test_ci_site_tag_injection_and_fork_clean_strip(tmp_path: Path) -> None:
    """Verify inject_site_tags injects GTM/AdSense/ads.txt in CI and strips cleanly for forks."""
    sample_web = tmp_path / "web"
    (sample_web / "en").mkdir(parents=True)
    for rel in ("index.html", "en/index.html"):
        (sample_web / rel).write_text(
            f"<html><head>{HEAD_MARKER}</head><body>{BODY_MARKER}<main/></body></html>",
            encoding="utf-8",
        )
    (sample_web / "404.html").write_text(
        f"<html><head>{HEAD_MARKER}</head><body>404</body></html>",
        encoding="utf-8",
    )

    # 1. With CI secrets configured -> injects deduplicated tags & writes ads.txt, skips 404.html
    res = inject_site_tags(
        sample_web,
        gtm_id="GTM-TEST1234",
        adsense_client="ca-pub-1234567890123456",
        ads_txt_content="google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0",
    )
    assert res == {"updated_pages": 2, "gtm_enabled": True, "adsense_enabled": True, "ads_txt_written": True}
    for rel in ("index.html", "en/index.html"):
        txt = (sample_web / rel).read_text(encoding="utf-8")
        assert txt.count("gtm.js?id=GTM-TEST1234") == 1
        assert txt.count("ns.html?id=GTM-TEST1234") == 1
        assert txt.count("adsbygoogle.js?client=ca-pub-1234567890123456") == 1
        assert HEAD_MARKER not in txt and BODY_MARKER not in txt
    assert "adsbygoogle" not in (sample_web / "404.html").read_text(encoding="utf-8")
    assert (sample_web / "ads.txt").read_text(encoding="utf-8").strip().startswith("google.com, pub-1234567890123456")

    # 2. Fork/local build with empty env -> removes placeholders cleanly & removes ads.txt
    sample_web2 = tmp_path / "web_fork"
    sample_web2.mkdir()
    (sample_web2 / "index.html").write_text(
        f"<html><head>{HEAD_MARKER}</head><body>{BODY_MARKER}</body></html>",
        encoding="utf-8",
    )
    res2 = inject_site_tags(sample_web2)
    assert res2 == {"updated_pages": 1, "gtm_enabled": False, "adsense_enabled": False, "ads_txt_written": False}
    clean_html = (sample_web2 / "index.html").read_text(encoding="utf-8")
    assert HEAD_MARKER not in clean_html and BODY_MARKER not in clean_html
    assert not (sample_web2 / "ads.txt").exists()
