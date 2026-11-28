"""Inject optional analytics (GTM) and AdSense tags + ads.txt into static web/ at CI deploy time.

Keeps personal publisher IDs and ads.txt out of the public open-source repository while
preserving full AdSense / GTM functionality on official deployed sites.

Environment variables (read from GitHub Actions Secrets):
  GTM_CONTAINER_ID   Google Tag Manager container ID (optional)
  ADSENSE_CLIENT_ID  Google AdSense publisher client ID (optional)
  ADSENSE_ADS_TXT    full ads.txt line(s) (optional)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

HEAD_MARKER = "<!-- INJECT_HEAD_TRACKING -->"
BODY_MARKER = "<!-- INJECT_BODY_NOSCRIPT -->"

_GTM_PATTERN = re.compile(r"^GTM-[A-Z0-9]{4,20}$")
_ADSENSE_PATTERN = re.compile(r"^ca-pub-\d{10,24}$")


def build_head_snippet(gtm_id: str, adsense_client: str) -> str:
    parts: list[str] = []

    if gtm_id or adsense_client:
        hints = []
        if gtm_id:
            hints.append('  <link rel="preconnect" href="https://www.googletagmanager.com" crossorigin />')
        if adsense_client:
            hints.append('  <link rel="dns-prefetch" href="https://pagead2.googlesyndication.com" />')
        parts.append("  <!-- Performance hints for analytics & ads -->\n" + "\n".join(hints))

    if gtm_id:
        parts.append(
            "  <!-- Google Tag Manager + gtag dataLayer bridge -->\n"
            "  <script>\n"
            "    window.dataLayer = window.dataLayer || [];\n"
            "    function gtag(){dataLayer.push(arguments);}\n"
            "    window.dataLayer.push({'gtm.start': new Date().getTime(), event: 'gtm.js'});\n"
            "    gtag('js', new Date());\n"
            "  </script>\n"
            f'  <script async src="https://www.googletagmanager.com/gtm.js?id={gtm_id}"></script>'
        )

    if adsense_client:
        parts.append(
            "  <!-- Google AdSense -->\n"
            f'  <meta name="google-adsense-account" content="{adsense_client}" />\n'
            f'  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={adsense_client}" crossorigin="anonymous"></script>'
        )

    return "\n\n".join(parts)


def build_body_noscript(gtm_id: str) -> str:
    if not gtm_id:
        return ""
    return (
        "  <!-- Google Tag Manager (noscript) -->\n"
        f'  <noscript><iframe src="https://www.googletagmanager.com/ns.html?id={gtm_id}" '
        'height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>'
    )


def inject_site_tags(
    web_dir: Path,
    *,
    gtm_id: str = "",
    adsense_client: str = "",
    ads_txt_content: str = "",
) -> dict[str, int | bool]:
    """Inject GTM/AdSense snippets into all index.html pages (skipping 404.html) and write ads.txt."""
    gtm = gtm_id.strip()
    ads = adsense_client.strip()
    ads_txt = ads_txt_content.strip()

    if gtm and not _GTM_PATTERN.match(gtm):
        raise ValueError("Invalid GTM_CONTAINER_ID format")
    if ads and not _ADSENSE_PATTERN.match(ads):
        raise ValueError("Invalid ADSENSE_CLIENT_ID format")

    head_snippet = build_head_snippet(gtm, ads)
    body_snippet = build_body_noscript(gtm)

    updated_pages = 0
    for html_file in sorted(web_dir.rglob("*.html")):
        if html_file.name.lower() == "404.html":
            continue
        text = html_file.read_text(encoding="utf-8")
        if HEAD_MARKER not in text and BODY_MARKER not in text:
            continue
        new_text = text.replace(HEAD_MARKER, head_snippet).replace(BODY_MARKER, body_snippet)
        html_file.write_text(new_text, encoding="utf-8")
        updated_pages += 1

    ads_written = False
    ads_path = web_dir / "ads.txt"
    if ads_txt:
        ads_path.write_text(ads_txt + "\n", encoding="utf-8")
        ads_written = True
    elif ads_path.exists():
        ads_path.unlink()

    return {
        "updated_pages": updated_pages,
        "gtm_enabled": bool(gtm),
        "adsense_enabled": bool(ads),
        "ads_txt_written": ads_written,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inject CI-managed GTM/AdSense tags and ads.txt into web/.")
    parser.add_argument("--web-dir", default="web", help="Target static web directory (default: web)")
    args = parser.parse_args(argv)

    result = inject_site_tags(
        Path(args.web_dir),
        gtm_id=os.environ.get("GTM_CONTAINER_ID", ""),
        adsense_client=os.environ.get("ADSENSE_CLIENT_ID", ""),
        ads_txt_content=os.environ.get("ADSENSE_ADS_TXT", ""),
    )
    print(
        f"Site tags processed: pages={result['updated_pages']} "
        f"gtm={result['gtm_enabled']} adsense={result['adsense_enabled']} "
        f"ads_txt={result['ads_txt_written']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
