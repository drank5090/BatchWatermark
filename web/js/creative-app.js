/**
 * Interactive Creative Mode Studio Controller for BatchWatermark Web v2.0.
 * Completely independent from Work Mode: manages its own image queue,
 * Watermark Library (images + text), Subject-Aware Auto-Layout, Pointer-Events
 * interactive drag/resize/rotate canvas, Undo/Redo, Apply-to-All, and Export.
 */

import {
  drawCreativeOverlay,
  exportCreativeImageBlob,
  generateAestheticLayout,
  preloadAllAssetImages,
  renderAssetStampCanvas,
} from "./creative-engine.js";
import { CreativeLibraryStore, fileToCreativeAsset } from "./creative-library.js";
import {
  ROLE_LABELS,
  clonePlacement,
  createPlacement,
  defaultAutoLayoutConfig,
  newCreativeId,
  sanitizeCreativeAsset,
} from "./creative-models.js";
import { SUPPORTED_IMAGE_EXTS, getFileExtension, stripExtension } from "./models.js";
import { loadImagePreview } from "./watermark-engine.js";
import { ZipBuilder } from "./zip.js";

const $ = (id) => document.getElementById(id);

export class CreativeModeApp {
  constructor({ toast, trackEvent } = {}) {
    this._toast = toast || (() => {});
    this._trackEvent = trackEvent || (() => {});

    this.libraryStore = new CreativeLibraryStore();
    this.imageCache = new Map(); // asset.id -> HTMLImageElement
    this.stampCache = new Map(); // cacheKey -> HTMLCanvasElement

    // Independent Creative Mode image docs
    this.docs = new Map(); // doc.id -> doc
    this.docOrder = [];
    this.activeDocId = null;
    this.selectedLayerId = "";

    this.autoConfig = defaultAutoLayoutConfig();
    this._updatingInspector = false;

    // Canvas layout & pointer drag state
    this._imgRect = { x: 0, y: 0, w: 0, h: 0 };
    this._drag = null; // { mode, pointerId, startX, startY, origX, origY, origScale, origRot, startDist, startAngle }
    this._snapV = false;
    this._snapH = false;
    this._initialized = false;

    this._init();
  }

  async _init() {
    await this.libraryStore.init();
    await preloadAllAssetImages(this.libraryStore.listAssets(), this.imageCache);
    this._bindEvents();
    this._renderLibraryList();
    this._syncAutoUIFromConfig();
    this._updateControlsState();
    this._setupResizeObserver();
    this._initialized = true;
    this.renderCanvas();
  }

  // ---- Event Binding ----

  _bindEvents() {
    // Import images for Creative Mode
    const openImgPicker = () => $("creativeFileInput").click();
    $("btnCreativeAddImg").addEventListener("click", openImgPicker);
    $("btnCreativeEmptyAdd").addEventListener("click", openImgPicker);
    $("creativeFileInput").addEventListener("change", (e) => {
      if (e.target.files?.length) this.addImageFiles(Array.from(e.target.files));
      e.target.value = "";
    });

    $("btnCreativeClearImgs").addEventListener("click", () => this.clearAllDocs());

    // Watermark Library actions
    $("btnLibUploadImg").addEventListener("click", () => $("creativeAssetFileInput").click());
    $("creativeAssetFileInput").addEventListener("change", async (e) => {
      if (e.target.files?.length) await this.addImageAssetsFromFiles(Array.from(e.target.files));
      e.target.value = "";
    });

    $("btnLibAddText").addEventListener("click", () => this._openTextModal());
    $("btnCloseTextModal").addEventListener("click", () => this._closeTextModal());
    $("btnCancelTextModal").addEventListener("click", () => this._closeTextModal());
    $("btnConfirmAddText").addEventListener("click", () => this._confirmAddTextAsset());
    $("creativeTextModal").addEventListener("click", (e) => {
      if (e.target === $("creativeTextModal")) this._closeTextModal();
    });

    $("btnLibImport").addEventListener("click", () => $("creativeLibImportInput").click());
    $("creativeLibImportInput").addEventListener("change", async (e) => {
      const f = e.target.files?.[0];
      e.target.value = "";
      if (!f) return;
      try {
        const txt = await f.text();
        const imported = await this.libraryStore.importJsonText(txt, { replace: false });
        await preloadAllAssetImages(this.libraryStore.listAssets(), this.imageCache);
        this.stampCache.clear();
        this._renderLibraryList();
        this.renderCanvas();
        this._toast(`已导入 ${imported.length} 个创作水印素材`);
      } catch (err) {
        window.alert(`导入水印库失败：${err.message || err}`);
      }
    });

    $("btnLibExport").addEventListener("click", () => {
      const json = this.libraryStore.exportJsonText();
      this._downloadBlob(new Blob([json], { type: "application/json;charset=utf-8" }), "creative_watermark_library.json");
      this._toast("已导出创作模式水印库 (.json)，与桌面端 EXE 互通");
    });

    $("btnLibReset").addEventListener("click", async () => {
      await this.libraryStore.resetToBuiltins();
      await preloadAllAssetImages(this.libraryStore.listAssets(), this.imageCache);
      this.stampCache.clear();
      this._renderLibraryList();
      this.renderCanvas();
      this._toast("已恢复默认艺术水印库");
    });

    // Auto-layout buttons
    $("btnCreativeAuto").addEventListener("click", () => this.runAutoLayoutCurrent(false));
    $("btnPanelAutoGen").addEventListener("click", () => this.runAutoLayoutCurrent(false));
    $("btnCreativeShuffle").addEventListener("click", () => this.runAutoLayoutCurrent(true));
    $("btnPanelShuffle").addEventListener("click", () => this.runAutoLayoutCurrent(true));
    $("btnCreativeAutoAll").addEventListener("click", () => this.runAutoLayoutAll());
    $("btnCreativeSyncAll").addEventListener("click", () => this.syncCurrentLayoutToAll());
    $("btnClearLayers").addEventListener("click", () => this.clearUnlockedLayers());

    // Undo / Redo
    $("btnCreativeUndo").addEventListener("click", () => this.undo());
    $("btnCreativeRedo").addEventListener("click", () => this.redo());

    // Auto-layout parameter inputs
    $("selCreativeStyle").addEventListener("change", () => this._readAutoConfigFromUI());
    this._bindSliderPair("rngCDensity", "numCDensity", () => this._readAutoConfigFromUI());
    this._bindSliderPair("rngCScaleVar", "numCScaleVar", () => this._readAutoConfigFromUI());
    this._bindSliderPair("rngCAvoid", "numCAvoid", () => this._readAutoConfigFromUI());
    this._bindSliderPair("rngCOpacity", "numCOpacity", () => this._readAutoConfigFromUI());
    this._bindSliderPair("rngCRotJitter", "numCRotJitter", () => this._readAutoConfigFromUI());
    $("chkCSoftGlow").addEventListener("change", () => this._readAutoConfigFromUI());
    $("chkCMicroGrid").addEventListener("change", () => this._readAutoConfigFromUI());

    // Layer Inspector controls
    this._bindSliderPair("rngLayerScale", "numLayerScale", () => this._applyInspectorToSelected(), { scale: 10 });
    this._bindSliderPair("rngLayerOpacity", "numLayerOpacity", () => this._applyInspectorToSelected());
    this._bindSliderPair("rngLayerRot", "numLayerRot", () => this._applyInspectorToSelected());
    $("chkLayerGlow").addEventListener("change", () => this._applyInspectorToSelected());
    $("chkLayerLock").addEventListener("change", () => this._applyInspectorToSelected());
    $("btnLayerUp").addEventListener("click", () => this.moveSelectedLayer(1));
    $("btnLayerDown").addEventListener("click", () => this.moveSelectedLayer(-1));
    $("btnLayerDup").addEventListener("click", () => this.duplicateLayer(this.selectedLayerId));
    $("btnLayerDel").addEventListener("click", () => this.deleteLayer(this.selectedLayerId));

    // Export
    this._bindSliderPair("rngCQuality", "numCQuality", () => {});
    $("btnCreativeExportTop").addEventListener("click", () => this.exportBatch(false));
    $("btnCreativeExportCur").addEventListener("click", () => this.exportBatch(true));
    $("btnCreativeExportAll").addEventListener("click", () => this.exportBatch(false));

    // Mobile Creative tabs
    document.querySelectorAll("#creativeMobileTabs [data-creative-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.creativeTab;
        $("creativeWorkspace").dataset.mobileCreativeTab = tab;
        document.querySelectorAll("#creativeMobileTabs [data-creative-tab]").forEach((b) => {
          const active = b === btn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", String(active));
        });
      });
    });

    // Canvas Pointer & Drop interactions
    this._bindCanvasInteractions();

    // Global keyboard shortcuts while Creative Mode is visible
    window.addEventListener("keydown", (e) => {
      if ($("creativeModeView").classList.contains("hidden")) return;
      const tag = (e.target?.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!$("creativeTextModal").classList.contains("hidden")) return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) this.redo();
        else this.undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        this.redo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d" && this.selectedLayerId) {
        e.preventDefault();
        this.duplicateLayer(this.selectedLayerId);
      } else if ((e.key === "Delete" || e.key === "Backspace") && this.selectedLayerId) {
        e.preventDefault();
        this.deleteLayer(this.selectedLayerId);
      } else if (this.selectedLayerId && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
        e.preventDefault();
        const layer = this._getSelectedLayer();
        if (!layer) return;
        const step = e.shiftKey ? 0.02 : 0.005;
        this._activeDoc()?.pushUndo();
        if (e.key === "ArrowLeft") layer.x = Math.max(-0.08, +(layer.x - step).toFixed(5));
        if (e.key === "ArrowRight") layer.x = Math.min(1.08, +(layer.x + step).toFixed(5));
        if (e.key === "ArrowUp") layer.y = Math.max(-0.08, +(layer.y - step).toFixed(5));
        if (e.key === "ArrowDown") layer.y = Math.min(1.08, +(layer.y + step).toFixed(5));
        this.renderCanvas();
        this._updateControlsState();
      }
    });
  }

  _bindSliderPair(rangeId, numId, onChange, { scale = 1 } = {}) {
    const rng = $(rangeId);
    const num = $(numId);
    if (!rng || !num) return;
    rng.addEventListener("input", () => {
      num.value = scale === 1 ? rng.value : (Number(rng.value) / scale).toFixed(1);
      onChange();
    });
    num.addEventListener("input", () => {
      const val = Number(num.value);
      if (!Number.isNaN(val)) {
        rng.value = String(Math.round(val * scale));
        onChange();
      }
    });
  }

  _setupResizeObserver() {
    const stage = $("creativeStageBox");
    if (!stage || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => this.renderCanvas());
    ro.observe(stage);
  }

  // ---- Watermark Library Management ----

  async addImageAssetsFromFiles(files) {
    let added = 0;
    for (const f of files) {
      const ext = getFileExtension(f.name);
      if (!SUPPORTED_IMAGE_EXTS.has(ext) && !(f.type || "").startsWith("image/")) continue;
      try {
        const asset = await fileToCreativeAsset(f);
        await this.libraryStore.addAsset(asset);
        added++;
      } catch {
        // skip unsupported
      }
    }
    if (added) {
      await preloadAllAssetImages(this.libraryStore.listAssets(), this.imageCache);
      this._renderLibraryList();
      this._toast(`已添加 ${added} 个图片水印到水印库（已本机保存）`);
    }
    return added;
  }

  _openTextModal() {
    $("creativeTextModal").classList.remove("hidden");
    $("txtAssetContent").focus();
  }

  _closeTextModal() {
    $("creativeTextModal").classList.add("hidden");
  }

  async _confirmAddTextAsset() {
    const raw = $("txtAssetContent").value.trim();
    if (!raw) {
      this._toast("请输入水印文字内容");
      return;
    }
    const firstLine = raw.split(/\r?\n/)[0].trim();
    const name = $("txtAssetName").value.trim() || firstLine.slice(0, 16);
    const role = $("selAssetRole").value || "auto";
    const asset = sanitizeCreativeAsset({
      id: newCreativeId("txt"),
      kind: "text",
      name,
      role,
      enabled: true,
      weight: 1.0,
      text: raw,
      font_name: $("selAssetFont").value || "宋体",
      color: $("clrAssetColor").value || "#FFFFFF",
      stroke_enabled: $("chkAssetStroke").checked,
      stroke_color: "#1E293B",
      stroke_width: 2,
      glow_enabled: $("chkAssetGlow").checked,
      glow_color: "#FFFFFF",
      glow_radius: 6,
      base_scale: Number($("rngAssetScale").value || 22) / 100,
      opacity: Number($("rngAssetOpacity").value || 78),
      rotation_range: role === "micro" ? 12 : 6,
      builtin: false,
    });
    await this.libraryStore.addAsset(asset);
    this._renderLibraryList();
    this._closeTextModal();
    $("txtAssetName").value = "";
    this._toast(`已添加文字水印「${asset.name}」`);
  }

  _renderLibraryList() {
    const host = $("creativeLibList");
    host.innerHTML = "";
    const assets = this.libraryStore.listAssets();
    $("creativeLibCount").textContent = `${assets.length} 项`;

    for (const asset of assets) {
      const card = document.createElement("div");
      card.className = "creative-asset-card";
      card.draggable = true;
      card.dataset.assetId = asset.id;
      card.title = "按住拖拽到右侧画布任意位置，或点击「＋」直接放置";

      // Drag from library onto canvas
      card.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/x-bw-asset-id", asset.id);
        e.dataTransfer.effectAllowed = "copy";
      });

      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.checked = asset.enabled;
      chk.title = "勾选后参与自动美观排版";
      chk.addEventListener("change", async () => {
        asset.enabled = chk.checked;
        await this.libraryStore.updateAsset(asset);
      });

      const thumb = document.createElement("div");
      thumb.className = "asset-thumb";
      const previewStamp = renderAssetStampCanvas(asset, 38, {
        opacity: 96,
        glowEnabled: false,
        imageCache: this.imageCache,
      });
      if (previewStamp) {
        previewStamp.className = "asset-thumb-canvas";
        thumb.appendChild(previewStamp);
      } else {
        thumb.textContent = asset.kind === "image" ? "图" : "字";
      }

      const info = document.createElement("div");
      info.className = "asset-info";

      const title = document.createElement("div");
      title.className = "asset-name";
      title.textContent = asset.name;

      const meta = document.createElement("div");
      meta.className = "asset-meta";
      const badge = document.createElement("span");
      badge.className = asset.kind === "image" ? "kind-badge img" : "kind-badge txt";
      badge.textContent = asset.kind === "image" ? "图" : "字";

      const roleSel = document.createElement("select");
      roleSel.className = "mini-select";
      roleSel.setAttribute("aria-label", `${asset.name} 排版角色`);
      for (const [rk, rl] of Object.entries(ROLE_LABELS)) {
        const opt = document.createElement("option");
        opt.value = rk;
        opt.textContent = rl;
        if (rk === asset.role) opt.selected = true;
        roleSel.appendChild(opt);
      }
      roleSel.addEventListener("change", async () => {
        asset.role = roleSel.value;
        await this.libraryStore.updateAsset(asset);
      });

      meta.append(badge, roleSel);
      info.append(title, meta);

      const actions = document.createElement("div");
      actions.className = "asset-actions";

      const btnDrop = document.createElement("button");
      btnDrop.type = "button";
      btnDrop.className = "card-icon-btn";
      btnDrop.textContent = "＋";
      btnDrop.title = "放置到当前画布";
      btnDrop.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this.addAssetToCenter(asset.id);
      });

      const btnDel = document.createElement("button");
      btnDel.type = "button";
      btnDel.className = "card-icon-btn remove";
      btnDel.textContent = "✕";
      btnDel.title = "删除该素材";
      btnDel.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        await this.libraryStore.deleteAsset(asset.id);
        this.stampCache.clear();
        for (const doc of this.docs.values()) {
          doc.placements = doc.placements.filter((p) => p.asset_id !== asset.id);
        }
        this._renderLibraryList();
        this._renderFilmstrip();
        this.renderCanvas();
        this._refreshInspector();
      });

      actions.append(btnDrop, btnDel);
      card.append(chk, thumb, info, actions);
      host.appendChild(card);
    }
  }

  // ---- Image Queue Management ----

  async addImageFiles(files) {
    let added = 0;
    let firstId = null;
    for (const file of files) {
      const ext = getFileExtension(file.name);
      if (!SUPPORTED_IMAGE_EXTS.has(ext) && !(file.type || "").startsWith("image/")) continue;
      try {
        const { previewCanvas, origW, origH } = await loadImagePreview(file, 1100);
        const doc = {
          id: newCreativeId("cdoc"),
          file,
          filename: file.name,
          origW,
          origH,
          previewCanvas,
          placements: [],
          undoStack: [],
          redoStack: [],
          pushUndo() {
            this.undoStack.push(this.placements.map((p) => clonePlacement(p, false)));
            if (this.undoStack.length > 40) this.undoStack.shift();
            this.redoStack.length = 0;
          },
        };
        this.docs.set(doc.id, doc);
        this.docOrder.push(doc.id);
        if (!firstId) firstId = doc.id;
        added++;
      } catch {
        // skip unreadable
      }
    }

    if (added) {
      if (!this.activeDocId && firstId) this.activeDocId = firstId;
      this._renderFilmstrip();
      this._updateControlsState();
      this.renderCanvas();
      this._trackEvent("creative_images_imported", { count: added });
      this._toast(`创作模式已导入 ${added} 张图片，点击「✨ 智能排版」或拖入左侧水印即可开始`);
    }
    return added;
  }

  selectDoc(docId) {
    if (!this.docs.has(docId)) return;
    this.activeDocId = docId;
    this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  removeDoc(docId) {
    if (!this.docs.has(docId)) return;
    this.docs.delete(docId);
    this.docOrder = this.docOrder.filter((id) => id !== docId);
    if (this.activeDocId === docId) {
      this.activeDocId = this.docOrder[0] || null;
      this.selectedLayerId = "";
    }
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  clearAllDocs() {
    this.docs.clear();
    this.docOrder = [];
    this.activeDocId = null;
    this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  _activeDoc() {
    return this.activeDocId ? this.docs.get(this.activeDocId) || null : null;
  }

  _renderFilmstrip() {
    const strip = $("creativeFilmstrip");
    strip.innerHTML = "";
    for (const id of this.docOrder) {
      const doc = this.docs.get(id);
      if (!doc) continue;
      const item = document.createElement("div");
      item.className = "filmstrip-card" + (id === this.activeDocId ? " selected" : "");
      item.addEventListener("click", () => this.selectDoc(id));

      const top = document.createElement("div");
      top.className = "filmstrip-top";
      const badge = document.createElement("span");
      badge.className = "group-badge";
      badge.textContent = `${doc.placements.length} 层`;
      const btnX = document.createElement("button");
      btnX.type = "button";
      btnX.className = "card-icon-btn remove mini";
      btnX.textContent = "✕";
      btnX.addEventListener("click", (e) => {
        e.stopPropagation();
        this.removeDoc(id);
      });
      top.append(badge, btnX);

      const thumb = document.createElement("canvas");
      thumb.width = 96;
      thumb.height = 46;
      thumb.className = "filmstrip-thumb";
      const tctx = thumb.getContext("2d");
      const fit = Math.min(96 / doc.previewCanvas.width, 46 / doc.previewCanvas.height);
      const dw = doc.previewCanvas.width * fit;
      const dh = doc.previewCanvas.height * fit;
      tctx.drawImage(doc.previewCanvas, (96 - dw) / 2, (46 - dh) / 2, dw, dh);

      const name = document.createElement("div");
      name.className = "filmstrip-name";
      name.textContent = doc.filename;
      name.title = doc.filename;

      item.append(top, thumb, name);
      strip.appendChild(item);
    }
  }

  // ---- Auto-Layout & Manual Placement ----

  _syncAutoUIFromConfig() {
    $("selCreativeStyle").value = this.autoConfig.style;
    $("rngCDensity").value = $("numCDensity").value = String(this.autoConfig.density);
    $("rngCScaleVar").value = $("numCScaleVar").value = String(this.autoConfig.scale_variation);
    $("rngCAvoid").value = $("numCAvoid").value = String(this.autoConfig.subject_avoidance);
    $("rngCOpacity").value = $("numCOpacity").value = String(this.autoConfig.global_opacity);
    $("rngCRotJitter").value = $("numCRotJitter").value = String(this.autoConfig.rotation_jitter);
    $("chkCSoftGlow").checked = this.autoConfig.soft_glow;
    $("chkCMicroGrid").checked = this.autoConfig.include_micro_grid;
  }

  _readAutoConfigFromUI() {
    this.autoConfig.style = $("selCreativeStyle").value || "artistic_scatter";
    this.autoConfig.density = Number($("numCDensity").value) || 58;
    this.autoConfig.scale_variation = Number($("numCScaleVar").value) ?? 72;
    this.autoConfig.subject_avoidance = Number($("numCAvoid").value) ?? 75;
    this.autoConfig.global_opacity = Number($("numCOpacity").value) || 78;
    this.autoConfig.rotation_jitter = Number($("numCRotJitter").value) ?? 18;
    this.autoConfig.soft_glow = $("chkCSoftGlow").checked;
    this.autoConfig.include_micro_grid = $("chkCMicroGrid").checked;
  }

  runAutoLayoutCurrent(newSeed = false) {
    const doc = this._activeDoc();
    if (!doc) return 0;
    this._readAutoConfigFromUI();
    const assets = this.libraryStore.listAssets().filter((a) => a.enabled);
    if (!assets.length) {
      this._toast("请先在左侧水印库勾选或上传至少 1 个水印素材");
      return 0;
    }
    if (newSeed) {
      this.autoConfig.seed = Math.floor(Math.random() * 999999999) + 1;
    }
    doc.pushUndo();
    const locked = doc.placements.filter((p) => p.locked);
    doc.placements = generateAestheticLayout(doc.origW, doc.origH, assets, this.autoConfig, {
      baseCanvas: doc.previewCanvas,
      existingLocked: locked,
      imageCache: this.imageCache,
    });
    this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
    this._trackEvent("creative_auto_layout", { style: this.autoConfig.style, layers: doc.placements.length });
    this._toast(`已智能排版 ${doc.placements.length} 个大小错落水印（点击任意元素可单独拖拽微调）`);
    return doc.placements.length;
  }

  runAutoLayoutAll() {
    if (!this.docOrder.length) return;
    this._readAutoConfigFromUI();
    const assets = this.libraryStore.listAssets().filter((a) => a.enabled);
    if (!assets.length) {
      this._toast("请先勾选至少 1 个水印素材");
      return;
    }
    this.docOrder.forEach((id, idx) => {
      const doc = this.docs.get(id);
      if (!doc) return;
      doc.pushUndo();
      const cfg = { ...this.autoConfig, seed: ((this.autoConfig.seed + idx * 7919) & 0x7fffffff) };
      const locked = doc.placements.filter((p) => p.locked);
      doc.placements = generateAestheticLayout(doc.origW, doc.origH, assets, cfg, {
        baseCanvas: doc.previewCanvas,
        existingLocked: locked,
        imageCache: this.imageCache,
      });
    });
    this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
    this._toast(`已为全部 ${this.docOrder.length} 张图片生成独立智能排版`);
  }

  syncCurrentLayoutToAll() {
    const src = this._activeDoc();
    if (!src || this.docOrder.length < 2) return;
    for (const id of this.docOrder) {
      if (id === src.id) continue;
      const dst = this.docs.get(id);
      if (!dst) continue;
      dst.pushUndo();
      dst.placements = src.placements.map((p) => clonePlacement(p, true));
    }
    this._renderFilmstrip();
    this._toast(`已将当前 ${src.placements.length} 个水印按相对坐标同步套用到全部图片`);
  }

  dropAssetAt(assetId, nx, ny) {
    const doc = this._activeDoc();
    const asset = this.libraryStore.getAsset(assetId);
    if (!doc || !asset) {
      if (!doc) this._toast("请先导入至少 1 张底图后再拖入水印");
      return null;
    }
    doc.pushUndo();
    const maxZ = doc.placements.reduce((m, p) => Math.max(m, p.z_index), -1);
    const layer = createPlacement({
      id: newCreativeId("lyr"),
      asset_id: asset.id,
      x: +nx.toFixed(5),
      y: +ny.toFixed(5),
      scale: asset.base_scale,
      rotation: 0,
      opacity: asset.opacity,
      glow_enabled: asset.glow_enabled,
      locked: false,
      auto_generated: false,
      z_index: maxZ + 1,
    });
    doc.placements.push(layer);
    this.selectedLayerId = layer.id;
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
    return layer;
  }

  addAssetToCenter(assetId) {
    const doc = this._activeDoc();
    if (!doc) {
      this._toast("请先点击左上角「＋ 添加图片」导入底图");
      return null;
    }
    const jitter = ((doc.placements.length % 5) - 2) * 0.03;
    return this.dropAssetAt(assetId, 0.5 + jitter, 0.5 + jitter);
  }

  clearUnlockedLayers() {
    const doc = this._activeDoc();
    if (!doc || !doc.placements.length) return;
    doc.pushUndo();
    doc.placements = doc.placements.filter((p) => p.locked);
    this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  // ---- Inspector & Layer Operations ----

  _getSelectedLayer() {
    const doc = this._activeDoc();
    if (!doc || !this.selectedLayerId) return null;
    return doc.placements.find((p) => p.id === this.selectedLayerId) || null;
  }

  _refreshInspector() {
    const layer = this._getSelectedLayer();
    this._updatingInspector = true;
    try {
      $("creativeInspectorEmpty").classList.toggle("hidden", Boolean(layer));
      $("creativeInspectorBody").classList.toggle("hidden", !layer);
      if (!layer) return;

      const asset = this.libraryStore.getAsset(layer.asset_id);
      $("inspectorLayerName").textContent = `${asset ? asset.name : "水印图层"} · ${layer.auto_generated ? "自动生成" : "手动放置"}`;
      const pct = +(layer.scale * 100).toFixed(1);
      $("rngLayerScale").value = String(Math.round(pct * 10));
      $("numLayerScale").value = pct.toFixed(1);
      $("rngLayerOpacity").value = $("numLayerOpacity").value = String(layer.opacity);
      $("rngLayerRot").value = $("numLayerRot").value = String(Math.round(layer.rotation));
      $("chkLayerGlow").checked = layer.glow_enabled;
      $("chkLayerLock").checked = layer.locked;
    } finally {
      this._updatingInspector = false;
    }
  }

  _applyInspectorToSelected() {
    if (this._updatingInspector) return;
    const layer = this._getSelectedLayer();
    if (!layer) return;
    layer.scale = Math.max(0.025, Math.min(0.85, Number($("numLayerScale").value) / 100 || layer.scale));
    layer.opacity = Math.max(5, Math.min(100, Math.round(Number($("numLayerOpacity").value) || 75)));
    layer.rotation = Math.max(-180, Math.min(180, Number($("numLayerRot").value) || 0));
    layer.glow_enabled = $("chkLayerGlow").checked;
    layer.locked = $("chkLayerLock").checked;
    this.renderCanvas();
  }

  moveSelectedLayer(delta) {
    const doc = this._activeDoc();
    const layer = this._getSelectedLayer();
    if (!doc || !layer) return;
    doc.pushUndo();
    const ordered = [...doc.placements].sort((a, b) => a.z_index - b.z_index);
    const idx = ordered.indexOf(layer);
    const next = Math.max(0, Math.min(ordered.length - 1, idx + delta));
    if (next !== idx) {
      ordered.splice(idx, 1);
      ordered.splice(next, 0, layer);
      ordered.forEach((p, i) => { p.z_index = i; });
      doc.placements = ordered;
      this.renderCanvas();
      this._updateControlsState();
    }
  }

  duplicateLayer(layerId) {
    const doc = this._activeDoc();
    if (!doc || !layerId) return;
    const src = doc.placements.find((p) => p.id === layerId);
    if (!src) return;
    doc.pushUndo();
    const dup = clonePlacement(src, true);
    dup.x = Math.min(0.95, +(dup.x + 0.04).toFixed(5));
    dup.y = Math.min(0.95, +(dup.y + 0.04).toFixed(5));
    dup.auto_generated = false;
    dup.z_index = doc.placements.reduce((m, p) => Math.max(m, p.z_index), 0) + 1;
    doc.placements.push(dup);
    this.selectedLayerId = dup.id;
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  deleteLayer(layerId) {
    const doc = this._activeDoc();
    if (!doc || !layerId) return;
    if (!doc.placements.some((p) => p.id === layerId)) return;
    doc.pushUndo();
    doc.placements = doc.placements.filter((p) => p.id !== layerId);
    if (this.selectedLayerId === layerId) this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  undo() {
    const doc = this._activeDoc();
    if (!doc || !doc.undoStack.length) return;
    doc.redoStack.push(doc.placements.map((p) => clonePlacement(p, false)));
    doc.placements = doc.undoStack.pop();
    this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  redo() {
    const doc = this._activeDoc();
    if (!doc || !doc.redoStack.length) return;
    doc.undoStack.push(doc.placements.map((p) => clonePlacement(p, false)));
    doc.placements = doc.redoStack.pop();
    this.selectedLayerId = "";
    this._renderFilmstrip();
    this._refreshInspector();
    this._updateControlsState();
    this.renderCanvas();
  }

  _updateControlsState() {
    const count = this.docOrder.length;
    const has = count > 0;
    const doc = this._activeDoc();

    $("creativeCountBadge").textContent = `共 ${count} 张`;
    $("creativeEmptyState").classList.toggle("hidden", has);
    $("creativeCanvas").classList.toggle("hidden", !has);

    $("btnCreativeClearImgs").disabled = !has;
    $("btnCreativeAuto").disabled = !has;
    $("btnCreativeShuffle").disabled = !has;
    $("btnCreativeAutoAll").disabled = !has;
    $("btnCreativeSyncAll").disabled = count < 2;
    $("btnCreativeUndo").disabled = !(doc && doc.undoStack.length);
    $("btnCreativeRedo").disabled = !(doc && doc.redoStack.length);
    $("btnCreativeExportTop").disabled = !has;
    $("btnCreativeExportCur").disabled = !has;
    $("btnCreativeExportAll").disabled = !has;
    $("btnCreativeExportAll").textContent = count === 1 ? "⬇ 直接导出图片 (1 张)" : `⬇ 批量导出 ZIP (${count} 张)`;
  }

  // ---- Interactive Canvas Rendering & Hit-Testing ----

  _layerDisplayGeom(layer) {
    const asset = this.libraryStore.assetMap().get(layer.asset_id);
    if (!asset) return null;
    const r = this._imgRect;
    if (r.w <= 0 || r.h <= 0) return null;
    const shortEdge = Math.min(r.w, r.h);
    const exactW = Math.max(8, layer.scale * shortEdge);
    const qW = Math.max(8, Math.round(exactW / 4) * 4);
    const key = `${asset.id}|${qW}|${layer.opacity}|${layer.glow_enabled ? 1 : 0}|${asset.text}|${asset.color}`;
    let stamp = this.stampCache.get(key);
    if (!stamp) {
      stamp = renderAssetStampCanvas(asset, qW, {
        opacity: layer.opacity,
        glowEnabled: layer.glow_enabled,
        imageCache: this.imageCache,
      });
      if (stamp) this.stampCache.set(key, stamp);
    }
    if (!stamp) return null;
    const ratio = exactW / qW;
    return {
      cx: r.x + layer.x * r.w,
      cy: r.y + layer.y * r.h,
      w: stamp.width * ratio,
      h: stamp.height * ratio,
    };
  }

  _toLocal(px, py, cx, cy, rotCCW) {
    const dx = px - cx;
    const dy = py - cy;
    const rad = (rotCCW * Math.PI) / 180;
    const c = Math.cos(rad);
    const s = Math.sin(rad);
    return { x: dx * c - dy * s, y: dx * s + dy * c };
  }

  _fromLocal(lx, ly, cx, cy, rotCCW) {
    const rad = (-rotCCW * Math.PI) / 180;
    const c = Math.cos(rad);
    const s = Math.sin(rad);
    return { x: cx + lx * c - ly * s, y: cy + lx * s + ly * c };
  }

  _hitHandles(px, py, layer) {
    const g = this._layerDisplayGeom(layer);
    if (!g) return "";
    const hw = Math.max(15, g.w / 2);
    const hh = Math.max(15, g.h / 2);
    const rotPt = this._fromLocal(0, -(hh + 24), g.cx, g.cy, layer.rotation);
    if (Math.hypot(px - rotPt.x, py - rotPt.y) <= 13) return "rotate";
    for (const sx of [-1, 1]) {
      for (const sy of [-1, 1]) {
        const corner = this._fromLocal(sx * hw, sy * hh, g.cx, g.cy, layer.rotation);
        if (Math.hypot(px - corner.x, py - corner.y) <= 12) return "resize";
      }
    }
    return "";
  }

  _hitLayer(px, py) {
    const doc = this._activeDoc();
    if (!doc) return null;
    const ordered = [...doc.placements].sort((a, b) => b.z_index - a.z_index);
    for (const layer of ordered) {
      const g = this._layerDisplayGeom(layer);
      if (!g) continue;
      const loc = this._toLocal(px, py, g.cx, g.cy, layer.rotation);
      const hw = Math.max(14, g.w / 2 + 5);
      const hh = Math.max(14, g.h / 2 + 5);
      if (Math.abs(loc.x) <= hw && Math.abs(loc.y) <= hh) return layer;
    }
    return null;
  }

  renderCanvas() {
    const canvas = $("creativeCanvas");
    const box = $("creativeStageBox");
    const doc = this._activeDoc();
    if (!canvas || !box || !doc) return;

    const cssW = Math.max(100, Math.floor(box.clientWidth));
    const cssH = Math.max(100, Math.floor(box.clientHeight));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      canvas.style.width = `${cssW}px`;
      canvas.style.height = `${cssH}px`;
    }

    const ctx = canvas.getContext("2d");
    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.fillStyle = "#11141a";
    ctx.fillRect(0, 0, cssW, cssH);

    const pad = cssW < 520 ? 10 : 20;
    const availW = Math.max(40, cssW - pad * 2);
    const availH = Math.max(40, cssH - pad * 2);
    const fit = Math.min(availW / doc.previewCanvas.width, availH / doc.previewCanvas.height);
    const dw = doc.previewCanvas.width * fit;
    const dh = doc.previewCanvas.height * fit;
    const dx = (cssW - dw) / 2;
    const dy = (cssH - dh) / 2;
    this._imgRect = { x: dx, y: dy, w: dw, h: dh };

    // Checkerboard + base photo + creative watermark layers clipped to photo rect
    ctx.save();
    ctx.beginPath();
    ctx.rect(dx, dy, dw, dh);
    ctx.clip();

    const tile = 12;
    for (let y = Math.floor(dy); y < dy + dh; y += tile) {
      for (let x = Math.floor(dx); x < dx + dw; x += tile) {
        const even = (Math.floor((x - dx) / tile) + Math.floor((y - dy) / tile)) % 2 === 0;
        ctx.fillStyle = even ? "#1f2430" : "#293040";
        ctx.fillRect(x, y, tile, tile);
      }
    }

    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(doc.previewCanvas, dx, dy, dw, dh);

    // Draw all creative watermark layers translated into image rect
    ctx.save();
    ctx.translate(dx, dy);
    drawCreativeOverlay(
      ctx,
      dw,
      dh,
      doc.placements,
      this.libraryStore.assetMap(),
      this.imageCache,
      this.stampCache,
    );
    ctx.restore();

    // Snap center lines while dragging
    if (this._drag && this._drag.mode === "move") {
      ctx.strokeStyle = "rgba(56, 189, 248, 0.78)";
      ctx.lineWidth = 1.2;
      ctx.setLineDash([5, 4]);
      if (this._snapV) {
        ctx.beginPath();
        ctx.moveTo(dx + dw / 2, dy);
        ctx.lineTo(dx + dw / 2, dy + dh);
        ctx.stroke();
      }
      if (this._snapH) {
        ctx.beginPath();
        ctx.moveTo(dx, dy + dh / 2);
        ctx.lineTo(dx + dw, dy + dh / 2);
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }
    ctx.restore();

    // Subtle crisp image frame
    ctx.strokeStyle = "#323846";
    ctx.lineWidth = 1;
    ctx.strokeRect(dx + 0.5, dy + 0.5, dw - 1, dh - 1);

    // Selection gizmo (unclipped so handles near border remain visible & interactive)
    const sel = this._getSelectedLayer();
    if (sel) {
      const g = this._layerDisplayGeom(sel);
      if (g) {
        const hw = Math.max(15, g.w / 2);
        const hh = Math.max(15, g.h / 2);
        const accent = sel.locked ? "#f59e0b" : "#38bdf8";

        ctx.save();
        ctx.translate(g.cx, g.cy);
        ctx.rotate((-sel.rotation * Math.PI) / 180);
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(-hw, -hh, hw * 2, hh * 2);

        // Rotation handle stem + circle
        ctx.beginPath();
        ctx.moveTo(0, -hh);
        ctx.lineTo(0, -(hh + 24));
        ctx.stroke();

        ctx.fillStyle = "#0f172a";
        ctx.beginPath();
        ctx.arc(0, -(hh + 24), 6.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // 4 corner resize circles
        ctx.fillStyle = "#ffffff";
        for (const sx of [-1, 1]) {
          for (const sy of [-1, 1]) {
            ctx.beginPath();
            ctx.arc(sx * hw, sy * hh, 5.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          }
        }
        ctx.restore();
      }
    }

    ctx.restore();
  }

  _bindCanvasInteractions() {
    const canvas = $("creativeCanvas");
    const stage = $("creativeStageBox");

    const getCanvasPos = (e) => {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      const doc = this._activeDoc();
      if (!doc) return;
      const { x, y } = getCanvasPos(e);

      const curSel = this._getSelectedLayer();
      if (curSel) {
        const handle = this._hitHandles(x, y, curSel);
        if (handle) {
          doc.pushUndo();
          this._startPointerDrag(handle, curSel, e, x, y);
          return;
        }
      }

      const hit = this._hitLayer(x, y);
      if (hit) {
        this.selectedLayerId = hit.id;
        this._refreshInspector();
        doc.pushUndo();
        this._startPointerDrag("move", hit, e, x, y);
        this.renderCanvas();
        return;
      }

      if (this.selectedLayerId) {
        this.selectedLayerId = "";
        this._refreshInspector();
        this.renderCanvas();
      }
    });

    canvas.addEventListener("pointermove", (e) => {
      const doc = this._activeDoc();
      if (!doc) return;
      const { x, y } = getCanvasPos(e);

      if (!this._drag) {
        const curSel = this._getSelectedLayer();
        if (curSel) {
          const h = this._hitHandles(x, y, curSel);
          if (h === "rotate") { canvas.style.cursor = "crosshair"; return; }
          if (h === "resize") { canvas.style.cursor = "nwse-resize"; return; }
        }
        canvas.style.cursor = this._hitLayer(x, y) ? "grab" : "default";
        return;
      }

      if (e.pointerId !== this._drag.pointerId) return;
      const layer = this._getSelectedLayer();
      if (!layer) return;
      const r = this._imgRect;
      this._snapV = false;
      this._snapH = false;

      if (this._drag.mode === "move") {
        canvas.style.cursor = "grabbing";
        let nx = Math.max(-0.08, Math.min(1.08, this._drag.origX + (x - this._drag.startX) / Math.max(1, r.w)));
        let ny = Math.max(-0.08, Math.min(1.08, this._drag.origY + (y - this._drag.startY) / Math.max(1, r.h)));
        if (Math.abs(nx - 0.5) < 0.012) { nx = 0.5; this._snapV = true; }
        if (Math.abs(ny - 0.5) < 0.012) { ny = 0.5; this._snapH = true; }
        layer.x = +nx.toFixed(5);
        layer.y = +ny.toFixed(5);
      } else if (this._drag.mode === "resize") {
        const cx = r.x + layer.x * r.w;
        const cy = r.y + layer.y * r.h;
        const dist = Math.max(6, Math.hypot(x - cx, y - cy));
        const ratio = dist / Math.max(8, this._drag.startDist);
        layer.scale = +Math.max(0.025, Math.min(0.85, this._drag.origScale * ratio)).toFixed(5);
      } else if (this._drag.mode === "rotate") {
        const cx = r.x + layer.x * r.w;
        const cy = r.y + layer.y * r.h;
        const curAng = (Math.atan2(y - cy, x - cx) * 180) / Math.PI;
        let rot = this._drag.origRot - (curAng - this._drag.startAngle);
        while (rot > 180) rot -= 360;
        while (rot < -180) rot += 360;
        for (const snap of [-90, -45, 0, 45, 90]) {
          if (Math.abs(rot - snap) < 2.2) { rot = snap; break; }
        }
        layer.rotation = +rot.toFixed(2);
      }

      this._refreshInspector();
      this.renderCanvas();
    });

    const endDrag = (e) => {
      if (!this._drag || e.pointerId !== this._drag.pointerId) return;
      try { canvas.releasePointerCapture(e.pointerId); } catch {}
      this._drag = null;
      this._snapV = false;
      this._snapH = false;
      canvas.style.cursor = "default";
      this._updateControlsState();
      this.renderCanvas();
    };
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);

    // Drop watermark library item OR OS image files onto stage
    stage.addEventListener("dragover", (e) => {
      e.preventDefault();
      stage.classList.add("drag-over");
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    });
    stage.addEventListener("dragleave", () => stage.classList.remove("drag-over"));
    stage.addEventListener("drop", async (e) => {
      e.preventDefault();
      stage.classList.remove("drag-over");
      const assetId = e.dataTransfer?.getData("text/x-bw-asset-id");
      if (assetId && this._activeDoc()) {
        const rect = canvas.getBoundingClientRect();
        const px = e.clientX - rect.left;
        const py = e.clientY - rect.top;
        const r = this._imgRect;
        const nx = Math.max(0.03, Math.min(0.97, (px - r.x) / Math.max(1, r.w)));
        const ny = Math.max(0.03, Math.min(0.97, (py - r.y) / Math.max(1, r.h)));
        this.dropAssetAt(assetId, nx, ny);
        return;
      }
      const files = Array.from(e.dataTransfer?.files || []);
      if (files.length) await this.addImageFiles(files);
    });
  }

  _startPointerDrag(mode, layer, e, x, y) {
    const r = this._imgRect;
    const cx = r.x + layer.x * r.w;
    const cy = r.y + layer.y * r.h;
    this._drag = {
      mode,
      pointerId: e.pointerId,
      startX: x,
      startY: y,
      origX: layer.x,
      origY: layer.y,
      origScale: layer.scale,
      origRot: layer.rotation,
      startDist: Math.max(8, Math.hypot(x - cx, y - cy)),
      startAngle: (Math.atan2(y - cy, x - cx) * 180) / Math.PI,
    };
    try { $("creativeCanvas").setPointerCapture(e.pointerId); } catch {}
  }

  // ---- High-Resolution Export ----

  async exportBatch(onlyCurrent = false) {
    const targets = onlyCurrent
      ? [this._activeDoc()].filter(Boolean)
      : this.docOrder.map((id) => this.docs.get(id)).filter(Boolean);
    if (!targets.length) return;

    const exportConfig = {
      outputFormat: $("selCOutputFormat").value || "keep",
      quality: Number($("numCQuality").value) || 94,
      suffix: $("txtCSuffix").value || "_creative",
    };

    const assetMap = this.libraryStore.assetMap();
    await preloadAllAssetImages(this.libraryStore.listAssets(), this.imageCache);

    if (targets.length === 1) {
      const doc = targets[0];
      try {
        const { blob, ext } = await exportCreativeImageBlob(doc, assetMap, this.imageCache, exportConfig);
        const outName = `${stripExtension(doc.filename)}${exportConfig.suffix}${ext}`;
        this._downloadBlob(blob, outName);
        this._trackEvent("creative_exported", { count: 1, mode: "single" });
        this._toast(`已导出高清创作图片：${outName}`);
      } catch (err) {
        window.alert(`导出失败：${err.message || err}`);
      }
      return;
    }

    const zip = new ZipBuilder();
    const usedNames = new Set();
    let ok = 0;
    for (const doc of targets) {
      try {
        const { blob, ext } = await exportCreativeImageBlob(doc, assetMap, this.imageCache, exportConfig);
        let base = `${stripExtension(doc.filename)}${exportConfig.suffix}`;
        let name = `${base}${ext}`;
        let n = 1;
        while (usedNames.has(name.toLowerCase())) {
          name = `${base}_${n++}${ext}`;
        }
        usedNames.add(name.toLowerCase());
        zip.addFile(name, new Uint8Array(await blob.arrayBuffer()));
        ok++;
      } catch {
        // skip failed item
      }
    }
    if (ok > 0) {
      const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
      this._downloadBlob(zip.buildBlob(), `BatchWatermark_Creative_${ts}.zip`);
      this._trackEvent("creative_exported", { count: ok, mode: "zip" });
      this._toast(`已批量打包导出 ${ok} 张高清创作图片`);
    }
  }

  _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
}
