"""Generate Web i18n data bundle, static localized SEO pages (/en/, /ja/, /zh-hant/),
multi-language hreflang sitemap.xml, and multilingual GEO llms.txt.

Strictly uses BCP-47 standard codes: zh-CN, en, ja, zh-Hant.
"""

from __future__ import annotations

from datetime import date
import html
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from batch_watermark import __version__
from batch_watermark.i18n import translate_text
from batch_watermark.i18n_data import REGEX_TRANSLATIONS, SUPPORTED_LOCALES, TRANSLATIONS

WEB_DIR = ROOT / "web"
PRIMARY_ORIGIN = "https://watermark.zak-cloud.top"
MIRROR_ORIGIN = "https://drank5090.github.io/BatchWatermark"
REPO_URL = "https://github.com/drank5090/BatchWatermark"

LOCALE_URLS = {
    "zh-CN": f"{PRIMARY_ORIGIN}/",
    "en": f"{PRIMARY_ORIGIN}/en/",
    "ja": f"{PRIMARY_ORIGIN}/ja/",
    "zh-Hant": f"{PRIMARY_ORIGIN}/zh-hant/",
}

OG_LOCALES = {
    "zh-CN": "zh_CN",
    "en": "en_US",
    "ja": "ja_JP",
    "zh-Hant": "zh_Hant",
}

# Full handcrafted SEO metadata + localized crawlable #guide content per locale
SEO_PACKS: dict[str, dict] = {
    "zh-CN": {
        "title": "BatchWatermark 在线批量加水印工具 · 免费图片与视频添加文字/Logo水印（零上传）",
        "description": "BatchWatermark（watermark.zak-cloud.top）是免费开源、100% 浏览器本地运行的双模式在线批量加水印工具：工作模式支持多张图片与视频实时预览、横竖版隔离导出与 JSON 预设；创作模式支持图文水印库、智能避让主体多尺度艺术排版与自由拖拽精修。",
        "keywords": "批量加水印,在线加水印,图片加水印,视频加水印,艺术水印,画师防盗水印,免费加水印工具,Logo水印,文字水印,平铺水印,防盗图水印,本地加水印,不上传图片加水印,横竖版水印,BatchWatermark",
        "og_title": "BatchWatermark · 免费在线批量图片视频加水印 & 艺术水印创作（零上传）",
        "og_desc": "100% 浏览器本地运行、绝不上传服务器：工作模式批量处理图片与视频，创作模式支持图文水印库、智能避让人物多尺度艺术排版与自由拖拽。",
        "og_alt": "BatchWatermark 在线批量加水印工具与创作模式艺术水印界面",
        "app_name": "BatchWatermark 在线批量加水印工具",
        "alt_names": ["BatchWatermark Web", "在线批量加水印工具", "艺术水印创作工具"],
        "price_currency": "CNY",
        "breadcrumb_home": "BatchWatermark 首页",
        "howto_name": "如何使用 BatchWatermark 在线批量给图片和视频加水印",
        "howto_desc": "无需安装软件、不上传文件，4 步在浏览器本地完成工作模式批量水印或创作模式艺术水印。",
        "howto_tool": "现代浏览器（Chrome / Edge / Safari / Firefox）",
        "howto_steps": [
            ("选择工作模式或创作模式", "在顶部标签栏切换「工作模式」（高效批量图片/视频、平铺/九宫格、横竖隔离）或「创作模式」（图文水印库、自动避让主体多尺度艺术排版、自由拖拽）。"),
            ("导入图片、视频或水印素材", "支持多选文件、导入整个文件夹或直接拖拽进入画布；创作模式还可上传透明 PNG 贴纸与多行文字组建本机持久化水印库。"),
            ("实时预览与精细调整", "工作模式所有图片与视频帧同步实时刷新；创作模式可一键「智能排版 / 换一版」，并直接拖拽、缩放、旋转或锁定任意单个水印。"),
            ("一键本地高清导出", "支持单文件直下、零依赖 UTF-8 ZIP 批量打包导出，或在 Chrome/Edge 中直接写入本地目录，全程零服务器上传。"),
        ],
        "features_ld": [
            "100% 浏览器本地内存运算，图片与视频零上传服务器",
            "双模式独立标签切换：工作模式（批量图片/视频）与创作模式（艺术水印/自由拖拽）",
            "创作模式支持图文水印库、显著度主体避让算法、大小错落自动排版与单层拖拽缩放旋转",
            "工作模式支持多图与视频帧同步实时预览、平铺防盗、九宫格定位与横竖版隔离分文件夹导出",
            "自定义预设与创作水印库本机持久化，支持 UTF-8 JSON 导入导出并与 Windows 桌面 EXE 互通",
            "支持单文件直下、ZIP 打包导出与 Chrome/Edge 直写本地文件夹，适配 PC 与手机端",
        ],
        "faqs": [
            ("BatchWatermark 在线加水印免费吗？需要注册登录吗？", "完全免费并基于 MIT 协议开源，无需注册登录、无张数限制、无强制品牌角标，打开 watermark.zak-cloud.top 或 GitHub Pages 镜像即可直接使用。"),
            ("我的图片和视频会被上传到服务器吗？", "绝不会上传。图片解码、Canvas 水印绘制、创作模式显著度计算、MediaRecorder 视频合成与 ZIP 打包全部在您的浏览器本地内存中完成，没有任何文件上传接口。"),
            ("工作模式和创作模式有什么区别？", "工作模式专注高效批量给图片和视频加文字/Logo 平铺或九宫格水印，并支持横竖隔离导出；创作模式面向插画、摄影与约稿防盗，支持上传图文水印库、算法自动避让主体生成大小不一的艺术排版，并可自由拖拽精修。两个模式完全独立，通过顶部标签页切换。"),
            ("支持手机端使用吗？", "支持。网页版针对 iOS Safari 与 Android 浏览器做了专属移动端布局优化：顶部固定实时预览/交互画布，下方通过分类标签切换参数，单图支持直接下载保存到手机。"),
            ("支持哪些图片和视频格式？可以导出什么格式？", "图片支持 JPG / JPEG / PNG / WebP / BMP / GIF / AVIF，可保持原格式或转换为 JPEG、PNG、WebP 并调节质量；视频支持 MP4 / WebM / MOV，通过浏览器本地 MediaRecorder 导出 MP4 或 WebM 并保留原声。"),
            ("横版和竖版图片可以使用不同的水印并分开导出吗？", "可以。在工作模式点击顶部「横竖隔离」，预览区自动分为横版区（宽 ≥ 高）和竖版区（高 > 宽），支持独立参数，导出时自动归入「横版/」和「竖版/」子文件夹。"),
            ("创作模式的水印库可以跨设备或与桌面版互通吗？", "可以。创作模式水印库自动保存在浏览器本地 IndexedDB 中，并支持导出为标准 UTF-8 JSON 文件包，与 Windows 桌面 EXE 版 100% 双向导入导出互通。"),
            ("需要处理大量高清长视频，有离线桌面版吗？", "有。BatchWatermark 提供基于 Python、PySide6 与内置 FFmpeg 的 Windows 独立单文件 EXE，同样内置工作模式与创作模式及四语言切换，可在 GitHub Releases 免费下载。"),
        ],
    },
    "en": {
        "title": "BatchWatermark — Free Online Batch Image & Video Watermark Tool & Creative Studio (100% Local)",
        "description": "Free, open-source, 100% client-side batch watermark tool for photos and videos. Zero uploads. Switch between Work Mode (bulk tiled/anchor watermarking, video audio, landscape/portrait split) and Creative Mode (sticker & text library, subject-aware multi-scale auto layout, drag/resize/rotate canvas).",
        "keywords": "batch watermark online,free watermark tool,watermark photos online,watermark video online,client-side watermark,no upload watermark,tiled watermark,logo watermark,art watermark generator,illustration anti-theft watermark,BatchWatermark",
        "og_title": "BatchWatermark — Free Online Batch Photo & Video Watermarking + Creative Art Studio",
        "og_desc": "100% browser-local processing with zero server uploads. Bulk-watermark images & videos in Work Mode, or design varied-size art watermarks with subject avoidance and free drag-and-drop in Creative Mode.",
        "og_alt": "BatchWatermark online batch photo/video watermark tool and Creative Mode canvas",
        "app_name": "BatchWatermark Online Batch Watermark & Creative Studio",
        "alt_names": ["BatchWatermark Web", "Free Online Batch Watermark Tool", "Creative Art Watermark Studio"],
        "price_currency": "USD",
        "breadcrumb_home": "BatchWatermark Home",
        "howto_name": "How to Batch Watermark Images and Videos Locally with BatchWatermark",
        "howto_desc": "No installation and zero server uploads — batch watermark photos/videos or design artistic multi-scale watermarks in 4 steps.",
        "howto_tool": "Modern Web Browser (Chrome, Edge, Safari, Firefox)",
        "howto_steps": [
            ("Choose Work Mode or Creative Mode", "Use the top tabs to switch between Work Mode (fast batch image/video watermarking, tiling, 3x3 anchors, orientation split) and Creative Mode (sticker + text library, smart subject-avoiding varied-size layouts, free drag/resize/rotate)."),
            ("Import Images, Videos, or Watermark Assets", "Select files, import an entire folder, or drag & drop directly. In Creative Mode, upload transparent PNG/WebP stickers and custom multi-line text into your persistent Watermark Library."),
            ("Live Preview & Fine-Tune", "Work Mode refreshes every thumbnail and video frame in real time. Creative Mode generates balanced varied-size art layouts in one click and lets you drag, resize, rotate, or lock any individual watermark."),
            ("Export Locally in One Click", "Download single files directly, export a UTF-8 ZIP bundle, or write straight into a local folder on Chrome/Edge — 100% private in browser memory."),
        ],
        "features_ld": [
            "100% browser-local execution — zero files uploaded to any server",
            "Independent Dual Modes via top tabs: Work Mode (bulk images & videos) and Creative Mode (artistic watermarks)",
            "Creative Mode: custom PNG sticker & text library, visual saliency subject avoidance, multi-scale auto-layout & interactive drag/resize/rotate canvas",
            "Work Mode: real-time multi-image & video preview, brick-staggered tiling, 3x3 anchor grid & landscape/portrait split export",
            "Local persistent presets & watermark library packs with cross-platform JSON compatibility with Windows Desktop EXE",
            "Direct single-file download, zero-dependency ZIP export, Chrome/Edge local folder writing & mobile touch UI",
        ],
        "faqs": [
            ("Is BatchWatermark free? Do I need an account?", "Yes — 100% free and MIT open-source with no login, no file count limits, and no forced branding watermarks."),
            ("Are my photos or videos uploaded to any server?", "Never. Image decoding, Canvas 2D compositing, Creative Mode saliency analysis, MediaRecorder video encoding, and ZIP creation all run strictly inside your local browser memory."),
            ("What is the difference between Work Mode and Creative Mode?", "Work Mode is built for high-speed batch watermarking of photos and videos (tiled or anchored, with landscape/portrait isolation). Creative Mode is tailored for illustrators, photographers, and creators: upload sticker & text libraries, auto-generate varied-size art watermarks that avoid faces/subjects, and drag/resize/rotate individual layers freely."),
            ("Does it work on mobile phones (iOS & Android)?", "Yes. Both Work Mode and Creative Mode adapt cleanly to mobile screens with a pinned live preview/canvas on top, touch-friendly category tabs below, and direct single-file downloads."),
            ("Which image and video formats are supported?", "Images: JPG, JPEG, PNG, WebP, BMP, GIF, and AVIF (export as original, JPEG, PNG, or WebP with quality control). Videos: MP4, WebM, and MOV exported locally with original audio preserved."),
            ("Can I apply different watermarks to landscape and portrait photos?", "Yes. Toggle 'Split Orientation' in Work Mode to separate landscape (W >= H) and portrait (H > W) items, optionally configure independent watermark settings, and auto-export into separate subfolders."),
            ("Are watermark libraries and presets compatible with the Desktop EXE?", "Yes. Both Work Mode presets and Creative Mode Watermark Library packs export as portable UTF-8 JSON files that work identically between Web and the Windows Desktop EXE."),
            ("Is there an offline desktop app for large or long HD videos?", "Yes. Download the standalone Windows single-file EXE (Python + PySide6 + bundled FFmpeg) from GitHub Releases for faster H.264 MP4 video encoding and offline batch processing."),
        ],
        "guide": {
            "eyebrow": "Free · MIT Open Source · Zero Install · 100% Local & Private",
            "hero_title": "BatchWatermark: Online Batch Photo & Video Watermarking + Creative Art Studio",
            "hero_lead": "<strong>BatchWatermark</strong> (primary domain <a href=\"https://watermark.zak-cloud.top/en/\">watermark.zak-cloud.top</a>) runs 100% inside your browser with <strong>zero server uploads</strong>. Switch cleanly between <strong>Work Mode</strong> for rapid bulk photo/video watermarking and <strong>Creative Mode</strong> for varied-size artistic anti-theft layouts with subject avoidance and free drag-and-drop editing.",
            "hero_cta": "↑ Start Watermarking Now",
            "tldr_title": "Key Specs at a Glance (TL;DR)",
            "facts": [
                ("Privacy & Security", "<strong>0 server uploads</strong> · 100% local HTML5 Canvas 2D + MediaRecorder processing"),
                ("Dual Independent Modes", "<strong>Work Mode</strong> (bulk photos & videos) + <strong>Creative Mode</strong> (art library, auto-layout & free drag)"),
                ("Supported Formats", "Images <strong>JPG / PNG / WebP / BMP / GIF / AVIF</strong> · Videos <strong>MP4 / WebM / MOV</strong>"),
                ("Orientation Split", "Auto-separates Landscape (W ≥ H) & Portrait (H &gt; W) with independent configs & subfolder export"),
                ("Cross-Platform JSON", "Local persistence (IndexedDB / localStorage) + JSON packs <strong>100% compatible with Windows EXE</strong>"),
                ("Cost & License", "<strong>100% Free</strong> · No file limits · No sign-up · MIT Open Source"),
            ],
            "feat_title": "Core Features",
            "features": [
                ("✨ Creative Mode (Art Library + Smart Auto-Layout + Free Drag)", "Upload transparent PNG stickers and multi-line text into your Watermark Library. Auto-generate varied-size artistic compositions that protect faces/subjects, then drag, resize, rotate, lock, or sync across all images."),
                ("Bulk Image & Video Watermarking", "Import dozens of photos, videos, or entire folders via picker or drag-and-drop. Auto-corrects mobile EXIF orientation and preserves original audio on video export."),
                ("Multi-Line Text & Transparent Logo Watermarks", "Load custom local <code>.ttf / .otf / .woff2</code> fonts, adjust stroke, drop shadow, line height, opacity, and angle, or scale transparent PNG/WebP logos proportionally."),
                ("Anti-Theft Tiling & 3×3 Anchor Grid", "Brick-staggered diagonal tiling resists cropping; single-anchor mode provides a 3×3 grid with percentage margins and fine X/Y offsets."),
                ("Real-Time Multi-Preview (Desktop & Mobile)", "Every parameter tweak updates all previews simultaneously. Mobile view pins the live preview/canvas above thumb-friendly tabs."),
                ("Orientation Split & Portable JSON Packs", "Separate landscape and portrait sets automatically, export into organized subfolders, and share JSON presets/libraries seamlessly with the Desktop EXE."),
            ],
            "cmp_title": "Web Edition vs. Desktop EXE vs. Cloud Watermark Sites",
            "cmp_headers": ["Dimension", "BatchWatermark Web (This Page)", "BatchWatermark Desktop EXE", "Typical Cloud Sites"],
            "cmp_rows": [
                ("Privacy & Uploads", "<strong>0 uploads</strong> · local browser RAM", "<strong>0 uploads</strong> · fully offline", "Requires uploading to remote servers"),
                ("Work + Creative Dual Mode", "<strong>Built-in</strong> (multi-scale auto + drag)", "<strong>Built-in</strong> (100% JSON compatible)", "Single basic watermark only"),
                ("Video Watermarking", "MP4 / WebM / MOV (MediaRecorder)", "MP4 / MOV / MKV / AVI (bundled FFmpeg)", "Strict size caps or paid tiers"),
                ("Batch Limits & Cost", "<strong>Free & unlimited</strong>, no login", "<strong>Free & unlimited</strong>, MIT license", "Watermarks, daily caps, or paywalls"),
            ],
            "howto_title": "4 Simple Steps to Watermark Locally",
            "use_title": "Popular Use Cases",
            "uses": [
                ("Illustrators, ACG & Commission Protection", "Use Creative Mode with snowflakes, seals, and poetic text to generate varied-size anti-theft art watermarks that frame the artwork without blocking the character's face."),
                ("E-Commerce & Photography Delivery", "Bulk-watermark product shots and client proofs with live multi-preview, custom logos, and automatic landscape/portrait subfolder export."),
                ("ID Scans & Confidential Documents", "Add 'For Verification Only' diagonal anti-theft text 100% locally in browser memory — documents never leave your device."),
            ],
            "faq_title": "Frequently Asked Questions (FAQ)",
            "footer_note": "MIT Open Source · 100% Local Processing · Multi-Language Support (简体中文 / English / 日本語 / 繁體中文)",
        },
    },
    "ja": {
        "title": "BatchWatermark — 無料オンライン画像・動画一括透かし＆アート透かし作成ツール（完全ローカル）",
        "description": "インストール不要・サーバー送信ゼロの完全ローカル一括透かし（ウォーターマーク）ツール。ワークモードで画像・動画を一括処理、クリエイティブモードで透過PNGスタンプや文字ライブラリから人物を回避した大小ランダムなアート透かしを自動生成・自由ドラッグ編集できます。",
        "keywords": "透かし 一括,ウォーターマーク 無料,画像 透かし オンライン,動画 透かし,イラスト 盗用防止 透かし,アート透かし,ローカル 透かし ツール,アップロードなし 透かし,BatchWatermark",
        "og_title": "BatchWatermark — 完全ローカル画像・動画一括透かし＆アート透かしスタジオ",
        "og_desc": "ブラウザ内完結・アップロード一切なし。画像・動画の一括透かし（ワークモード）と、イラスト・写真向けの大小ランダム自動配置＆自由ドラッグ編集（クリエイティブモード）を搭載。",
        "og_alt": "BatchWatermark オンライン画像・動画一括透かしおよびクリエイティブモード画面",
        "app_name": "BatchWatermark オンライン一括透かし＆クリエイティブスタジオ",
        "alt_names": ["BatchWatermark Web", "無料一括透かしツール", "イラスト盗用防止アート透かし"],
        "price_currency": "JPY",
        "breadcrumb_home": "BatchWatermark ホーム",
        "howto_name": "BatchWatermark で画像・動画にローカル一括透かしを入れる手順",
        "howto_desc": "インストール不要・サーバー送信ゼロ。わずか4ステップで画像・動画の一括透かしやアート透かしを作成できます。",
        "howto_tool": "モダンブラウザ（Chrome / Edge / Safari / Firefox）",
        "howto_steps": [
            ("ワークモードまたはクリエイティブモードを選択", "上部タブで「ワークモード」（画像・動画の一括タイル／9点配置・縦横分離）と「クリエイティブモード」（透過スタンプ＆文字ライブラリ・人物回避自動配置・自由ドラッグ）を切り替えます。"),
            ("画像・動画または透かし素材を読み込む", "ファイル複数選択、フォルダ読み込み、ドラッグ＆ドロップに対応。クリエイティブモードでは独自の透過PNGスタンプや複数行テキストをライブラリに保存できます。"),
            ("リアルタイムプレビューと微調整", "ワークモードは全サムネイルと動画フレームを同時更新。クリエイティブモードは「自動レイアウト／別の案」で一括生成し、個別の移動・拡縮・回転・ロックも可能です。"),
            ("ワンクリックでローカル書き出し", "単体ダウンロード、UTF-8 ZIP 一括保存、または Chrome / Edge でのローカルフォルダ直接書き出しに対応。データは外部へ送信されません。"),
        ],
        "features_ld": [
            "100% ブラウザ内ローカル処理・画像および動画のサーバーアップロードゼロ",
            "上部タブで完全独立する2モード：ワークモード（一括処理）とクリエイティブモード（アート透かし）",
            "クリエイティブモード：画像＆文字ライブラリ、人物・主体回避アルゴリズム、大小ランダム自動配置、自由ドラッグ・拡縮・回転",
            "ワークモード：複数画像・動画のリアルタイム同期プレビュー、斜めレンガ状タイル、9点アンカー、縦横分離書き出し",
            "ローカル保存プリセット＆透かし素材パック（Windows デスクトップ版 EXE と JSON 完全互換）",
            "単体保存・ZIP書き出し・ローカルフォルダ直接保存・PCおよびスマホ操作に最適化",
        ],
        "faqs": [
            ("BatchWatermark は無料ですか？アカウント登録は必要ですか？", "完全無料・MIT ライセンスのオープンソースです。登録やログインは不要で、処理枚数の上限や強制ロゴもありません。"),
            ("画像や動画がサーバーにアップロードされることはありますか？", "一切ありません。画像デコード、Canvas 2D 合成、主体回避解析、動画録画、ZIP 生成まですべてお使いのブラウザ内メモリで完結します。"),
            ("ワークモードとクリエイティブモードの違いは何ですか？", "ワークモードは大量の写真・動画に斜めタイルやロゴ透かしを素早く一括適用する用途向けです。クリエイティブモードはイラスト・同人作品・写真向けに、複数の透過PNGスタンプや文字を人物の顔を避けつつ大小バランスよく自動配置し、そのまま自由ドラッグで微調整できます。"),
            ("スマートフォン（iPhone / Android）でも使えますか？", "はい。スマホ画面ではプレビュー・編集キャンバスを上部に固定し、下部タブで直感的にパラメータや素材ライブラリを切り替えられ、1枚だけの直接保存にも対応しています。"),
            ("対応している画像・動画フォーマットは？", "画像は JPG / JPEG / PNG / WebP / BMP / GIF / AVIF に対応し、元形式維持または JPEG / PNG / WebP 書き出しが可能。動画は MP4 / WebM / MOV に対応し、音声を保持してローカル書き出しできます。"),
            ("横向き画像と縦向き画像で別々の透かし設定・別フォルダ書き出しはできますか？", "はい。ワークモード上部の「縦横分離」をオンにすると横向き（幅 ≥ 高さ）と縦向き（高さ > 幅）を自動分類し、個別設定と別サブフォルダ出力が行えます。"),
            ("作成した透かしライブラリやプリセットはデスクトップ版と共有できますか？", "はい。ブラウザ内（IndexedDB / localStorage）に自動保存されるほか、UTF-8 JSON パックとして書き出し、Windows デスクトップ EXE 版と双方向に読み込めます。"),
            ("長時間の高画質動画を大量処理したい場合、オフライン版はありますか？", "はい。Python + PySide6 + FFmpeg 内蔵の Windows 単体実行 EXE 版を GitHub Releases で無料配布しており、ワーク＆クリエイティブ両モードと4言語切替に対応しています。"),
        ],
        "guide": {
            "eyebrow": "無料 · MIT オープンソース · インストール不要 · 完全ローカル処理",
            "hero_title": "BatchWatermark：画像・動画の一括透かし＆イラスト向けアート透かし作成",
            "hero_lead": "<strong>BatchWatermark</strong>（公式サイト <a href=\"https://watermark.zak-cloud.top/ja/\">watermark.zak-cloud.top</a>）はブラウザ内で完結する無料の<strong>画像・動画一括透かしツール</strong>です。サーバーへのファイル送信は<strong>一切ゼロ</strong>。高速な一括処理の<strong>ワークモード</strong>と、透過スタンプ＆文字を人物回避しながら大小ランダム配置できる<strong>クリエイティブモード</strong>を上部タブで自在に切り替えられます。",
            "hero_cta": "↑ ツールに戻って透かしを作成",
            "tldr_title": "主な仕様（TL;DR）",
            "facts": [
                ("プライバシー保護", "<strong>アップロード 0 回</strong> · 100% ブラウザ内 HTML5 Canvas + MediaRecorder 処理"),
                ("独立した2つのモード", "<strong>ワークモード</strong>（写真・動画一括）＋ <strong>クリエイティブモード</strong>（素材庫・自動配置・自由ドラッグ）"),
                ("対応フォーマット", "画像 <strong>JPG / PNG / WebP / BMP / GIF / AVIF</strong> · 動画 <strong>MP4 / WebM / MOV</strong>"),
                ("縦横分離書き出し", "横向き（幅 ≥ 高さ）と縦向き（高さ &gt; 幅）を自動分類し、個別設定・別フォルダ出力"),
                ("デスクトップ版と完全互換", "ローカル自動保存 ＋ UTF-8 JSON パックで <strong>Windows EXE 版と100%互換</strong>"),
                ("料金・ライセンス", "<strong>完全無料</strong> · 枚数制限なし · ログイン不要 · MIT オープンソース"),
            ],
            "feat_title": "主要機能",
            "features": [
                ("✨ クリエイティブモード（イラスト・作品向けアート透かし）", "透過 PNG スタンプと複数行テキストをライブラリ登録。顔や主体を回避しつつ大小メリハリのあるアート透かしを自動生成し、個別の移動・拡縮・回転・ロックや全画像への一括適用ができます。"),
                ("画像・動画の一括透かし処理", "複数ファイルやフォルダ丸ごとのドラッグ＆ドロップに対応。スマホ写真の EXIF 向きを自動補正し、動画は元の音声を保ったまま書き出せます。"),
                ("多行テキスト＆透過ロゴ透かし", "ローカルの <code>.ttf / .otf / .woff2</code> フォント読み込み、縁取り、影、行間、透明度・角度調整に対応。透過 PNG / WebP ロゴも比率維持で配置可能。"),
                ("盗用防止タイル＆9点アンカー配置", "レンガ状に互い違い配置する斜め全面タイルで切り抜きを防止。単点配置では 3×3 アンカーと余白・オフセット微調整に対応。"),
                ("複数同時プレビュー（PC・スマホ最適化）", "パラメータ変更が全プレビューへ即座に反映。スマホではキャンバス固定＋下部タブ操作で片手でも快適です。"),
                ("縦横分離＆JSON プリセット共有", "横長・縦長を分けて設定・書き出し可能。プリセットと透かし素材庫は JSON でデスクトップ版と自在にやり取りできます。"),
            ],
            "cmp_title": "Web 版 vs デスクトップ EXE 版 vs 一般的なクラウド型サイト",
            "cmp_headers": ["比較項目", "BatchWatermark Web（本サイト）", "BatchWatermark デスクトップ EXE", "一般的なオンライン透かしサイト"],
            "cmp_rows": [
                ("データ送信・安全性", "<strong>送信ゼロ</strong> · ローカルメモリ完結", "<strong>送信ゼロ</strong> · 完全オフライン", "外部サーバーへのアップロード必須"),
                ("ワーク＋クリエイティブ両対応", "<strong>標準搭載</strong>（自動配置＋自由ドラッグ）", "<strong>標準搭載</strong>（JSON 完全互換）", "単純な単一透かしのみ"),
                ("動画透かし対応", "MP4 / WebM / MOV（ブラウザ録画）", "MP4 / MOV / MKV / AVI（FFmpeg内蔵）", "容量制限や有料プランが必要"),
                ("利用制限・料金", "<strong>完全無料・無制限</strong>・登録不要", "<strong>完全無料・無制限</strong>・MIT公開", "枚数上限・強制ロゴ・課金あり"),
            ],
            "howto_title": "4ステップで完了する使い方",
            "use_title": "おすすめの活用シーン",
            "uses": [
                ("イラスト・同人・コミッションの盗用防止", "クリエイティブモードで雪の結晶・スタンプ・詩的な署名テキストを人物の顔を避けて美しく自動配置し、無断転載やAI学習対策に活用できます。"),
                ("EC 商品画像・写真納品の一括処理", "ワークモードで数十〜数百枚の商品写真やサンプル画像を同時プレビューし、横向き・縦向き別フォルダで一気に納品準備。"),
                ("本人確認書類・社内資料の保護", "「提出専用・複製禁止」などの斜め透かしを完全ローカルで追加。機密画像が外部ネットワークに出ることはありません。"),
            ],
            "faq_title": "よくある質問（FAQ）",
            "footer_note": "MIT オープンソース · 完全ローカル処理 · 多言語対応（简体中文 / English / 日本語 / 繁體中文）",
        },
    },
    "zh-Hant": {
        "title": "BatchWatermark 線上批次加浮水印工具 · 免費圖片與影片加文字/Logo浮水印（零上傳）",
        "description": "BatchWatermark（watermark.zak-cloud.top）是免費開源、100% 瀏覽器本機運行的雙模式線上批次加浮水印工具：工作模式支援多張圖片與影片即時預覽、橫豎版隔離匯出與 JSON 預設；創作模式支援圖文浮水印庫、智慧避讓主體多尺度藝術排版與自由拖曳精修。",
        "keywords": "批次加浮水印,線上加浮水印,圖片加浮水印,影片加浮水印,藝術浮水印,畫師防盜浮水印,免費浮水印工具,Logo浮水印,文字浮水印,平鋪浮水印,防盜圖浮水印,本機加浮水印,不上傳圖片加浮水印,BatchWatermark",
        "og_title": "BatchWatermark · 免費線上批次圖片影片加浮水印 & 藝術浮水印創作（零上傳）",
        "og_desc": "100% 瀏覽器本機運算、絕不上傳伺服器：工作模式高效批次處理圖片與影片，創作模式支援圖文浮水印庫、智慧避讓人物多尺度藝術排版與自由拖曳。",
        "og_alt": "BatchWatermark 線上批次加浮水印工具與創作模式藝術浮水印介面",
        "app_name": "BatchWatermark 線上批次加浮水印工具",
        "alt_names": ["BatchWatermark Web", "線上批次加浮水印工具", "藝術浮水印創作工具"],
        "price_currency": "USD",
        "breadcrumb_home": "BatchWatermark 首頁",
        "howto_name": "如何使用 BatchWatermark 線上批次為圖片和影片加上浮水印",
        "howto_desc": "免安裝軟體、絕不上傳檔案，4 步驟在瀏覽器本機完成工作模式批次浮水印或創作模式藝術浮水印。",
        "howto_tool": "現代瀏覽器（Chrome / Edge / Safari / Firefox）",
        "howto_steps": [
            ("選擇工作模式或創作模式", "在頂部分頁切換「工作模式」（高效批次圖片/影片、平鋪/九宮格、橫豎隔離）或「創作模式」（圖文浮水印庫、自動避讓主體多尺度藝術排版、自由拖曳）。"),
            ("匯入圖片、影片或浮水印素材", "支援多選檔案、匯入整個資料夾或直接拖曳進入畫布；創作模式還可上傳透明 PNG 貼紙與多行文字建立本機持久化浮水印庫。"),
            ("即時預覽與精細微調", "工作模式所有圖片與影片幀同步即時刷新；創作模式可一鍵「智慧排版 / 換一版」，並直接拖曳、縮放、旋轉或鎖定任意單一浮水印。"),
            ("一鍵本機高畫質匯出", "支援單檔直接下載、零依賴 UTF-8 ZIP 批次打包匯出，或在 Chrome/Edge 直接寫入本機資料夾，全程零伺服器上傳。"),
        ],
        "features_ld": [
            "100% 瀏覽器本機記憶體運算，圖片與影片零上傳伺服器",
            "雙模式獨立分頁切換：工作模式（批次圖片/影片）與創作模式（藝術浮水印/自由拖曳）",
            "創作模式支援圖文浮水印庫、顯著度主體避讓演算法、大小錯落自動排版與單層拖曳縮放旋轉",
            "工作模式支援多圖與影片幀同步即時預覽、平鋪防盜、九宮格定位與橫豎版隔離分資料夾匯出",
            "自訂預設與創作浮水印庫本機持久化，支援 UTF-8 JSON 匯入匯出並與 Windows 桌面 EXE 互通",
            "支援單檔直接下載、ZIP 打包匯出與 Chrome/Edge 直寫本機資料夾，適配桌機與手機端",
        ],
        "faqs": [
            ("BatchWatermark 線上加浮水印免費嗎？需要註冊登入嗎？", "完全免費並採用 MIT 授權開源，無需註冊登入、無張數限制、無強制品牌角標，開啟 watermark.zak-cloud.top 或 GitHub Pages 鏡像即可直接使用。"),
            ("我的圖片與影片會被上傳到伺服器嗎？", "絕不會上傳。圖片解碼、Canvas 浮水印繪製、創作模式顯著度分析、MediaRecorder 影片合成與 ZIP 打包全部在您的瀏覽器本機記憶體內完成，沒有任何檔案上傳介面。"),
            ("工作模式與創作模式有什麼差別？", "工作模式專注於高效批次為圖片與影片加上文字/Logo 平鋪或九宮格浮水印，並支援橫豎隔離匯出；創作模式專為插畫、攝影與委託稿防盜打造，支援上傳圖文浮水印庫、演算法自動避讓主體產生大小不一的藝術排版，且每個元素皆可自由拖曳精修。"),
            ("支援手機端使用嗎？", "支援。網頁版針對 iOS Safari 與 Android 瀏覽器做了專屬行動端介面優化：頂部固定即時預覽/互動畫布，下方透過分類分頁切換參數，單圖可直接下載儲存到手機。"),
            ("支援哪些圖片與影片格式？可匯出什麼格式？", "圖片支援 JPG / JPEG / PNG / WebP / BMP / GIF / AVIF，可保留原格式或轉換為 JPEG、PNG、WebP 並調整品質；影片支援 MP4 / WebM / MOV，於瀏覽器本機匯出 MP4 或 WebM 並保留原聲。"),
            ("橫版與直版圖片可以使用不同的浮水印並分開匯出嗎？", "可以。在工作模式點擊頂部「橫豎隔離」，預覽區會自動分為橫版區（寬 ≥ 高）與直版區（高 > 寬），支援獨立參數設定，匯出時自動分類至對應子資料夾。"),
            ("創作模式的浮水印庫能與桌面版互通嗎？", "可以。創作模式浮水印庫自動儲存於瀏覽器本機 IndexedDB，並支援匯出標準 UTF-8 JSON 檔案包，與 Windows 桌面 EXE 版 100% 雙向匯入匯出互通。"),
            ("需要處理大量高畫質長影片，有離線桌面版嗎？", "有。BatchWatermark 提供基於 Python、PySide6 與內建 FFmpeg 的 Windows 獨立單檔 EXE，同樣內建工作模式與創作模式及四語言切換，可於 GitHub Releases 免費下載。"),
        ],
        "guide": {
            "eyebrow": "免費 · MIT 開源 · 免安裝 · 100% 本機零上傳",
            "hero_title": "BatchWatermark：線上批次圖片與影片加浮水印 & 藝術創作工作室",
            "hero_lead": "<strong>BatchWatermark</strong>（主站 <a href=\"https://watermark.zak-cloud.top/zh-hant/\">watermark.zak-cloud.top</a>）是一款完全運行於瀏覽器本機的免費<strong>批次圖片與影片加浮水印工具</strong>，全程<strong>零伺服器上傳</strong>。可於頂部分頁自由切換<strong>工作模式</strong>（高效批次圖片/影片）與<strong>創作模式</strong>（圖文浮水印庫、智慧避讓主體多尺度藝術排版與自由拖曳精修）。",
            "hero_cta": "↑ 返回工具立即開始加浮水印",
            "tldr_title": "核心規格一覽（TL;DR）",
            "facts": [
                ("隱私與資料安全", "<strong>0 次伺服器上傳</strong> · 100% 本機瀏覽器 HTML5 Canvas + MediaRecorder 運算"),
                ("雙模式獨立運作", "<strong>工作模式</strong>（批次圖片/影片）+ <strong>創作模式</strong>（浮水印庫、智慧排版、自由拖曳）"),
                ("支援媒體格式", "圖片 <strong>JPG / PNG / WebP / BMP / GIF / AVIF</strong> · 影片 <strong>MP4 / WebM / MOV</strong>"),
                ("橫豎版隔離匯出", "自動區分橫版（寬 ≥ 高）與直版（高 &gt; 寬），支援獨立浮水印參數並分資料夾匯出"),
                ("預設與跨端互通", "本機持久儲存（IndexedDB / localStorage）+ UTF-8 JSON 與 Windows EXE <strong>100% 互通</strong>"),
                ("費用與開源授權", "<strong>完全免費</strong> · 無張數限制 · 免登入 · MIT 協議開源"),
            ],
            "feat_title": "核心功能",
            "features": [
                ("✨ 創作模式（圖文浮水印庫 + 智慧避讓 + 自由拖曳）", "上傳透明 PNG 貼紙與多行文字組成浮水印庫，一鍵產生避讓人物主體的大小錯落藝術浮水印，並可單獨拖曳、縮放、旋轉、鎖定或按比例套用至全部圖片。"),
                ("批次圖片與影片加浮水印", "支援多選檔案、匯入整個資料夾或直接拖曳整批素材；自動校正手機照片 EXIF 方向，影片匯出可保留原聲。"),
                ("多行文字與透明 Logo 浮水印", "支援常用中英文字體與載入本機 <code>.ttf / .otf / .woff2</code> 自訂字體，可調顏色、描邊、陰影與行距；透明 PNG / WebP Logo 依寬度比例縮放。"),
                ("全圖平鋪防盜與九宮格定位", "平鋪模式可調水平/垂直間距、-180°~180° 旋轉角度與磚牆交錯；單點模式提供 3×3 九宮格定位與精細偏移。"),
                ("多圖即時同步預覽（桌機 + 手機適配）", "調整任一參數即可同步看到所有圖片與影片幀的浮水印變化；手機端採頂部固定畫布 + 分類分頁設計，單手流暢操作。"),
                ("橫豎隔離與跨端 JSON 互通", "自動區分橫版與直版媒體分別調參與匯出；預設與創作浮水印庫 JSON 與桌面端 EXE 100% 互通。"),
            ],
            "cmp_title": "網頁版 vs Windows 桌面 EXE vs 傳統雲端網站",
            "cmp_headers": ["比較維度", "BatchWatermark 網頁版（本頁）", "BatchWatermark 桌面 EXE", "傳統雲端浮水印網站"],
            "cmp_rows": [
                ("隱私與上傳", "<strong>零上傳</strong> · 純本機瀏覽器運算", "<strong>零上傳</strong> · 完全離線執行", "需上傳至遠端伺服器，具外洩風險"),
                ("工作 + 創作雙模式", "<strong>完整內建</strong>（智慧排版 + 自由拖曳）", "<strong>完整內建</strong>（與網頁 JSON 互通）", "多僅支援單一固定浮水印"),
                ("影片浮水印支援", "MP4 / WebM / MOV（本機錄製）", "MP4 / MOV / MKV / AVI（內建 FFmpeg）", "常限制檔案大小或需付費會員"),
                ("費用與張數限制", "<strong>完全免費無上限</strong>、免登入", "<strong>完全免費無上限</strong>、MIT 開源", "常有張數限制、強制角標或付費牆"),
            ],
            "howto_title": "4 步驟完成本機批次加浮水印",
            "use_title": "常見應用場景",
            "uses": [
                ("插畫、約稿與原創作品防盜", "使用創作模式將雪花、印章與落款文字自動避開人物臉部並大小錯落排布，兼顧防盜與畫面美感。"),
                ("電商商品圖與攝影交件樣圖", "於工作模式一次匯入數十張商品照或攝影毛片，同步預覽並依橫版/直版自動分資料夾匯出。"),
                ("證件掃描件與內部機密文件", "在瀏覽器本機加上「僅供審核使用」斜向平鋪防盜字樣，檔案全程不離開您的裝置。"),
            ],
            "faq_title": "常見問題（FAQ）",
            "footer_note": "MIT 開源授權 · 100% 本機處理 · 多語言支援（简体中文 / English / 日本語 / 繁體中文）",
        },
    },
}


def build_i18n_data_js() -> None:
    """Export single-source-of-truth translation tables into web/js/i18n-data.js."""
    out_path = WEB_DIR / "js" / "i18n-data.js"
    lines = [
        "// AUTO-GENERATED by scripts/build_i18n_web.py from batch_watermark/i18n_data.py.",
        "// Do not hand-edit; run `uv run python scripts/build_i18n_web.py` after updating translations.",
        "",
        f"export const SUPPORTED_LOCALES = {json.dumps(SUPPORTED_LOCALES, ensure_ascii=False)};",
        "",
        f"export const TRANSLATIONS = {json.dumps(TRANSLATIONS, ensure_ascii=False, indent=2)};",
        "",
        f"export const REGEX_TRANSLATIONS = {json.dumps(REGEX_TRANSLATIONS, ensure_ascii=False, indent=2)};",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {out_path.relative_to(ROOT)} ({len(TRANSLATIONS)} keys, {len(REGEX_TRANSLATIONS)} regex rules)")


def _build_hreflang_block() -> str:
    links = [
        f'  <link rel="alternate" hreflang="zh-CN" href="{LOCALE_URLS["zh-CN"]}" />',
        f'  <link rel="alternate" hreflang="en" href="{LOCALE_URLS["en"]}" />',
        f'  <link rel="alternate" hreflang="ja" href="{LOCALE_URLS["ja"]}" />',
        f'  <link rel="alternate" hreflang="zh-Hant" href="{LOCALE_URLS["zh-Hant"]}" />',
        f'  <link rel="alternate" hreflang="x-default" href="{LOCALE_URLS["zh-CN"]}" />',
    ]
    return "\n".join(links)


def _build_og_locale_block(locale_code: str) -> str:
    cur = OG_LOCALES[locale_code]
    alts = [v for k, v in OG_LOCALES.items() if k != locale_code]
    lines = [f'  <meta property="og:locale" content="{cur}" />']
    for a in alts:
        lines.append(f'  <meta property="og:locale:alternate" content="{a}" />')
    return "\n".join(lines)


def _build_json_ld(locale_code: str) -> str:
    pack = SEO_PACKS[locale_code]
    url = LOCALE_URLS[locale_code]
    slug = next((s for c, _l, s in SUPPORTED_LOCALES if c == locale_code), "")
    mirror_url = f"{MIRROR_ORIGIN}/{slug}/" if slug else f"{MIRROR_ORIGIN}/"

    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{PRIMARY_ORIGIN}/#website",
                "name": "BatchWatermark",
                "alternateName": pack["alt_names"],
                "url": f"{PRIMARY_ORIGIN}/",
                "inLanguage": ["zh-CN", "en", "ja", "zh-Hant"],
                "sameAs": [f"{MIRROR_ORIGIN}/", REPO_URL],
            },
            {
                "@type": "WebApplication",
                "@id": f"{url}#app",
                "name": pack["app_name"],
                "alternateName": pack["alt_names"],
                "url": url,
                "inLanguage": locale_code,
                "sameAs": [mirror_url, REPO_URL],
                "description": pack["description"],
                "applicationCategory": "MultimediaApplication",
                "applicationSubCategory": "Image and Video Watermarking Tool",
                "operatingSystem": "Web Browser (Chrome, Edge, Safari, Firefox, iOS, Android), Windows 10/11",
                "browserRequirements": "Requires HTML5 Canvas 2D and MediaRecorder support",
                "softwareVersion": __version__,
                "isAccessibleForFree": True,
                "license": "https://opensource.org/licenses/MIT",
                "screenshot": f"{PRIMARY_ORIGIN}/og-image.png",
                "image": f"{PRIMARY_ORIGIN}/og-image.png",
                "offers": {
                    "@type": "Offer",
                    "price": "0",
                    "priceCurrency": pack["price_currency"],
                },
                "author": {
                    "@type": "Person",
                    "name": "drank5090",
                    "url": "https://github.com/drank5090",
                },
                "featureList": pack["features_ld"],
            },
            {
                "@type": "HowTo",
                "@id": f"{url}#howto",
                "name": pack["howto_name"],
                "description": pack["howto_desc"],
                "inLanguage": locale_code,
                "totalTime": "PT1M",
                "tool": [{"@type": "HowToTool", "name": pack["howto_tool"]}],
                "step": [
                    {
                        "@type": "HowToStep",
                        "position": idx,
                        "name": name,
                        "text": text,
                    }
                    for idx, (name, text) in enumerate(pack["howto_steps"], start=1)
                ],
            },
            {
                "@type": "FAQPage",
                "@id": f"{url}#faq",
                "inLanguage": locale_code,
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a},
                    }
                    for q, a in pack["faqs"]
                ],
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{url}#breadcrumb",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": pack["breadcrumb_home"],
                        "item": url,
                    }
                ],
            },
        ],
    }
    raw = json.dumps(graph, ensure_ascii=False, indent=2)
    indented = "\n".join("  " + line for line in raw.splitlines())
    return f'  <script type="application/ld+json">\n{indented}\n  </script>'


def _build_guide_html(locale_code: str, asset_prefix: str) -> str:
    pack = SEO_PACKS[locale_code]
    g = pack["guide"]

    facts_html = "\n".join(
        f'          <div class="fact-card">\n'
        f'            <dt>{html.escape(dt)}</dt>\n'
        f'            <dd>{dd}</dd>\n'
        f'          </div>'
        for dt, dd in g["facts"]
    )
    feats_html = "\n".join(
        f'          <li class="feature-item">\n'
        f'            <h3>{html.escape(title)}</h3>\n'
        f'            <p>{body}</p>\n'
        f'          </li>'
        for title, body in g["features"]
    )
    th_html = "".join(f"<th>{html.escape(h)}</th>" for h in g["cmp_headers"])
    tr_html = "\n".join(
        "              <tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in g["cmp_rows"]
    )
    steps_html = "\n".join(
        f'          <li><strong>{html.escape(name)}</strong>：{html.escape(text)}</li>'
        for name, text in pack["howto_steps"]
    )
    uses_html = "\n".join(
        f'          <li class="feature-item">\n'
        f'            <h3>{html.escape(title)}</h3>\n'
        f'            <p>{html.escape(body)}</p>\n'
        f'          </li>'
        for title, body in g["uses"]
    )
    faqs_html = "\n".join(
        f'          <details class="faq-item">\n'
        f'            <summary>{html.escape(q)}</summary>\n'
        f'            <p>{html.escape(a)}</p>\n'
        f'          </details>'
        for q, a in pack["faqs"]
    )

    # Bidirectional crawlable language links in footer
    lang_links = []
    for code, label, slug in SUPPORTED_LOCALES:
        href = f"{asset_prefix}{slug}/" if slug else (asset_prefix or "./")
        if code == locale_code:
            lang_links.append(f'<strong>{html.escape(label)}</strong>')
        else:
            lang_links.append(f'<a href="{href}" hreflang="{code}">{html.escape(label)}</a>')
    lang_nav = " · ".join(lang_links)

    return f'''  <!-- Crawlable Product Guide & GEO Knowledge Hub (scroll below the app viewport) -->
  <div class="site-guide-wrap">
    <article id="guide" class="site-guide" aria-labelledby="guideTitle">
      <header class="guide-hero">
        <p class="guide-eyebrow">{html.escape(g["eyebrow"])}</p>
        <h2 id="guideTitle">{html.escape(g["hero_title"])}</h2>
        <p class="guide-lead">{g["hero_lead"]}</p>
        <a class="btn btn-primary guide-cta" href="#top">{html.escape(g["hero_cta"])}</a>
      </header>

      <section class="guide-section" aria-labelledby="tldrTitle">
        <h2 id="tldrTitle">{html.escape(g["tldr_title"])}</h2>
        <dl class="facts-grid">
{facts_html}
        </dl>
      </section>

      <section class="guide-section" aria-labelledby="featTitle">
        <h2 id="featTitle">{html.escape(g["feat_title"])}</h2>
        <ul class="feature-grid">
{feats_html}
        </ul>
      </section>

      <section class="guide-section" aria-labelledby="compareTitle">
        <h2 id="compareTitle">{html.escape(g["cmp_title"])}</h2>
        <div class="table-scroll">
          <table class="compare-table">
            <thead>
              <tr>{th_html}</tr>
            </thead>
            <tbody>
{tr_html}
            </tbody>
          </table>
        </div>
      </section>

      <section class="guide-section" aria-labelledby="howtoTitle">
        <h2 id="howtoTitle">{html.escape(g["howto_title"])}</h2>
        <ol class="howto-steps">
{steps_html}
        </ol>
      </section>

      <section class="guide-section" aria-labelledby="useTitle">
        <h2 id="useTitle">{html.escape(g["use_title"])}</h2>
        <ul class="feature-grid">
{uses_html}
        </ul>
      </section>

      <section class="guide-section" aria-labelledby="faqTitle">
        <h2 id="faqTitle">{html.escape(g["faq_title"])}</h2>
        <div class="faq-list">
{faqs_html}
        </div>
      </section>

      <footer class="guide-footer">
        <nav class="guide-links" aria-label="Language versions">
          {lang_nav}
        </nav>
        <nav class="guide-links" aria-label="Related links">
          <a href="{PRIMARY_ORIGIN}/">watermark.zak-cloud.top</a>
          <a href="{MIRROR_ORIGIN}/" rel="noopener">GitHub Pages Mirror</a>
          <a href="{REPO_URL}" target="_blank" rel="noopener noreferrer">GitHub Source</a>
          <a href="{REPO_URL}/releases" target="_blank" rel="noopener noreferrer">Windows EXE Releases</a>
          <a href="{asset_prefix}llms.txt">llms.txt (GEO)</a>
        </nav>
        <p class="muted-text">{html.escape(g["footer_note"])}</p>
      </footer>
    </article>
  </div>'''


def _pretranslate_ui_fragment(ui_html: str, locale_code: str) -> str:
    """Pre-translate known UI text nodes & attributes in static HTML for native SSR-like crawlability."""
    if locale_code == "zh-CN":
        return ui_html

    # Sort longest-first to avoid partial replacements inside attributes/text
    def repl_attr(match: re.Match[str]) -> str:
        attr_name = match.group(1)
        val = match.group(2)
        translated = translate_text(html.unescape(val), locale_code)
        return f'{attr_name}="{html.escape(translated, quote=True)}"'

    out = re.sub(r'\b(title|placeholder|aria-label)="([^"]+)"', repl_attr, ui_html)

    # Translate text strictly between > and < (skipping script/style blocks and data-i18n-skip)
    def repl_text(match: re.Match[str]) -> str:
        raw = match.group(1)
        stripped = raw.strip()
        if not stripped:
            return f">{raw}<"
        translated = translate_text(html.unescape(stripped), locale_code)
        if translated == stripped:
            return f">{raw}<"
        return f">{raw.replace(stripped, html.escape(translated))}<"

    out = re.sub(r">([^<>]+)<", repl_text, out)
    # Mark selected language option in <select id="langSelect">
    out = out.replace(f'<option value="{locale_code}">', f'<option value="{locale_code}" selected>')
    return out


def _rewrite_head(html_text: str, locale_code: str, asset_prefix: str) -> str:
    pack = SEO_PACKS[locale_code]
    url = LOCALE_URLS[locale_code]

    out = re.sub(r'<html lang="[^"]+">', f'<html lang="{locale_code}">', html_text, count=1)
    out = re.sub(r"<title>.*?</title>", f"<title>{html.escape(pack['title'])}</title>", out, count=1, flags=re.S)
    out = re.sub(
        r'<meta name="description" content="[^"]*" />',
        f'<meta name="description" content="{html.escape(pack["description"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta name="keywords" content="[^"]*" />',
        f'<meta name="keywords" content="{html.escape(pack["keywords"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<link rel="canonical" href="[^"]*" />(?:\s*<link rel="alternate" hreflang="[^"]*" href="[^"]*" />)+',
        f'<link rel="canonical" href="{url}" />\n{_build_hreflang_block()}',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta property="og:locale" content="[^"]*" />(?:\s*<meta property="og:locale:alternate" content="[^"]*" />)*',
        _build_og_locale_block(locale_code),
        out,
        count=1,
    )
    out = re.sub(
        r'<meta property="og:url" content="[^"]*" />',
        f'<meta property="og:url" content="{url}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta property="og:title" content="[^"]*" />',
        f'<meta property="og:title" content="{html.escape(pack["og_title"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta property="og:description" content="[^"]*" />',
        f'<meta property="og:description" content="{html.escape(pack["og_desc"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta property="og:image:alt" content="[^"]*" />',
        f'<meta property="og:image:alt" content="{html.escape(pack["og_alt"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta name="twitter:title" content="[^"]*" />',
        f'<meta name="twitter:title" content="{html.escape(pack["og_title"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta name="twitter:description" content="[^"]*" />',
        f'<meta name="twitter:description" content="{html.escape(pack["og_desc"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'<meta name="twitter:image:alt" content="[^"]*" />',
        f'<meta name="twitter:image:alt" content="{html.escape(pack["og_alt"], quote=True)}" />',
        out,
        count=1,
    )
    out = re.sub(
        r'  <script type="application/ld\+json">.*?</script>',
        _build_json_ld(locale_code),
        out,
        count=1,
        flags=re.S,
    )

    if asset_prefix:
        for rel_ref in ("favicon.ico", "favicon.svg", "apple-touch-icon.png", "site.webmanifest", "styles.css"):
            out = out.replace(f'href="{rel_ref}"', f'href="{asset_prefix}{rel_ref}"')
        out = out.replace('src="js/app.js"', f'src="{asset_prefix}js/app.js"')

    return out


def update_root_and_generate_locale_pages() -> None:
    root_html_path = WEB_DIR / "index.html"
    base_html = root_html_path.read_text(encoding="utf-8")

    # 1. Update zh-CN root index.html head (full 4-language hreflang, og:locale:alternate, JSON-LD)
    #    and ensure crawlable language footer links exist in zh-CN guide too.
    updated_zh = _rewrite_head(base_html, "zh-CN", "")
    lang_nav_zh = (
        '<nav class="guide-links" aria-label="语言版本 / Languages">\n'
        '          <strong>简体中文</strong> · '
        '<a href="./en/" hreflang="en">English</a> · '
        '<a href="./ja/" hreflang="ja">日本語</a> · '
        '<a href="./zh-hant/" hreflang="zh-Hant">繁體中文</a>\n'
        '        </nav>'
    )
    if 'aria-label="语言版本 / Languages"' not in updated_zh:
        updated_zh = updated_zh.replace(
            '<footer class="guide-footer">',
            f'<footer class="guide-footer">\n        {lang_nav_zh}',
            1,
        )
    root_html_path.write_text(updated_zh, encoding="utf-8")
    print(f"Updated root zh-CN SEO page: {root_html_path.relative_to(ROOT)}")

    # Split base_html into [before_guide, guide_block, after_guide]
    guide_start_marker = "  <!-- Crawlable Product Guide"
    guide_end_marker = "</article>\n  </div>"
    gs_idx = updated_zh.index(guide_start_marker)
    ge_idx = updated_zh.index(guide_end_marker, gs_idx) + len(guide_end_marker)
    before_guide = updated_zh[:gs_idx]
    after_guide = updated_zh[ge_idx:]

    # 2. Generate /en/index.html, /ja/index.html, /zh-hant/index.html
    for loc_code, _label, slug in SUPPORTED_LOCALES:
        if not slug:
            continue
        head_end = before_guide.index("</head>") + len("</head>")
        head_part = _rewrite_head(before_guide[:head_end], loc_code, "../")
        body_ui_part = _pretranslate_ui_fragment(before_guide[head_end:], loc_code)
        guide_part = _build_guide_html(loc_code, "../")
        modals_part = _pretranslate_ui_fragment(after_guide, loc_code).replace('src="js/app.js"', 'src="../js/app.js"')

        page_html = head_part + body_ui_part + guide_part + modals_part
        target_dir = WEB_DIR / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "index.html"
        target_file.write_text(page_html, encoding="utf-8")
        print(f"Generated localized SEO page: {target_file.relative_to(ROOT)} ({len(page_html):,} chars)")


def generate_multilang_sitemap() -> None:
    today = date.today().isoformat()
    hreflang_lines = "\n".join(
        [
            f'    <xhtml:link rel="alternate" hreflang="zh-CN" href="{LOCALE_URLS["zh-CN"]}" />',
            f'    <xhtml:link rel="alternate" hreflang="en" href="{LOCALE_URLS["en"]}" />',
            f'    <xhtml:link rel="alternate" hreflang="ja" href="{LOCALE_URLS["ja"]}" />',
            f'    <xhtml:link rel="alternate" hreflang="zh-Hant" href="{LOCALE_URLS["zh-Hant"]}" />',
            f'    <xhtml:link rel="alternate" hreflang="x-default" href="{LOCALE_URLS["zh-CN"]}" />',
        ]
    )

    entries = []
    for code, _label, _slug in SUPPORTED_LOCALES:
        pack = SEO_PACKS[code]
        prio = "1.0" if code == "zh-CN" else "0.9"
        entries.append(
            f"""  <url>
    <loc>{LOCALE_URLS[code]}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>{prio}</priority>
{hreflang_lines}
    <image:image>
      <image:loc>{PRIMARY_ORIGIN}/og-image.png</image:loc>
      <image:title>{html.escape(pack["app_name"])}</image:title>
      <image:caption>{html.escape(pack["og_alt"])}</image:caption>
    </image:image>
  </url>"""
        )

    entries.append(
        f"""  <url>
    <loc>{PRIMARY_ORIGIN}/llms.txt</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>"""
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml"\n'
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    out_path = WEB_DIR / "sitemap.xml"
    out_path.write_text(xml, encoding="utf-8")
    print(f"Generated multilingual {out_path.relative_to(ROOT)}")


def generate_multilang_llms_txt() -> None:
    content = f"""# BatchWatermark (v2.0 Dual-Mode & Multi-Language)

> Free, open-source (MIT), 100% client-side batch image & video watermarking tool and artistic watermark creative studio. Zero server uploads. Available in Simplified Chinese (zh-CN), English (en), Japanese (ja), and Traditional Chinese (zh-Hant) across both Web and Windows Desktop EXE.

## Official Multilingual Entry Points

- Simplified Chinese (Primary / Default): {LOCALE_URLS["zh-CN"]}
- English: {LOCALE_URLS["en"]}
- Japanese (日本語): {LOCALE_URLS["ja"]}
- Traditional Chinese (繁體中文 / zh-Hant): {LOCALE_URLS["zh-Hant"]}
- GitHub Pages Mirror: {MIRROR_ORIGIN}/
- Source Code & Windows Desktop EXE Releases: {REPO_URL}

## Dual-Mode Architecture (Independent Top Tabs)

1. **Work Mode (工作模式 / ワークモード)**:
   - Bulk image & video watermarking with real-time synchronized multi-preview.
   - Multi-line text watermarks (custom `.ttf`/`.otf`/`.woff2` fonts, stroke, drop shadow) and transparent PNG/WebP logo watermarks.
   - Brick-staggered diagonal anti-theft tiling (`-180°` to `180°`) and 3×3 anchor grid positioning.
   - Landscape / Portrait Orientation Isolation (`横竖隔离`): independent configs and automatic subfolder export.
   - Local persistent presets + UTF-8 JSON import/export 100% compatible with the Windows Desktop EXE.

2. **Creative Mode (创作模式 / クリエイティブモード)**:
   - Custom Watermark Library supporting multiple transparent PNG/WebP image stickers and multi-line text templates (persisted locally via IndexedDB on Web / JSON on Desktop, with cross-platform JSON pack import/export).
   - Built-in artistic starter pack (frosted snowflakes, sparkles, ribbon wave, seal emblem, glowing serif title & poetic quotes).
   - Subject-aware multi-scale aesthetic auto-layout algorithm: computes a 48×48 visual saliency + portrait-center protection map so large/bright watermarks frame open edges while avoiding faces and key subjects, combining Hero focal pieces, varied-size Accents, and subtle Micro anti-theft texture stamps.
   - Interactive direct-manipulation canvas (mouse & touch): every auto-generated or manually dragged watermark can be freely dragged, resized, rotated, locked against shuffle, layered, undone/redone, and proportionally synced across all loaded images.

## Privacy, Formats & Export

- **Zero Server Uploads**: All image decoding, Canvas 2D compositing, saliency analysis, MediaRecorder video encoding, and UTF-8 ZIP packaging run strictly inside local browser memory.
- **Supported Formats**: Images (`JPG`, `JPEG`, `PNG`, `WebP`, `BMP`, `GIF`, `AVIF`); Videos (`MP4`, `WebM`, `MOV`, preserving original audio).
- **Desktop Companion**: Standalone Windows 64-bit single-file EXE (Python + PySide6 + Pillow + bundled FFmpeg) with identical Work Mode, Creative Mode, and 4-language UI (`zh-CN`, `en`, `ja`, `zh-Hant`).
"""
    out_path = WEB_DIR / "llms.txt"
    out_path.write_text(content, encoding="utf-8")
    print(f"Generated multilingual {out_path.relative_to(ROOT)}")


def main() -> int:
    build_i18n_data_js()
    update_root_and_generate_locale_pages()
    generate_multilang_sitemap()
    generate_multilang_llms_txt()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
