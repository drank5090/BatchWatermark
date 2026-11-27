/**
 * Data models for BatchWatermark v2.0 Creative Mode (Web Edition).
 * 100% JSON schema compatible with Desktop Python CreativeLibraryStore.
 */

import { clamp } from "./models.js";

export const CREATIVE_LIBRARY_SCHEMA_ID = "batch_watermark_creative_library";
export const CREATIVE_LIBRARY_SCHEMA_VERSION = 1;

export const ROLE_LABELS = {
  auto: "智能",
  hero: "主视觉",
  accent: "装饰",
  micro: "微底纹",
};

export const LAYOUT_STYLES = [
  { value: "artistic_scatter", label: "艺术错落 · 示例同款（推荐）" },
  { value: "frame_halo", label: "边框环绕 · 中心人物通透" },
  { value: "full_anti_theft", label: "全图防盗 · 多尺寸防抠图" },
  { value: "magazine_editorial", label: "杂志海报 · 主标题+点缀" },
];

export function newCreativeId(prefix = "id") {
  const rand = Math.random().toString(36).slice(2, 10);
  const ts = Date.now().toString(36).slice(-4);
  return `${prefix}_${ts}${rand}`;
}

export function defaultAutoLayoutConfig() {
  return {
    style: "artistic_scatter",
    density: 58,
    scale_variation: 72,
    subject_avoidance: 75,
    global_opacity: 78,
    rotation_jitter: 18,
    soft_glow: true,
    include_micro_grid: true,
    seed: 202601,
  };
}

export function sanitizeCreativeAsset(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  const kind = src.kind === "image" ? "image" : "text";
  const validRoles = new Set(["auto", "hero", "accent", "micro"]);
  const role = validRoles.has(src.role) ? src.role : "auto";
  return {
    id: String(src.id || newCreativeId(kind === "image" ? "img" : "txt")),
    kind,
    name: String(src.name || (kind === "image" ? "图片贴纸" : "文字水印")).slice(0, 40),
    role,
    enabled: src.enabled !== false,
    weight: clamp(Number(src.weight) || 1.0, 0.2, 3.0),
    image_data_url: String(src.image_data_url || ""),
    text: String(src.text || ""),
    font_name: String(src.font_name || "宋体"),
    custom_font_path: String(src.custom_font_path || ""),
    color: String(src.color || "#FFFFFF"),
    line_spacing: clamp(Number(src.line_spacing) || 1.25, 1.0, 2.4),
    stroke_enabled: src.stroke_enabled !== false,
    stroke_color: String(src.stroke_color || "#1E293B"),
    stroke_width: Math.round(clamp(Number(src.stroke_width ?? 2), 0, 12)),
    glow_enabled: src.glow_enabled !== false,
    glow_color: String(src.glow_color || "#FFFFFF"),
    glow_radius: Math.round(clamp(Number(src.glow_radius ?? 6), 0, 24)),
    base_scale: clamp(Number(src.base_scale) || 0.14, 0.03, 0.55),
    opacity: Math.round(clamp(Number(src.opacity ?? 75), 10, 100)),
    rotation_range: Math.round(clamp(Number(src.rotation_range ?? 18), 0, 45)),
    builtin: Boolean(src.builtin),
  };
}

export function cloneAsset(asset, newIdFlag = false) {
  const copy = sanitizeCreativeAsset(asset);
  if (newIdFlag) copy.id = newCreativeId(copy.kind === "image" ? "img" : "txt");
  return copy;
}

export function createPlacement(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  return {
    id: String(src.id || newCreativeId("lyr")),
    asset_id: String(src.asset_id || ""),
    x: clamp(Number(src.x ?? 0.5), -0.15, 1.15),
    y: clamp(Number(src.y ?? 0.5), -0.15, 1.15),
    scale: clamp(Number(src.scale ?? 0.14), 0.025, 0.85),
    rotation: clamp(Number(src.rotation ?? 0), -180, 180),
    opacity: Math.round(clamp(Number(src.opacity ?? 75), 5, 100)),
    glow_enabled: src.glow_enabled !== false,
    locked: Boolean(src.locked),
    auto_generated: Boolean(src.auto_generated),
    z_index: Math.round(Number(src.z_index ?? 0)),
  };
}

export function clonePlacement(layer, newIdFlag = false) {
  const copy = createPlacement(layer);
  if (newIdFlag) copy.id = newCreativeId("lyr");
  return copy;
}
