/**
 * Built-in artistic starter watermark pack + persistent IndexedDB / localStorage
 * storage & cross-platform JSON pack import/export for Creative Mode.
 */

import {
  CREATIVE_LIBRARY_SCHEMA_ID,
  CREATIVE_LIBRARY_SCHEMA_VERSION,
  cloneAsset,
  newCreativeId,
  sanitizeCreativeAsset,
} from "./creative-models.js";
import { stripExtension } from "./models.js";
import { loadHtmlImageFromFile } from "./watermark-engine.js";

const IDB_NAME = "BatchWatermarkCreativeDB";
const IDB_STORE = "library";
const IDB_KEY = "assets_v1";
const LS_FALLBACK_KEY = "batch_watermark_creative_library_v1";

// ---- Procedural Built-in Starter Art Stickers ----

function drawOrnateSnowflakeDataUrl(size = 256, fine = false) {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const ctx = c.getContext("2d");
  const cx = size / 2;
  const cy = size / 2;
  const radius = size * (fine ? 0.36 : 0.40);
  const branches = fine ? 8 : 6;
  const armW = Math.max(2, size * (fine ? 0.013 : 0.019));

  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.shadowColor = "rgba(224, 242, 254, 0.85)";
  ctx.shadowBlur = size * 0.03;

  for (let k = 0; k < branches; k++) {
    const ang = ((k * 360) / branches - 90) * (Math.PI / 180);
    const ca = Math.cos(ang);
    const sa = Math.sin(ang);
    const ex = cx + ca * radius;
    const ey = cy + sa * radius;

    ctx.strokeStyle = "rgba(255, 255, 255, 0.96)";
    ctx.lineWidth = armW;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(ex, ey);
    ctx.stroke();

    const twigs = fine ? [0.45, 0.74] : [0.38, 0.62, 0.80];
    ctx.strokeStyle = "rgba(224, 242, 254, 0.88)";
    ctx.lineWidth = Math.max(1.2, armW * 0.7);
    for (const frac of twigs) {
      const bx = cx + ca * (radius * frac);
      const by = cy + sa * (radius * frac);
      const tlen = radius * (frac < 0.5 ? 0.30 : frac < 0.75 ? 0.24 : 0.14);
      for (const side of [-1, 1]) {
        const tang = ang + side * (52 * Math.PI / 180);
        ctx.beginPath();
        ctx.moveTo(bx, by);
        ctx.lineTo(bx + Math.cos(tang) * tlen, by + Math.sin(tang) * tlen);
        ctx.stroke();
      }
    }

    ctx.fillStyle = "#FFFFFF";
    ctx.beginPath();
    ctx.arc(ex, ey, size * (fine ? 0.018 : 0.025), 0, Math.PI * 2);
    ctx.fill();
  }

  // Inner hex ring
  const ringR = radius * 0.24;
  ctx.strokeStyle = "rgba(224, 242, 254, 0.85)";
  ctx.lineWidth = Math.max(1.2, armW * 0.7);
  ctx.beginPath();
  for (let i = 0; i <= branches; i++) {
    const a = (((i % branches) * 360) / branches - 90) * (Math.PI / 180);
    const px = cx + Math.cos(a) * ringR;
    const py = cy + Math.sin(a) * ringR;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();

  ctx.fillStyle = "#FFFFFF";
  ctx.beginPath();
  ctx.arc(cx, cy, size * 0.036, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  return c.toDataURL("image/png");
}

function drawSparkleClusterDataUrl(size = 192) {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const ctx = c.getContext("2d");

  const drawStar = (x, y, rOut, rIn, alpha) => {
    ctx.fillStyle = `rgba(255,255,255,${alpha})`;
    ctx.beginPath();
    for (let i = 0; i < 8; i++) {
      const a = (i * 45 - 90) * (Math.PI / 180);
      const r = i % 2 === 0 ? rOut : rIn;
      const px = x + Math.cos(a) * r;
      const py = y + Math.sin(a) * r;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fill();
  };

  ctx.save();
  ctx.shadowColor = "rgba(224, 242, 254, 0.9)";
  ctx.shadowBlur = size * 0.05;
  drawStar(size * 0.44, size * 0.46, size * 0.34, size * 0.068, 0.96);
  drawStar(size * 0.76, size * 0.26, size * 0.16, size * 0.034, 0.86);
  drawStar(size * 0.74, size * 0.74, size * 0.11, size * 0.025, 0.78);

  ctx.fillStyle = "rgba(240, 249, 255, 0.85)";
  for (const [dx, dy, dr] of [[0.20, 0.24, 0.022], [0.26, 0.78, 0.018], [0.84, 0.52, 0.016]]) {
    ctx.beginPath();
    ctx.arc(size * dx, size * dy, size * dr, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
  return c.toDataURL("image/png");
}

function drawRibbonWaveDataUrl(width = 420, height = 96) {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  const ctx = c.getContext("2d");

  ctx.save();
  ctx.lineCap = "round";
  ctx.shadowColor = "rgba(224, 242, 254, 0.85)";
  ctx.shadowBlur = 5;

  const trace = (phase, amp, style, lw) => {
    ctx.strokeStyle = style;
    ctx.lineWidth = lw;
    ctx.beginPath();
    for (let i = 0; i <= 84; i++) {
      const t = i / 84;
      const x = 18 + t * (width - 36);
      const y = height * 0.52 + Math.sin(t * Math.PI * 2 * 1.15 + phase) * (height * amp);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  };

  trace(0, 0.26, "rgba(255, 255, 255, 0.88)", 3);
  trace(0.65, 0.16, "rgba(219, 234, 254, 0.58)", 2);

  ctx.fillStyle = "#FFFFFF";
  for (const idx of [16, 44, 68]) {
    const t = idx / 84;
    const x = 18 + t * (width - 36);
    const y = height * 0.52 + Math.sin(t * Math.PI * 2 * 1.15) * (height * 0.26);
    ctx.beginPath();
    ctx.arc(x, y, idx === 44 ? 5 : 3.5, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
  return c.toDataURL("image/png");
}

function drawArtSealDataUrl(size = 200) {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const ctx = c.getContext("2d");
  const cx = size / 2;
  const cy = size / 2;

  ctx.save();
  ctx.shadowColor = "rgba(224, 242, 254, 0.85)";
  ctx.shadowBlur = 5;
  ctx.strokeStyle = "rgba(255,255,255,0.92)";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.arc(cx, cy, size * 0.41, 0, Math.PI * 2);
  ctx.stroke();

  ctx.strokeStyle = "rgba(224,242,254,0.68)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(cx, cy, size * 0.35, 0, Math.PI * 2);
  ctx.stroke();

  ctx.fillStyle = "rgba(255,255,255,0.95)";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = `600 ${Math.round(size * 0.24)}px "SimSun", "Songti SC", "Noto Serif SC", serif`;
  ctx.fillText("初雪", cx, cy - size * 0.04);

  ctx.fillStyle = "rgba(224,242,254,0.82)";
  ctx.font = `600 ${Math.round(size * 0.085)}px Georgia, serif`;
  ctx.fillText("ORIGINAL", cx, cy + size * 0.20);
  ctx.restore();
  return c.toDataURL("image/png");
}

export function getBuiltinCreativeAssets() {
  return [
    sanitizeCreativeAsset({
      id: "builtin_snowflake_ornate",
      kind: "image",
      name: "❄️ 晶莹雪花",
      role: "accent",
      enabled: true,
      weight: 1.8,
      image_data_url: drawOrnateSnowflakeDataUrl(256, false),
      base_scale: 0.14,
      opacity: 78,
      rotation_range: 30,
      glow_enabled: true,
      builtin: true,
    }),
    sanitizeCreativeAsset({
      id: "builtin_frost_crystal",
      kind: "image",
      name: "❅ 冰晶星芒",
      role: "micro",
      enabled: true,
      weight: 1.5,
      image_data_url: drawOrnateSnowflakeDataUrl(192, true),
      base_scale: 0.075,
      opacity: 62,
      rotation_range: 35,
      glow_enabled: true,
      builtin: true,
    }),
    sanitizeCreativeAsset({
      id: "builtin_sparkle_cluster",
      kind: "image",
      name: "✧ 梦幻星光",
      role: "accent",
      enabled: true,
      weight: 1.2,
      image_data_url: drawSparkleClusterDataUrl(192),
      base_scale: 0.11,
      opacity: 76,
      rotation_range: 22,
      glow_enabled: true,
      builtin: true,
    }),
    sanitizeCreativeAsset({
      id: "builtin_art_seal",
      kind: "image",
      name: "💮 初雪印章",
      role: "accent",
      enabled: true,
      weight: 0.8,
      image_data_url: drawArtSealDataUrl(200),
      base_scale: 0.12,
      opacity: 74,
      rotation_range: 14,
      glow_enabled: true,
      builtin: true,
    }),
    sanitizeCreativeAsset({
      id: "builtin_ribbon_wave",
      kind: "image",
      name: "〰 丝带波纹",
      role: "accent",
      enabled: true,
      weight: 0.7,
      image_data_url: drawRibbonWaveDataUrl(420, 96),
      base_scale: 0.34,
      opacity: 58,
      rotation_range: 10,
      glow_enabled: true,
      builtin: true,
    }),
    sanitizeCreativeAsset({
      id: "builtin_text_hero",
      kind: "text",
      name: "主标题 · 初雪犹如初見",
      role: "hero",
      enabled: true,
      weight: 1.0,
      text: "初雪犹如初見",
      font_name: "宋体",
      color: "#FFFFFF",
      stroke_enabled: true,
      stroke_color: "#1E293B",
      stroke_width: 2,
      glow_enabled: true,
      glow_color: "#E0F2FE",
      glow_radius: 8,
      base_scale: 0.36,
      opacity: 88,
      rotation_range: 4,
      builtin: true,
    }),
    sanitizeCreativeAsset({
      id: "builtin_text_poetic",
      kind: "text",
      name: "诗意配文 · 双语落款",
      role: "accent",
      enabled: true,
      weight: 1.0,
      text: "你代替初雪 降临我身边\nLike quiet snow falling beside you",
      font_name: "微软雅黑",
      color: "#F8FAFC",
      line_spacing: 1.35,
      stroke_enabled: true,
      stroke_color: "#0F172A",
      stroke_width: 1,
      glow_enabled: true,
      glow_color: "#FFFFFF",
      glow_radius: 5,
      base_scale: 0.22,
      opacity: 72,
      rotation_range: 5,
      builtin: true,
    }),
    sanitizeCreativeAsset({
      id: "builtin_text_micro",
      kind: "text",
      name: "微防盗签 · 禁止二改",
      role: "micro",
      enabled: true,
      weight: 1.4,
      text: "Winter · 禁止快转/二改",
      font_name: "微软雅黑",
      color: "#F1F5F9",
      stroke_enabled: true,
      stroke_color: "#0F172A",
      stroke_width: 1,
      glow_enabled: false,
      base_scale: 0.13,
      opacity: 46,
      rotation_range: 10,
      builtin: true,
    }),
  ];
}

/**
 * Convert an uploaded image File into a trimmed, portable CreativeAsset.
 */
export async function fileToCreativeAsset(file, maxEdge = 640) {
  const img = await loadHtmlImageFromFile(file);
  const w0 = img.naturalWidth || img.width || 1;
  const h0 = img.naturalHeight || img.height || 1;
  const scale = Math.max(w0, h0) > maxEdge ? maxEdge / Math.max(w0, h0) : 1;
  const w = Math.max(1, Math.round(w0 * scale));
  const h = Math.max(1, Math.round(h0 * scale));

  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, 0, 0, w, h);

  // Trim fully transparent excess borders for accurate handles & collision
  let finalCanvas = c;
  try {
    const imgData = ctx.getImageData(0, 0, w, h).data;
    let minX = w, minY = h, maxX = -1, maxY = -1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (imgData[(y * w + x) * 4 + 3] > 6) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX >= minX && maxY >= minY) {
      const pad = 2;
      const sx = Math.max(0, minX - pad);
      const sy = Math.max(0, minY - pad);
      const sw = Math.min(w - sx, maxX - minX + 1 + pad * 2);
      const sh = Math.min(h - sy, maxY - minY + 1 + pad * 2);
      if (sw > 4 && sh > 4 && (sw < w - 4 || sh < h - 4)) {
        const trimmed = document.createElement("canvas");
        trimmed.width = sw;
        trimmed.height = sh;
        trimmed.getContext("2d").drawImage(c, sx, sy, sw, sh, 0, 0, sw, sh);
        finalCanvas = trimmed;
      }
    }
  } catch {
    // Ignore taint errors
  }

  return sanitizeCreativeAsset({
    id: newCreativeId("img"),
    kind: "image",
    name: stripExtension(file.name).slice(0, 26) || "图片贴纸",
    role: "auto",
    enabled: true,
    weight: 1.0,
    image_data_url: finalCanvas.toDataURL("image/png"),
    base_scale: 0.14,
    opacity: 82,
    rotation_range: 24,
    glow_enabled: true,
    builtin: false,
  });
}

// ---- IndexedDB persistence with localStorage fallback ----

function openLibraryDB() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("no-idb"));
      return;
    }
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) {
        db.createObjectStore(IDB_STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("idb-open-failed"));
  });
}

async function idbGet(key) {
  const db = await openLibraryDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, "readonly");
    const req = tx.objectStore(IDB_STORE).get(key);
    req.onsuccess = () => resolve(req.result ?? null);
    req.onerror = () => reject(req.error);
  });
}

async function idbSet(key, value) {
  const db = await openLibraryDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, "readwrite");
    tx.objectStore(IDB_STORE).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export class CreativeLibraryStore {
  constructor() {
    this._assets = [];
    this._loaded = false;
  }

  async init() {
    if (this._loaded) return this.listAssets();
    let stored = null;
    try {
      stored = await idbGet(IDB_KEY);
    } catch {
      try {
        const raw = localStorage.getItem(LS_FALLBACK_KEY);
        if (raw) stored = JSON.parse(raw);
      } catch {
        stored = null;
      }
    }
    const parsed = CreativeLibraryStore.parsePayload(stored);
    this._assets = parsed.length > 0 ? parsed : getBuiltinCreativeAssets();
    this._loaded = true;
    return this.listAssets();
  }

  async _persist() {
    const payload = CreativeLibraryStore.buildExportPayload(this._assets);
    try {
      await idbSet(IDB_KEY, payload);
    } catch {
      try {
        localStorage.setItem(LS_FALLBACK_KEY, JSON.stringify(payload));
      } catch {
        // Storage quota exceeded; keep in memory
      }
    }
  }

  listAssets() {
    return this._assets.map((a) => cloneAsset(a, false));
  }

  assetMap() {
    const map = new Map();
    for (const a of this._assets) map.set(a.id, a);
    return map;
  }

  getAsset(id) {
    const found = this._assets.find((a) => a.id === id);
    return found ? cloneAsset(found, false) : null;
  }

  async addAsset(asset) {
    const item = cloneAsset(asset, false);
    const ids = new Set(this._assets.map((a) => a.id));
    if (ids.has(item.id)) item.id = newCreativeId(item.kind === "image" ? "img" : "txt");
    this._assets.push(item);
    await this._persist();
    return cloneAsset(item, false);
  }

  async updateAsset(asset) {
    const idx = this._assets.findIndex((a) => a.id === asset.id);
    if (idx < 0) return false;
    this._assets[idx] = cloneAsset(asset, false);
    await this._persist();
    return true;
  }

  async deleteAsset(id) {
    const before = this._assets.length;
    this._assets = this._assets.filter((a) => a.id !== id);
    if (this._assets.length !== before) {
      await this._persist();
      return true;
    }
    return false;
  }

  async resetToBuiltins() {
    this._assets = getBuiltinCreativeAssets();
    await this._persist();
    return this.listAssets();
  }

  static buildExportPayload(assets) {
    return {
      schema: CREATIVE_LIBRARY_SCHEMA_ID,
      version: CREATIVE_LIBRARY_SCHEMA_VERSION,
      assets: assets.map((a) => sanitizeCreativeAsset(a)),
    };
  }

  static parsePayload(raw) {
    if (!raw) return [];
    const list = Array.isArray(raw) ? raw : Array.isArray(raw.assets) ? raw.assets : [];
    const out = [];
    for (const entry of list) {
      if (!entry || typeof entry !== "object") continue;
      const asset = sanitizeCreativeAsset(entry);
      if (asset.kind === "image" && !asset.image_data_url) continue;
      if (asset.kind === "text" && !asset.text.trim()) continue;
      out.push(asset);
    }
    return out;
  }

  async importJsonText(jsonText, { replace = false } = {}) {
    const raw = JSON.parse(jsonText);
    const parsed = CreativeLibraryStore.parsePayload(raw);
    if (!parsed.length) throw new Error("文件中未找到有效的创作模式水印库素材");
    if (replace) {
      this._assets = parsed;
    } else {
      const ids = new Set(this._assets.map((a) => a.id));
      for (const item of parsed) {
        if (ids.has(item.id)) item.id = newCreativeId(item.kind === "image" ? "img" : "txt");
        ids.add(item.id);
        this._assets.push(item);
      }
    }
    await this._persist();
    return parsed;
  }

  exportJsonText() {
    return JSON.stringify(CreativeLibraryStore.buildExportPayload(this._assets), null, 2);
  }
}
