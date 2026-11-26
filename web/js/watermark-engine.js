/**
 * Pure HTML5 Canvas 2D watermarking engine with exact WYSIWYG parity
 * across thumbnail previews, full-res image export, and video overlays.
 */

import { FONT_FAMILY_MAP, getFileExtension } from "./models.js";

export const PREVIEW_MAX_EDGE = 640;

function resolveCanvasFont(config, fontPx, customFontFamily) {
  if (customFontFamily) {
    return `${fontPx}px "${customFontFamily}", sans-serif`;
  }
  const spec = FONT_FAMILY_MAP[config.font_name] || FONT_FAMILY_MAP["微软雅黑"];
  if (spec.startsWith("bold ")) {
    return `bold ${fontPx}px ${spec.slice(5)}`;
  }
  return `${fontPx}px ${spec}`;
}

function buildTextStampCanvas(config, canvasW, canvasH, refW, refH, customFontFamily) {
  const rawText = String(config.text || "");
  if (!rawText.trim()) return null;

  const lines = rawText.split(/\r?\n/);
  const previewRatio = canvasW / Math.max(1, refW);
  const refShort = Math.min(refW, refH);

  let fontPx;
  let unitScale;
  if (config.proportional_size) {
    fontPx = config.font_size * (refShort / 1000) * previewRatio;
    unitScale = (refShort / 1000) * previewRatio;
  } else {
    fontPx = config.font_size * previewRatio;
    unitScale = previewRatio;
  }
  fontPx = Math.max(6, Math.round(fontPx));

  let strokeW = config.stroke_enabled ? Math.round(config.stroke_width * unitScale) : 0;
  if (config.stroke_enabled && config.stroke_width > 0 && strokeW === 0) strokeW = 1;

  let shadowOff = config.shadow_enabled ? Math.round(config.shadow_offset * unitScale) : 0;
  if (config.shadow_enabled && config.shadow_offset > 0 && shadowOff === 0) shadowOff = 1;

  const lineHeight = Math.max(fontPx, Math.round(fontPx * Math.max(1.0, config.line_spacing || 1.25)));
  const fontCss = resolveCanvasFont(config, fontPx, customFontFamily);

  // Measure lines accurately
  const measureCanvas = document.createElement("canvas");
  const mctx = measureCanvas.getContext("2d");
  mctx.font = fontCss;
  let maxLineW = 1;
  for (const line of lines) {
    const metrics = mctx.measureText(line || " ");
    maxLineW = Math.max(maxLineW, Math.ceil(metrics.width));
  }

  const textW = maxLineW;
  const textH = Math.ceil(fontPx + (lines.length - 1) * lineHeight);
  const pad = strokeW + 6;
  const stampW = Math.max(2, textW + pad * 2 + shadowOff);
  const stampH = Math.max(2, textH + pad * 2 + shadowOff);

  const stamp = document.createElement("canvas");
  stamp.width = stampW;
  stamp.height = stampH;
  const ctx = stamp.getContext("2d");
  ctx.font = fontCss;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.lineJoin = "round";
  ctx.miterLimit = 2;

  const centerX = pad + textW / 2;
  const startY = pad;

  // Drop shadow pass
  if (shadowOff > 0) {
    ctx.save();
    ctx.globalAlpha = 0.65;
    ctx.fillStyle = config.shadow_color || "#000000";
    ctx.strokeStyle = config.shadow_color || "#000000";
    ctx.lineWidth = strokeW * 2;
    for (let i = 0; i < lines.length; i++) {
      const y = startY + i * lineHeight + shadowOff;
      if (strokeW > 0) ctx.strokeText(lines[i], centerX + shadowOff, y);
      ctx.fillText(lines[i], centerX + shadowOff, y);
    }
    ctx.restore();
  }

  // Main stroke + fill pass
  if (strokeW > 0) {
    ctx.strokeStyle = config.stroke_color || "#000000";
    ctx.lineWidth = strokeW * 2;
    for (let i = 0; i < lines.length; i++) {
      ctx.strokeText(lines[i], centerX, startY + i * lineHeight);
    }
  }

  ctx.fillStyle = config.text_color || "#FFFFFF";
  for (let i = 0; i < lines.length; i++) {
    ctx.fillText(lines[i], centerX, startY + i * lineHeight);
  }

  return stamp;
}

function buildLogoStampCanvas(config, canvasW, canvasH, refW, logoImage) {
  if (!logoImage) return null;
  const lw = logoImage.naturalWidth || logoImage.width || 0;
  const lh = logoImage.naturalHeight || logoImage.height || 0;
  if (lw <= 0 || lh <= 0) return null;

  const previewRatio = canvasW / Math.max(1, refW);
  const scalePct = Math.max(1, Math.min(300, Number(config.logo_scale_percent) || 22));

  let targetW;
  if (config.proportional_size) {
    targetW = Math.max(8, Math.round(refW * (scalePct / 100) * previewRatio));
  } else {
    targetW = Math.max(8, Math.round(lw * (scalePct / 100) * previewRatio));
  }
  const targetH = Math.max(8, Math.round(targetW * (lh / lw)));

  const stamp = document.createElement("canvas");
  stamp.width = targetW;
  stamp.height = targetH;
  const ctx = stamp.getContext("2d");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(logoImage, 0, 0, targetW, targetH);
  return stamp;
}

function rotateStampCanvas(stamp, angleDeg) {
  if (Math.abs(angleDeg) < 0.01) return stamp;
  // Pillow positive rotation is CCW; Canvas positive rotation is CW -> negate angle
  const canvasRad = (-angleDeg * Math.PI) / 180;
  const cos = Math.abs(Math.cos(canvasRad));
  const sin = Math.abs(Math.sin(canvasRad));
  const rw = Math.max(2, Math.ceil(stamp.width * cos + stamp.height * sin));
  const rh = Math.max(2, Math.ceil(stamp.width * sin + stamp.height * cos));

  const out = document.createElement("canvas");
  out.width = rw;
  out.height = rh;
  const ctx = out.getContext("2d");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.translate(rw / 2, rh / 2);
  ctx.rotate(canvasRad);
  ctx.drawImage(stamp, -stamp.width / 2, -stamp.height / 2);
  return out;
}

function computeSinglePosition(canvasW, canvasH, rw, rh, config) {
  const marginX = canvasW * ((config.margin_x_percent || 0) / 100);
  const marginY = canvasH * ((config.margin_y_percent || 0) / 100);
  const anchor = config.anchor || "bottom_right";

  let x;
  if (anchor === "top_left" || anchor === "middle_left" || anchor === "bottom_left") {
    x = marginX;
  } else if (anchor === "top_center" || anchor === "center" || anchor === "bottom_center") {
    x = (canvasW - rw) / 2;
  } else {
    x = canvasW - rw - marginX;
  }

  let y;
  if (anchor === "top_left" || anchor === "top_center" || anchor === "top_right") {
    y = marginY;
  } else if (anchor === "middle_left" || anchor === "center" || anchor === "middle_right") {
    y = (canvasH - rh) / 2;
  } else {
    y = canvasH - rh - marginY;
  }

  x += canvasW * ((config.offset_x_percent || 0) / 100);
  y += canvasH * ((config.offset_y_percent || 0) / 100);
  return { x: Math.round(x), y: Math.round(y) };
}

/**
 * Draw configured watermark directly onto `ctx` (which may be a transparent overlay
 * canvas or a composited image canvas).
 */
export function drawWatermarkOverlay(
  ctx,
  canvasW,
  canvasH,
  config,
  refW,
  refH,
  { logoImage = null, customFontFamily = "" } = {},
) {
  const opacity = Math.max(0, Math.min(100, Number(config.opacity) ?? 55)) / 100;
  if (opacity <= 0.001) return;

  const stamp =
    config.watermark_type === "image"
      ? buildLogoStampCanvas(config, canvasW, canvasH, refW, logoImage)
      : buildTextStampCanvas(config, canvasW, canvasH, refW, refH, customFontFamily);

  if (!stamp) return;

  const origSW = stamp.width;
  const origSH = stamp.height;
  const angle = Number(config.rotation) || 0;
  const rotStamp = rotateStampCanvas(stamp, angle);
  const rw = rotStamp.width;
  const rh = rotStamp.height;

  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";

  if (config.layout_mode === "single") {
    const { x, y } = computeSinglePosition(canvasW, canvasH, rw, rh, config);
    ctx.drawImage(rotStamp, x, y);
  } else {
    const previewRatio = canvasW / Math.max(1, refW);
    const refShort = Math.min(refW, refH);
    const unitScale = config.proportional_size ? (refShort / 1000) * previewRatio : previewRatio;

    const gapX = Math.max(0, (config.tile_spacing_x || 0) * unitScale);
    const gapY = Math.max(0, (config.tile_spacing_y || 0) * unitScale);

    const stepX = Math.max(12, origSW + gapX);
    const stepY = Math.max(12, origSH + gapY);

    const rad = (angle * Math.PI) / 180;
    const cosA = Math.cos(rad);
    const sinA = Math.sin(rad);

    // Rotated basis vectors aligned with CCW rotation
    const ux = cosA;
    const uy = -sinA;
    const vx = sinA;
    const vy = cosA;

    const cxCanvas = canvasW / 2 + canvasW * ((config.offset_x_percent || 0) / 100);
    const cyCanvas = canvasH / 2 + canvasH * ((config.offset_y_percent || 0) / 100);

    const radius = Math.hypot(canvasW, canvasH) * 0.55 + Math.max(rw, rh);
    const maxI = Math.min(80, Math.ceil(radius / stepX) + 1);
    const maxJ = Math.min(80, Math.ceil(radius / stepY) + 1);

    const halfRW = rw / 2;
    const halfRH = rh / 2;

    for (let j = -maxJ; j <= maxJ; j++) {
      const staggerShift = config.tile_stagger && j % 2 !== 0 ? 0.5 : 0;
      for (let i = -maxI; i <= maxI; i++) {
        const lx = (i + staggerShift) * stepX;
        const ly = j * stepY;

        const centerX = cxCanvas + lx * ux + ly * vx;
        const centerY = cyCanvas + lx * uy + ly * vy;

        const px = Math.round(centerX - halfRW);
        const py = Math.round(centerY - halfRH);

        if (px >= canvasW || py >= canvasH || px + rw <= 0 || py + rh <= 0) continue;
        ctx.drawImage(rotStamp, px, py);
      }
    }
  }

  ctx.restore();
}

/**
 * Create a standalone transparent overlay canvas for fast reuse across video frames.
 */
export function buildOverlayCanvas(width, height, config, renderOpts) {
  const overlay = document.createElement("canvas");
  overlay.width = width;
  overlay.height = height;
  const ctx = overlay.getContext("2d");
  drawWatermarkOverlay(ctx, width, height, config, width, height, renderOpts);
  return overlay;
}

/**
 * Load an image File with browser EXIF auto-orientation and generate a fast preview canvas.
 */
export async function loadImagePreview(file, maxEdge = PREVIEW_MAX_EDGE) {
  let bitmap;
  if (typeof createImageBitmap === "function") {
    try {
      bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch {
      bitmap = await createImageBitmap(file);
    }
  } else {
    bitmap = await loadHtmlImageFromFile(file);
  }

  const origW = bitmap.width;
  const origH = bitmap.height;
  let pw = origW;
  let ph = origH;
  if (Math.max(origW, origH) > maxEdge) {
    const scale = maxEdge / Math.max(origW, origH);
    pw = Math.max(1, Math.round(origW * scale));
    ph = Math.max(1, Math.round(origH * scale));
  }

  const previewCanvas = document.createElement("canvas");
  previewCanvas.width = pw;
  previewCanvas.height = ph;
  const ctx = previewCanvas.getContext("2d");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(bitmap, 0, 0, pw, ph);

  if (typeof bitmap.close === "function") bitmap.close();

  return { previewCanvas, origW, origH };
}

export function loadHtmlImageFromFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error(`无法解析图片：${file.name}`));
    };
    img.src = url;
  });
}

function resolveImageMimeAndExt(filename, outputFormat) {
  if (outputFormat === "jpeg") return { mime: "image/jpeg", ext: ".jpg" };
  if (outputFormat === "png") return { mime: "image/png", ext: ".png" };
  if (outputFormat === "webp") return { mime: "image/webp", ext: ".webp" };

  const origExt = getFileExtension(filename);
  if (origExt === ".jpg" || origExt === ".jpeg") return { mime: "image/jpeg", ext: origExt };
  if (origExt === ".webp") return { mime: "image/webp", ext: ".webp" };
  return { mime: "image/png", ext: ".png" };
}

/**
 * Render full-resolution watermarked image Blob ready for ZIP or File System write.
 */
export async function exportImageBlob(item, config, exportConfig, renderOpts) {
  let source;
  if (typeof createImageBitmap === "function") {
    try {
      source = await createImageBitmap(item.file, { imageOrientation: "from-image" });
    } catch {
      source = await createImageBitmap(item.file);
    }
  } else {
    source = await loadHtmlImageFromFile(item.file);
  }

  const w = source.width;
  const h = source.height;
  const { mime, ext } = resolveImageMimeAndExt(item.filename, exportConfig.outputFormat);

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");

  if (mime === "image/jpeg") {
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, w, h);
  }
  ctx.drawImage(source, 0, 0, w, h);
  if (typeof source.close === "function") source.close();

  drawWatermarkOverlay(ctx, w, h, config, w, h, renderOpts);

  const quality = Math.max(0.5, Math.min(1.0, (exportConfig.quality || 92) / 100));
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("图片编码失败"))),
      mime,
      mime === "image/png" ? undefined : quality,
    );
  });

  return { blob, ext };
}
