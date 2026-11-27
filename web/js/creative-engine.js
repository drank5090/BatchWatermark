/**
 * Subject-aware multi-scale aesthetic auto-layout algorithm and Canvas 2D compositor
 * for BatchWatermark v2.0 Creative Mode (100% parity with Desktop Python engine).
 */

import { createPlacement, newCreativeId } from "./creative-models.js";
import { FONT_FAMILY_MAP, getFileExtension } from "./models.js";
import { loadHtmlImageFromFile } from "./watermark-engine.js";

const SALIENCY_GRID = 48;

class Mulberry32 {
  constructor(seed) {
    this._state = seed >>> 0;
  }
  next() {
    this._state = (this._state + 0x6d2b79f5) >>> 0;
    let t = this._state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  uniform(lo, hi) {
    return lo + (hi - lo) * this.next();
  }
  weightedChoice(items) {
    let total = 0;
    for (const a of items) total += Math.max(0.05, Number(a.weight) || 1);
    let pick = this.next() * total;
    for (const a of items) {
      pick -= Math.max(0.05, Number(a.weight) || 1);
      if (pick <= 0) return a;
    }
    return items[items.length - 1];
  }
}

// ---- Image Decoding Cache ----

export function ensureAssetImageLoaded(asset, imageCache) {
  if (!asset || asset.kind !== "image" || !asset.image_data_url) return Promise.resolve(null);
  const existing = imageCache.get(asset.id);
  if (existing && existing._srcUrl === asset.image_data_url && existing.complete && existing.naturalWidth > 0) {
    return Promise.resolve(existing);
  }
  return new Promise((resolve) => {
    const img = new Image();
    img._srcUrl = asset.image_data_url;
    img.onload = () => {
      imageCache.set(asset.id, img);
      resolve(img);
    };
    img.onerror = () => resolve(null);
    img.src = asset.image_data_url;
  });
}

export async function preloadAllAssetImages(assets, imageCache) {
  await Promise.all(assets.map((a) => ensureAssetImageLoaded(a, imageCache)));
}

// ---- Visual Saliency & Portrait-Center Protection Grid ----

export function computeSaliencyGrid(sourceCanvas) {
  if (!sourceCanvas) return null;
  const c = document.createElement("canvas");
  c.width = SALIENCY_GRID;
  c.height = SALIENCY_GRID;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(sourceCanvas, 0, 0, SALIENCY_GRID, SALIENCY_GRID);
  const data = ctx.getImageData(0, 0, SALIENCY_GRID, SALIENCY_GRID).data;

  const lum = new Float32Array(SALIENCY_GRID * SALIENCY_GRID);
  const sat = new Float32Array(SALIENCY_GRID * SALIENCY_GRID);
  for (let i = 0; i < SALIENCY_GRID * SALIENCY_GRID; i++) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    lum[i] = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    const mx = Math.max(r, g, b);
    const mn = Math.min(r, g, b);
    sat[i] = mx > 12 ? (mx - mn) / mx : 0;
  }

  const raw = new Float32Array(SALIENCY_GRID * SALIENCY_GRID);
  let maxVal = 1e-6;
  for (let y = 0; y < SALIENCY_GRID; y++) {
    const ny = (y + 0.5) / SALIENCY_GRID;
    for (let x = 0; x < SALIENCY_GRID; x++) {
      const nx = (x + 0.5) / SALIENCY_GRID;
      const xm = Math.max(0, x - 1);
      const xp = Math.min(SALIENCY_GRID - 1, x + 1);
      const ym = Math.max(0, y - 1);
      const yp = Math.min(SALIENCY_GRID - 1, y + 1);
      const gx = Math.abs(lum[y * SALIENCY_GRID + xp] - lum[y * SALIENCY_GRID + xm]);
      const gy = Math.abs(lum[yp * SALIENCY_GRID + x] - lum[ym * SALIENCY_GRID + x]);
      const edge = Math.min(1, Math.hypot(gx, gy) * 2.2);

      const dx = (nx - 0.50) / 0.25;
      const dy = (ny - 0.42) / 0.28;
      const centerPrior = Math.exp(-0.5 * (dx * dx + dy * dy));

      const score = 0.52 * centerPrior + 0.36 * edge + 0.12 * sat[y * SALIENCY_GRID + x];
      raw[y * SALIENCY_GRID + x] = score;
      if (score > maxVal) maxVal = score;
    }
  }

  const smoothed = new Float32Array(SALIENCY_GRID * SALIENCY_GRID);
  for (let y = 0; y < SALIENCY_GRID; y++) {
    for (let x = 0; x < SALIENCY_GRID; x++) {
      let acc = 0;
      let cnt = 0;
      for (let yy = Math.max(0, y - 1); yy <= Math.min(SALIENCY_GRID - 1, y + 1); yy++) {
        for (let xx = Math.max(0, x - 1); xx <= Math.min(SALIENCY_GRID - 1, x + 1); xx++) {
          acc += raw[yy * SALIENCY_GRID + xx];
          cnt++;
        }
      }
      smoothed[y * SALIENCY_GRID + x] = Math.min(1, acc / cnt / maxVal);
    }
  }
  return smoothed;
}

function sampleSaliency(grid, nx, ny, radiusNorm = 0.05) {
  if (!grid) {
    const dx = (nx - 0.50) / 0.26;
    const dy = (ny - 0.42) / 0.28;
    return Math.exp(-0.5 * (dx * dx + dy * dy));
  }
  const cx = Math.max(0, Math.min(SALIENCY_GRID - 1, Math.floor(nx * SALIENCY_GRID)));
  const cy = Math.max(0, Math.min(SALIENCY_GRID - 1, Math.floor(ny * SALIENCY_GRID)));
  const rad = Math.max(1, Math.round(radiusNorm * SALIENCY_GRID));
  let acc = 0;
  let cnt = 0;
  for (let yy = Math.max(0, cy - rad); yy <= Math.min(SALIENCY_GRID - 1, cy + rad); yy++) {
    for (let xx = Math.max(0, cx - rad); xx <= Math.min(SALIENCY_GRID - 1, cx + rad); xx++) {
      acc += grid[yy * SALIENCY_GRID + xx];
      cnt++;
    }
  }
  return acc / Math.max(1, cnt);
}

// ---- Asset Aspect & Stamp Rendering ----

export function estimateAssetAspect(asset, imageCache) {
  if (asset.kind === "image") {
    const im = imageCache?.get(asset.id);
    if (im && im.naturalWidth > 0) {
      return Math.max(0.18, Math.min(4.0, im.naturalHeight / im.naturalWidth));
    }
    return 1.0;
  }
  const lines = String(asset.text || "").split(/\r?\n/).filter((l) => l.trim());
  const nonEmpty = lines.length ? lines : ["A"];
  let maxUnits = 1.5;
  for (const ln of nonEmpty) {
    let units = 0;
    for (const ch of ln) units += ch.charCodeAt(0) > 127 ? 1.0 : 0.58;
    if (units > maxUnits) maxUnits = units;
  }
  const aspect = (nonEmpty.length * Math.max(1.0, asset.line_spacing || 1.25)) / maxUnits;
  return Math.max(0.16, Math.min(2.5, aspect));
}

function resolveFontCss(asset, fontPx) {
  const spec = FONT_FAMILY_MAP[asset.font_name] || FONT_FAMILY_MAP["宋体"];
  if (spec.startsWith("bold ")) return `bold ${fontPx}px ${spec.slice(5)}`;
  return `${fontPx}px ${spec}`;
}

/**
 * Render an unrotated Canvas stamp whose visible content width matches `targetW`.
 */
export function renderAssetStampCanvas(
  asset,
  targetW,
  { opacity = 80, glowEnabled = true, imageCache = null } = {},
) {
  const w = Math.max(8, Math.round(targetW));
  const alpha = Math.max(0, Math.min(1, (Number(opacity) || 0) / 100));
  if (alpha <= 0.005) return null;

  if (asset.kind === "image") {
    const im = imageCache?.get(asset.id);
    if (!im || !im.complete || im.naturalWidth <= 0) return null;
    const h = Math.max(8, Math.round(w * (im.naturalHeight / im.naturalWidth)));
    const useGlow = Boolean(glowEnabled && asset.glow_enabled);
    const blurPx = useGlow ? Math.max(2, Math.min(14, Math.round(w * 0.04))) : 0;
    const pad = useGlow ? blurPx * 2 + 2 : 0;

    const stamp = document.createElement("canvas");
    stamp.width = w + pad * 2;
    stamp.height = h + pad * 2;
    const ctx = stamp.getContext("2d");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.globalAlpha = alpha;

    if (useGlow) {
      // Subtle dark grounding halo then dreamy white outer glow
      ctx.save();
      ctx.shadowColor = "rgba(15, 23, 42, 0.45)";
      ctx.shadowBlur = Math.max(1.5, blurPx * 0.7);
      ctx.shadowOffsetX = 1;
      ctx.shadowOffsetY = 1;
      ctx.drawImage(im, pad, pad, w, h);
      ctx.restore();

      ctx.save();
      ctx.shadowColor = asset.glow_color || "#FFFFFF";
      ctx.shadowBlur = blurPx;
      ctx.drawImage(im, pad, pad, w, h);
      ctx.restore();
    } else {
      ctx.drawImage(im, 0, 0, w, h);
    }
    return stamp;
  }

  // Text watermark stamp scaled precisely to target width `w`
  const rawText = String(asset.text || "").replace(/^\r?\n+|\r?\n+$/g, "");
  if (!rawText.trim()) return null;
  const lines = rawText.split(/\r?\n/);

  const meas = document.createElement("canvas").getContext("2d");
  meas.font = resolveFontCss(asset, 64);
  let refW = 1;
  for (const ln of lines) {
    refW = Math.max(refW, meas.measureText(ln || " ").width);
  }
  const fontPx = Math.max(8, Math.min(420, Math.round(64 * (w / refW))));
  const fontCss = resolveFontCss(asset, fontPx);
  meas.font = fontCss;
  let actualW = 2;
  for (const ln of lines) actualW = Math.max(actualW, Math.ceil(meas.measureText(ln || " ").width));

  const lineH = Math.max(fontPx, Math.round(fontPx * Math.max(1.0, asset.line_spacing || 1.25)));
  const actualH = Math.ceil(fontPx + (lines.length - 1) * lineH);
  const unit = Math.max(0.45, fontPx / 48);
  const strokeW = asset.stroke_enabled && asset.stroke_width > 0 ? Math.max(1, Math.round(asset.stroke_width * unit)) : 0;
  const glowBlur = glowEnabled && asset.glow_enabled && asset.glow_radius > 0
    ? Math.max(2, Math.min(18, Math.round(asset.glow_radius * 1.4 * unit)))
    : 0;

  const pad = strokeW + glowBlur * 2 + 6;
  const stamp = document.createElement("canvas");
  stamp.width = actualW + pad * 2;
  stamp.height = actualH + pad * 2;
  const ctx = stamp.getContext("2d");
  ctx.font = fontCss;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.lineJoin = "round";
  ctx.miterLimit = 2;
  ctx.globalAlpha = alpha;

  const cx = stamp.width / 2;
  const sy = pad;

  // Pass 1: Dreamy soft outer glow
  if (glowBlur > 0) {
    ctx.save();
    ctx.shadowColor = asset.glow_color || "#FFFFFF";
    ctx.shadowBlur = glowBlur;
    ctx.fillStyle = asset.glow_color || "#FFFFFF";
    for (let i = 0; i < lines.length; i++) {
      ctx.fillText(lines[i], cx, sy + i * lineH);
    }
    ctx.restore();
  }

  // Pass 2: Soft dark drop shadow for legibility on bright highlights
  const shOff = Math.max(1, Math.round(1.6 * unit));
  ctx.save();
  ctx.fillStyle = "rgba(15, 23, 42, 0.55)";
  ctx.strokeStyle = "rgba(15, 23, 42, 0.45)";
  ctx.lineWidth = strokeW * 2;
  for (let i = 0; i < lines.length; i++) {
    const y = sy + i * lineH + shOff;
    if (strokeW > 0) ctx.strokeText(lines[i], cx + shOff, y);
    ctx.fillText(lines[i], cx + shOff, y);
  }
  ctx.restore();

  // Pass 3: Main crisp stroke + fill
  if (strokeW > 0) {
    ctx.strokeStyle = asset.stroke_color || "#1E293B";
    ctx.lineWidth = strokeW * 2;
    for (let i = 0; i < lines.length; i++) {
      ctx.strokeText(lines[i], cx, sy + i * lineH);
    }
  }
  ctx.fillStyle = asset.color || "#FFFFFF";
  for (let i = 0; i < lines.length; i++) {
    ctx.fillText(lines[i], cx, sy + i * lineH);
  }

  return stamp;
}

// ---- Multi-Scale Subject-Aware Auto-Layout ----

function partitionAssets(assets) {
  const enabled = assets.filter((a) => a.enabled);
  if (!enabled.length) return { heroes: [], accents: [], micros: [] };

  let heroes = enabled.filter((a) => a.role === "hero");
  let accents = enabled.filter((a) => a.role === "accent");
  let micros = enabled.filter((a) => a.role === "micro");
  const autos = enabled.filter((a) => a.role === "auto");

  if (autos.length) {
    if (!heroes.length) {
      const autoText = autos.find((a) => a.kind === "text");
      heroes = [autoText || autos[0]];
    }
    accents = accents.concat(autos);
    micros = micros.concat(autos);
  }
  if (!accents.length) accents = [...enabled];
  if (!micros.length) micros = [...accents];
  if (!heroes.length) {
    const txt = enabled.find((a) => a.kind === "text");
    if (txt) heroes = [txt];
  }
  return { heroes, accents, micros };
}

export function generateAestheticLayout(
  canvasW,
  canvasH,
  assets,
  config,
  { baseCanvas = null, existingLocked = [], imageCache = null } = {},
) {
  const cw = Math.max(1, Math.round(canvasW));
  const ch = Math.max(1, Math.round(canvasH));
  const shortEdge = Math.min(cw, ch);
  const seed = ((Number(config.seed) || 202601) ^ Math.imul(cw, 73856093) ^ Math.imul(ch, 19349663)) >>> 0;
  const rng = new Mulberry32(seed);

  const { heroes, accents, micros } = partitionAssets(assets);
  if (!accents.length && !heroes.length && !micros.length) {
    return existingLocked.map((p) => createPlacement(p));
  }

  const saliency = baseCanvas ? computeSaliencyGrid(baseCanvas) : null;
  const avoidStrength = Math.max(0, Math.min(1, (config.subject_avoidance ?? 75) / 100));
  const scaleVar = Math.max(0, Math.min(1, (config.scale_variation ?? 72) / 100));
  const densityF = Math.max(0.1, Math.min(1, (config.density ?? 58) / 100));
  const opFactor = Math.max(0.15, Math.min(1, (config.global_opacity ?? 78) / 100));
  const style = config.style || "artistic_scatter";

  const aspects = new Map();
  for (const a of assets) aspects.set(a.id, estimateAssetAspect(a, imageCache));

  const occupied = []; // { cx, cy, hw, hh, assetId }
  const placements = [];

  existingLocked.forEach((locked, idx) => {
    const lp = createPlacement({ ...locked, z_index: idx });
    placements.push(lp);
    const asp = aspects.get(lp.asset_id) || 1.0;
    const hw = lp.scale * shortEdge * 0.52;
    occupied.push({ cx: lp.x * cw, cy: lp.y * ch, hw, hh: hw * asp, assetId: lp.asset_id });
  });

  const collides = (nx, ny, scale, asp, padMult) => {
    const cx = nx * cw;
    const cy = ny * ch;
    const hw = scale * shortEdge * 0.5 * padMult;
    const hh = Math.max(hw * asp, shortEdge * 0.015);
    for (const o of occupied) {
      if (Math.abs(cx - o.cx) < hw + o.hw && Math.abs(cy - o.cy) < hh + o.hh) return true;
    }
    return false;
  };

  const nearestDist = (nx, ny, sameAssetId = null) => {
    let best = 9.0;
    const px = nx * cw;
    const py = ny * ch;
    for (const o of occupied) {
      if (sameAssetId !== null && o.assetId !== sameAssetId) continue;
      const d = Math.hypot((px - o.cx) / shortEdge, (py - o.cy) / shortEdge);
      if (d < best) best = d;
    }
    return best;
  };

  const register = (asset, nx, ny, scale, rotation, opacity) => {
    const asp = aspects.get(asset.id) || 1.0;
    const hw = scale * shortEdge * 0.5;
    const hh = Math.max(hw * asp, shortEdge * 0.015);
    occupied.push({ cx: nx * cw, cy: ny * ch, hw, hh, assetId: asset.id });
    placements.push(
      createPlacement({
        id: newCreativeId("lyr"),
        asset_id: asset.id,
        x: Number(nx.toFixed(5)),
        y: Number(ny.toFixed(5)),
        scale: Number(Math.max(0.025, Math.min(0.75, scale)).toFixed(5)),
        rotation: Number(rotation.toFixed(2)),
        opacity: Math.max(8, Math.min(100, Math.round(opacity))),
        glow_enabled: Boolean(config.soft_glow && asset.glow_enabled),
        locked: false,
        auto_generated: true,
        z_index: placements.length,
      }),
    );
  };

  // ---- TIER 1: Hero Focal Title / Primary Badge ----
  if (heroes.length && style !== "full_anti_theft") {
    const heroAsset = rng.weightedChoice(heroes);
    const hAsp = aspects.get(heroAsset.id) || 0.35;
    let heroScale = Math.max(0.18, Math.min(0.50, heroAsset.base_scale * rng.uniform(0.95, 1.18 + 0.14 * scaleVar)));
    heroScale = Math.min(heroScale, (cw * 0.72) / shortEdge);

    const heroSlots =
      style === "magazine_editorial"
        ? [[0.50, 0.82], [0.50, 0.14], [0.28, 0.82], [0.72, 0.82]]
        : style === "frame_halo"
          ? [[0.50, 0.86], [0.50, 0.12], [0.78, 0.86], [0.22, 0.86]]
          : [[0.50, 0.79], [0.50, 0.84], [0.36, 0.80], [0.64, 0.80], [0.50, 0.16]];

    let bestSlot = null;
    let bestScore = -1e9;
    for (const [sx, sy] of heroSlots) {
      const jx = Math.max(0.16, Math.min(0.84, sx + rng.uniform(-0.04, 0.04)));
      const jy = Math.max(0.10, Math.min(0.90, sy + rng.uniform(-0.03, 0.03)));
      if (collides(jx, jy, heroScale, hAsp, 1.05)) continue;
      const sal = sampleSaliency(saliency, jx, jy, 0.08);
      const score = -sal * avoidStrength * 1.4 + rng.uniform(-0.08, 0.08);
      if (score > bestScore) {
        bestScore = score;
        bestSlot = [jx, jy];
      }
    }
    if (bestSlot) {
      const maxRot = Math.min(heroAsset.rotation_range, (config.rotation_jitter || 0) * 0.25, 6);
      const rot = maxRot > 0.3 ? rng.uniform(-maxRot, maxRot) : 0;
      const op = Math.min(100, heroAsset.opacity * (0.75 + 0.35 * opFactor));
      register(heroAsset, bestSlot[0], bestSlot[1], heroScale, rot, op);
    }
  }

  // ---- TIER 2: Multi-Scale Organic Accents ----
  let accentCount = Math.round(7 + densityF * 18);
  if (style === "frame_halo") accentCount = Math.round(8 + densityF * 15);
  else if (style === "full_anti_theft") accentCount = Math.round(12 + densityF * 22);
  else if (style === "magazine_editorial") accentCount = Math.round(6 + densityF * 11);

  const mults = [];
  for (let i = 0; i < accentCount; i++) {
    const frac = i / Math.max(1, accentCount - 1);
    let m;
    if (frac < 0.22) m = rng.uniform(1.08, 1.08 + 0.55 * scaleVar);
    else if (frac < 0.62) m = rng.uniform(Math.max(0.55, 0.92 - 0.22 * scaleVar), 1.06 + 0.14 * scaleVar);
    else m = rng.uniform(Math.max(0.32, 0.65 - 0.30 * scaleVar), Math.max(0.52, 0.85 - 0.12 * scaleVar));
    mults.push(m);
  }
  mults.sort((a, b) => b - a);

  const textLimit = Math.max(2, Math.round(accentCount * 0.28));
  let placedTexts = 0;
  const textAssetCounts = new Map();
  const nonTextAccents = accents.filter((a) => a.kind === "image");

  for (const mult of mults) {
    const eligibleTexts = accents.filter((a) => a.kind === "text" && (textAssetCounts.get(a.id) || 0) < 2);
    let pool;
    if (placedTexts >= textLimit && nonTextAccents.length) pool = nonTextAccents;
    else if (nonTextAccents.length) pool = nonTextAccents.concat(eligibleTexts);
    else pool = eligibleTexts.length ? eligibleTexts : accents;
    const asset = rng.weightedChoice(pool);
    const asp = aspects.get(asset.id) || 1.0;
    let scale = Math.max(0.04, Math.min(0.42, asset.base_scale * mult));
    if (asset.kind === "text") scale = Math.min(scale, (cw * 0.44) / shortEdge);

    const halfWN = (scale * shortEdge * 0.5) / cw;
    const halfHN = (scale * shortEdge * asp * 0.5) / ch;
    const mx = Math.min(0.38, asset.kind === "text" ? halfWN + 0.025 : Math.max(0.03, halfWN * 0.45));
    const my = Math.min(0.38, asset.kind === "text" ? halfHN + 0.025 : Math.max(0.03, halfHN * 0.45));
    const padMult = asset.kind === "text" ? 1.18 : 1.10;

    let bestCand = null;
    let bestScore = -1e9;
    for (let k = 0; k < 30; k++) {
      let nx, ny;
      if (style === "frame_halo") {
        const ep = rng.next();
        const band = rng.uniform(0.04, 0.22);
        if (ep < 0.28) { nx = rng.uniform(mx, 1 - mx); ny = Math.max(my, band); }
        else if (ep < 0.56) { nx = rng.uniform(mx, 1 - mx); ny = Math.min(1 - my, 1 - band); }
        else if (ep < 0.78) { nx = Math.max(mx, band); ny = rng.uniform(my, 1 - my); }
        else { nx = Math.min(1 - mx, 1 - band); ny = rng.uniform(my, 1 - my); }
      } else {
        nx = rng.uniform(mx, 1 - mx);
        ny = rng.uniform(my, 1 - my);
      }

      if (collides(nx, ny, scale, asp, padMult)) continue;
      const sal = sampleSaliency(saliency, nx, ny, Math.max(0.04, scale * 0.35));
      const sizeW = 0.65 + 0.85 * Math.min(1.4, mult);
      const distAll = Math.min(0.45, nearestDist(nx, ny));
      const distSame = Math.min(0.60, nearestDist(nx, ny, asset.id));
      const edgeDist = Math.min(nx, 1 - nx, ny, 1 - ny);
      const frameBonus = style === "artistic_scatter" && edgeDist < 0.24 ? 0.14 : 0;

      const score =
        distAll * 1.45 +
        distSame * 0.95 +
        frameBonus -
        sal * avoidStrength * sizeW * 1.85 +
        rng.uniform(-0.06, 0.06);
      if (score > bestScore) {
        bestScore = score;
        bestCand = [nx, ny, sal];
      }
    }
    if (!bestCand) continue;

    const [nx, ny, sal] = bestCand;
    let maxRot = Math.min(asset.rotation_range, config.rotation_jitter || 0);
    if (asset.kind === "text") maxRot = Math.min(maxRot * 0.30, 8);
    const rot = maxRot > 0.3 ? rng.uniform(-maxRot, maxRot) : 0;
    const salFade = 1 - sal * avoidStrength * 0.32;
    const op = asset.opacity * opFactor * rng.uniform(0.76, 1.08) * salFade;
    register(asset, nx, ny, scale, rot, op);
    if (asset.kind === "text") {
      placedTexts++;
      textAssetCounts.set(asset.id, (textAssetCounts.get(asset.id) || 0) + 1);
    }
  }

  // ---- TIER 3: Micro Anti-Theft Rhythm ----
  if ((config.include_micro_grid || style === "full_anti_theft") && micros.length) {
    const cols = Math.max(3, Math.min(7, Math.round(3 + densityF * 3.5)));
    const rows = Math.max(3, Math.min(7, Math.round(3 + densityF * 3.5)));
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (style === "frame_halo") {
          const cx0 = (c + 0.5) / cols;
          const cy0 = (r + 0.5) / rows;
          if (Math.abs(cx0 - 0.5) < 0.24 && Math.abs(cy0 - 0.45) < 0.24) continue;
        }
        if (rng.next() > 0.48 + 0.44 * densityF) continue;
        const asset = rng.weightedChoice(micros);
        const asp = aspects.get(asset.id) || 1.0;
        const nx = Math.max(0.05, Math.min(0.95, (c + 0.5) / cols + rng.uniform(-0.34, 0.34) / cols));
        const ny = Math.max(0.05, Math.min(0.95, (r + 0.5) / rows + rng.uniform(-0.34, 0.34) / rows));
        const microMult = rng.uniform(0.30, Math.max(0.42, 0.62 - 0.12 * scaleVar));
        const scale = Math.max(0.032, Math.min(0.14, asset.base_scale * microMult));
        if (collides(nx, ny, scale, asp, 1.06)) continue;

        const sal = sampleSaliency(saliency, nx, ny, 0.04);
        if (sal > 0.78 && avoidStrength > 0.6 && style !== "full_anti_theft") continue;

        let maxRot = Math.min(asset.rotation_range, config.rotation_jitter || 0);
        if (asset.kind === "text") maxRot = Math.min(maxRot * 0.45, 14);
        const rot = maxRot > 0.3 ? rng.uniform(-maxRot, maxRot) : 0;
        const salFade = 1 - sal * avoidStrength * 0.45;
        const op = Math.max(12, asset.opacity * opFactor * rng.uniform(0.32, 0.58) * salFade);
        register(asset, nx, ny, scale, rot, op);
      }
    }
  }

  placements.sort((a, b) => (a.auto_generated === b.auto_generated ? a.z_index - b.z_index : a.auto_generated ? -1 : 1));
  placements.forEach((p, idx) => { p.z_index = idx; });
  return placements;
}

// ---- Compositor & Full-Res Export ----

export function drawCreativeOverlay(ctx, canvasW, canvasH, placements, assetMap, imageCache, stampCache = null) {
  const shortEdge = Math.min(canvasW, canvasH);
  const ordered = [...placements].sort((a, b) => a.z_index - b.z_index);

  for (const layer of ordered) {
    const asset = assetMap.get(layer.asset_id);
    if (!asset || layer.opacity <= 0) continue;

    const exactW = Math.max(8, layer.scale * shortEdge);
    const qW = stampCache ? Math.max(8, Math.round(exactW / 4) * 4) : Math.round(exactW);
    let stamp = null;

    if (stampCache) {
      const key = `${asset.id}|${qW}|${layer.opacity}|${layer.glow_enabled ? 1 : 0}|${asset.text}|${asset.color}`;
      stamp = stampCache.get(key);
      if (!stamp) {
        stamp = renderAssetStampCanvas(asset, qW, {
          opacity: layer.opacity,
          glowEnabled: layer.glow_enabled,
          imageCache,
        });
        if (stamp) {
          stampCache.set(key, stamp);
          if (stampCache.size > 160) {
            const firstKey = stampCache.keys().next().value;
            stampCache.delete(firstKey);
          }
        }
      }
    } else {
      stamp = renderAssetStampCanvas(asset, qW, {
        opacity: layer.opacity,
        glowEnabled: layer.glow_enabled,
        imageCache,
      });
    }

    if (!stamp) continue;
    const ratio = exactW / qW;
    const drawW = stamp.width * ratio;
    const drawH = stamp.height * ratio;
    const cx = layer.x * canvasW;
    const cy = layer.y * canvasH;

    ctx.save();
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.translate(cx, cy);
    // Match Pillow CCW rotation by negating for Canvas CW rotation
    ctx.rotate((-layer.rotation * Math.PI) / 180);
    ctx.drawImage(stamp, -drawW / 2, -drawH / 2, drawW, drawH);
    ctx.restore();
  }
}

function resolveMimeAndExt(filename, outputFormat) {
  if (outputFormat === "jpeg") return { mime: "image/jpeg", ext: ".jpg" };
  if (outputFormat === "png") return { mime: "image/png", ext: ".png" };
  if (outputFormat === "webp") return { mime: "image/webp", ext: ".webp" };
  const ext = getFileExtension(filename);
  if (ext === ".jpg" || ext === ".jpeg") return { mime: "image/jpeg", ext };
  if (ext === ".webp") return { mime: "image/webp", ext: ".webp" };
  return { mime: "image/png", ext: ".png" };
}

export async function exportCreativeImageBlob(doc, assetMap, imageCache, exportConfig) {
  let source;
  if (typeof createImageBitmap === "function") {
    try {
      source = await createImageBitmap(doc.file, { imageOrientation: "from-image" });
    } catch {
      source = await createImageBitmap(doc.file);
    }
  } else {
    source = await loadHtmlImageFromFile(doc.file);
  }

  const w = source.width;
  const h = source.height;
  const { mime, ext } = resolveMimeAndExt(doc.filename, exportConfig.outputFormat);

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

  drawCreativeOverlay(ctx, w, h, doc.placements, assetMap, imageCache, null);

  const quality = Math.max(0.5, Math.min(1.0, (exportConfig.quality || 94) / 100));
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("图片编码失败"))),
      mime,
      mime === "image/png" ? undefined : quality,
    );
  });
  return { blob, ext };
}
