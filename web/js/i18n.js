/**
 * Multi-language i18n runtime for BatchWatermark Web Edition (zh-CN / en / ja / zh-Hant).
 * Supports both static SEO localized subdirectories (/en/, /ja/, /zh-hant/)
 * AND lossless in-place DOM language switching when media is already loaded.
 */

import { REGEX_TRANSLATIONS, SUPPORTED_LOCALES, TRANSLATIONS } from "./i18n-data.js";

const STORAGE_KEY = "batch_watermark_locale_v1";

const COMPILED_REGEX = REGEX_TRANSLATIONS.map(([pattern, repls]) => [new RegExp(pattern), repls]);

// Build reverse lookup map (localized -> canonical zh-CN) so pre-rendered static pages
// (/en/index.html, /ja/index.html, /zh-hant/index.html) can also switch losslessly in-place!
const REVERSE_TO_ZH = new Map();
for (const [zh, langs] of Object.entries(TRANSLATIONS)) {
  for (const localized of Object.values(langs)) {
    if (localized && !REVERSE_TO_ZH.has(localized)) {
      REVERSE_TO_ZH.set(localized, zh);
    }
  }
}

const NODE_SRC_MAP = new WeakMap();
const ATTR_SRC_MAP = new WeakMap();
const I18N_ATTRS = ["title", "placeholder", "aria-label"];

export const PAGE_TITLES = {
  "zh-CN": "BatchWatermark 在线批量加水印工具 · 免费图片与视频添加文字/Logo水印（零上传）",
  en: "BatchWatermark — Free Online Batch Image & Video Watermark Tool & Creative Studio (100% Local)",
  ja: "BatchWatermark — 無料オンライン画像・動画一括透かし＆アート透かし作成ツール（完全ローカル）",
  "zh-Hant": "BatchWatermark 線上批次加浮水印工具 · 免費圖片與影片加文字/Logo浮水印（零上傳）",
};

export function normalizeLocale(code) {
  if (!code) return "zh-CN";
  const c = String(code).trim().replace("_", "-").toLowerCase();
  if (c.includes("hant") || c === "zh-hk" || c === "zh-mo") return "zh-Hant";
  if (c.startsWith("zh")) return "zh-CN";
  if (c.startsWith("ja")) return "ja";
  if (c.startsWith("en")) return "en";
  return "zh-CN";
}

export function detectLocaleFromPage() {
  // 1. Explicit query parameter (?lang=en)
  try {
    const qp = new URLSearchParams(window.location.search).get("lang");
    if (qp) return normalizeLocale(qp);
  } catch {
    // ignore
  }
  // 2. Static localized subdirectory path (/en/, /ja/, /zh-hant/)
  const path = (window.location.pathname || "/").toLowerCase();
  if (/(^|\/)en(\/|$)/.test(path)) return "en";
  if (/(^|\/)ja(\/|$)/.test(path)) return "ja";
  if (/(^|\/)zh-hant(\/|$)/.test(path)) return "zh-Hant";
  // 3. Document <html lang="...">
  if (document.documentElement?.lang) {
    return normalizeLocale(document.documentElement.lang);
  }
  return "zh-CN";
}

let activeLocale = detectLocaleFromPage();

export function getLocale() {
  return activeLocale;
}

export function getSupportedLocales() {
  return SUPPORTED_LOCALES;
}

export function setLocale(code, { persist = true } = {}) {
  activeLocale = normalizeLocale(code);
  if (document.documentElement) {
    document.documentElement.lang = activeLocale;
  }
  if (PAGE_TITLES[activeLocale]) {
    document.title = PAGE_TITLES[activeLocale];
  }
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, activeLocale);
    } catch {
      // ignore
    }
  }
  return activeLocale;
}

export function canonicalizeToZh(text) {
  if (!text) return text;
  const trimmed = text.trim();
  if (TRANSLATIONS[trimmed]) return trimmed;
  const rev = REVERSE_TO_ZH.get(trimmed);
  return rev || trimmed;
}

export function t(src, targetLocale = activeLocale) {
  if (!src) return src;
  const loc = normalizeLocale(targetLocale);
  const raw = String(src);
  const trimmed = raw.trim();
  if (!trimmed) return raw;

  // Normalize to canonical zh-CN key first so pre-translated text also translates cleanly
  const canonical = TRANSLATIONS[trimmed] ? trimmed : (REVERSE_TO_ZH.get(trimmed) || trimmed);
  if (loc === "zh-CN") {
    return raw.replace(trimmed, canonical);
  }

  const entry = TRANSLATIONS[canonical];
  if (entry && entry[loc]) {
    return raw.replace(trimmed, entry[loc]);
  }

  for (const [regex, repls] of COMPILED_REGEX) {
    const m = canonical.match(regex);
    if (m && repls[loc]) {
      let out = repls[loc];
      for (let i = 1; i < m.length; i++) {
        const sub = t(m[i], loc);
        out = out.replaceAll(`$${i}`, sub);
      }
      return raw.replace(trimmed, out);
    }
  }

  return raw;
}

/**
 * Compute relative navigation URL for switching to `targetLocale` while preserving
 * both root hosting (watermark.zak-cloud.top) and subpath hosting (/BatchWatermark/).
 */
export function buildLocaleNavigationUrl(targetLocale) {
  const loc = normalizeLocale(targetLocale);
  const targetEntry = SUPPORTED_LOCALES.find((item) => item[0] === loc);
  const targetSlug = targetEntry ? targetEntry[2] : "";

  const path = (window.location.pathname || "/").toLowerCase();
  const inSubdir = /(^|\/)(en|ja|zh-hant)(\/|$)/.test(path);

  if (inSubdir) {
    return targetSlug ? `../${targetSlug}/` : "../";
  }
  return targetSlug ? `./${targetSlug}/` : "./";
}

/**
 * Translate all UI text nodes and attributes inside `root` in-place (lossless across language switches).
 */
export function applyDomTranslations(root = document.body, targetLocale = activeLocale) {
  const loc = normalizeLocale(targetLocale);
  if (!root) return;

  // Translate element attributes (title, placeholder, aria-label)
  const elements = root.querySelectorAll ? [root, ...root.querySelectorAll("*")] : [];
  for (const el of elements) {
    if (!el || !el.getAttribute || el.hasAttribute("data-i18n-skip")) continue;
    if (el.closest?.("[data-i18n-skip]")) continue;

    let savedAttrs = ATTR_SRC_MAP.get(el);
    if (!savedAttrs) {
      savedAttrs = {};
      ATTR_SRC_MAP.set(el, savedAttrs);
    }
    for (const attr of I18N_ATTRS) {
      const val = el.getAttribute(attr);
      if (!val) continue;
      if (!(attr in savedAttrs)) {
        savedAttrs[attr] = canonicalizeToZh(val);
      } else {
        // Detect if JS updated the attribute dynamically to a new canonical string
        const prevTranslated = t(savedAttrs[attr], activeLocale);
        if (val !== prevTranslated && val !== savedAttrs[attr]) {
          savedAttrs[attr] = canonicalizeToZh(val);
        }
      }
      const next = t(savedAttrs[attr], loc);
      if (next !== val) el.setAttribute(attr, next);
    }
  }

  // Translate text nodes inside interactive app shell (leave pre-rendered #guide intact when matching static page)
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      const tag = parent.tagName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") return NodeFilter.FILTER_REJECT;
      if (parent.hasAttribute("data-i18n-skip") || parent.closest?.("[data-i18n-skip]")) {
        return NodeFilter.FILTER_REJECT;
      }
      if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);

  for (const textNode of nodes) {
    const cur = textNode.nodeValue;
    const trimmed = cur.trim();
    if (!trimmed) continue;

    let src = NODE_SRC_MAP.get(textNode);
    if (!src) {
      src = canonicalizeToZh(trimmed);
      NODE_SRC_MAP.set(textNode, src);
    } else {
      const prevRendered = t(src, activeLocale);
      if (trimmed !== prevRendered && trimmed !== src) {
        src = canonicalizeToZh(trimmed);
        NODE_SRC_MAP.set(textNode, src);
      }
    }

    const translated = t(src, loc);
    if (translated !== trimmed) {
      textNode.nodeValue = cur.replace(trimmed, translated);
    }
  }
}
