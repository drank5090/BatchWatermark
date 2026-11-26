/**
 * Watermark configuration models & built-in presets.
 * 100% JSON schema compatible with Desktop Python BatchWatermark presets.
 */

export const PRESET_SCHEMA_ID = "batch_watermark_presets";
export const PRESET_SCHEMA_VERSION = 1;

export const SUPPORTED_IMAGE_EXTS = new Set([
  ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif",
]);

export const SUPPORTED_VIDEO_EXTS = new Set([
  ".mp4", ".webm", ".mov", ".m4v", ".mkv", ".ogv", ".avi",
]);

export const FONT_FAMILY_MAP = {
  "微软雅黑": '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif',
  "微软雅黑 粗体": 'bold "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif',
  "黑体": '"SimHei", "Heiti SC", "Noto Sans SC", sans-serif',
  "宋体": '"SimSun", "Songti SC", "Noto Serif SC", serif',
  "楷体": '"KaiTi", "Kaiti SC", serif',
  "仿宋": '"FangSong", "STFangsong", serif',
  "等线": '"DengXian", "Microsoft YaHei", sans-serif',
  "PingFang SC": '"PingFang SC", "Microsoft YaHei", sans-serif',
  "Segoe UI": '"Segoe UI", Arial, sans-serif',
  "Arial": 'Arial, Helvetica, sans-serif',
  "Georgia": 'Georgia, serif',
  "Monospace": '"Consolas", "Courier New", monospace',
};

export function defaultWatermarkConfig() {
  return {
    watermark_type: "text", // "text" | "image"
    text: "© 仅供内部使用",
    font_name: "微软雅黑",
    custom_font_path: "",
    font_size: 44,
    proportional_size: true,
    text_color: "#FFFFFF",
    line_spacing: 1.25,
    stroke_enabled: true,
    stroke_width: 2,
    stroke_color: "#000000",
    shadow_enabled: true,
    shadow_offset: 3,
    shadow_color: "#000000",
    logo_path: "",
    logo_scale_percent: 22,
    opacity: 55,
    rotation: -25,
    layout_mode: "tiled", // "tiled" | "single"
    anchor: "bottom_right",
    margin_x_percent: 4.0,
    margin_y_percent: 4.0,
    offset_x_percent: 0.0,
    offset_y_percent: 0.0,
    tile_spacing_x: 120,
    tile_spacing_y: 100,
    tile_stagger: true,
  };
}

export function cloneConfig(cfg) {
  return { ...defaultWatermarkConfig(), ...cfg };
}

export function sanitizeConfig(raw) {
  const base = defaultWatermarkConfig();
  if (!raw || typeof raw !== "object") return base;
  const out = { ...base };
  for (const key of Object.keys(base)) {
    if (key in raw && raw[key] !== undefined && raw[key] !== null) {
      out[key] = raw[key];
    }
  }
  if (!["text", "image"].includes(out.watermark_type)) out.watermark_type = "text";
  if (!["tiled", "single"].includes(out.layout_mode)) out.layout_mode = "tiled";
  const validAnchors = new Set([
    "top_left", "top_center", "top_right",
    "middle_left", "center", "middle_right",
    "bottom_left", "bottom_center", "bottom_right",
  ]);
  if (!validAnchors.has(out.anchor)) out.anchor = "bottom_right";
  out.font_size = clamp(Number(out.font_size) || 44, 10, 220);
  out.line_spacing = clamp(Number(out.line_spacing) || 1.25, 1.0, 2.5);
  out.stroke_width = clamp(Number(out.stroke_width) || 2, 1, 16);
  out.shadow_offset = clamp(Number(out.shadow_offset) || 3, 1, 20);
  out.logo_scale_percent = clamp(Number(out.logo_scale_percent) || 22, 3, 100);
  out.opacity = clamp(Number(out.opacity) ?? 55, 0, 100);
  out.rotation = clamp(Number(out.rotation) || 0, -180, 180);
  out.margin_x_percent = clamp(Number(out.margin_x_percent) || 0, 0, 30);
  out.margin_y_percent = clamp(Number(out.margin_y_percent) || 0, 0, 30);
  out.offset_x_percent = clamp(Number(out.offset_x_percent) || 0, -40, 40);
  out.offset_y_percent = clamp(Number(out.offset_y_percent) || 0, -40, 40);
  out.tile_spacing_x = clamp(Number(out.tile_spacing_x) || 120, 10, 500);
  out.tile_spacing_y = clamp(Number(out.tile_spacing_y) || 100, 10, 500);
  return out;
}

export function getBuiltinPresets() {
  return {
    "全图斜向平铺 (防盗)": cloneConfig({
      text: "© 仅供内部使用",
      font_size: 42,
      text_color: "#FFFFFF",
      stroke_enabled: true,
      stroke_width: 2,
      shadow_enabled: true,
      opacity: 48,
      rotation: -25,
      layout_mode: "tiled",
      tile_spacing_x: 130,
      tile_spacing_y: 110,
      tile_stagger: true,
    }),
    "右下角精致签名": cloneConfig({
      text: "© 2026 Photography",
      font_size: 34,
      text_color: "#FFFFFF",
      stroke_enabled: false,
      shadow_enabled: true,
      shadow_offset: 2,
      opacity: 82,
      rotation: 0,
      layout_mode: "single",
      anchor: "bottom_right",
      margin_x_percent: 3.5,
      margin_y_percent: 3.5,
    }),
    "正中心醒目样图": cloneConfig({
      text: "SAMPLE · 样图",
      font_size: 76,
      text_color: "#FFFFFF",
      stroke_enabled: true,
      stroke_width: 3,
      shadow_enabled: true,
      opacity: 62,
      rotation: -20,
      layout_mode: "single",
      anchor: "center",
    }),
    "底部居中版权栏": cloneConfig({
      text: "版权所有 · 严禁未经授权转载",
      font_size: 30,
      text_color: "#F3F4F6",
      stroke_enabled: true,
      stroke_width: 2,
      stroke_color: "#111827",
      shadow_enabled: false,
      opacity: 85,
      rotation: 0,
      layout_mode: "single",
      anchor: "bottom_center",
      margin_y_percent: 2.5,
    }),
  };
}

export function clamp(val, min, max) {
  return Math.max(min, Math.min(max, val));
}

export function getFileExtension(name) {
  const idx = name.lastIndexOf(".");
  return idx >= 0 ? name.slice(idx).toLowerCase() : "";
}

export function stripExtension(name) {
  const idx = name.lastIndexOf(".");
  return idx > 0 ? name.slice(0, idx) : name;
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const hrs = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const mm = String(mins).padStart(2, "0");
  const ss = String(secs).padStart(2, "0");
  return hrs > 0 ? `${String(hrs).padStart(2, "0")}:${mm}:${ss}` : `${mm}:${ss}`;
}
