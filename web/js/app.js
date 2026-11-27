/**
 * Main interactive controller for BatchWatermark Web Edition.
 */

import { CreativeModeApp } from "./creative-app.js";
import {
  SUPPORTED_IMAGE_EXTS,
  SUPPORTED_VIDEO_EXTS,
  cloneConfig,
  defaultWatermarkConfig,
  formatDuration,
  getBuiltinPresets,
  getFileExtension,
  stripExtension,
} from "./models.js";
import { PresetStore } from "./presets.js";
import { exportWatermarkedVideo, probeVideoAndExtractFrame } from "./video-engine.js";
import {
  PREVIEW_MAX_EDGE,
  drawWatermarkOverlay,
  exportImageBlob,
  loadHtmlImageFromFile,
  loadImagePreview,
} from "./watermark-engine.js";
import { ZipBuilder } from "./zip.js";

const $ = (id) => document.getElementById(id);

class BatchWatermarkApp {
  constructor() {
    this.presetStore = new PresetStore();
    this.builtinPresets = getBuiltinPresets();

    // Media store
    this.items = new Map(); // id -> item
    this.itemOrder = [];    // id[]
    this.dedupKeys = new Set();
    this.cards = new Map(); // id -> { el, canvas, nameEl, metaEl, badgeEl }
    this.selectedId = null;

    // Orientation isolation & config state
    this.orientationIsolated = false;
    this.viewScope = "both"; // "both" | "landscape" | "portrait"
    this.independentParams = false;
    this.editingOrientation = "landscape";
    this.landscapeConfig = defaultWatermarkConfig();
    this.portraitConfig = defaultWatermarkConfig();
    this.activeConfig = cloneConfig(this.landscapeConfig);

    // Logo & custom font state
    this.logoImage = null;
    this.customFontFamily = "";
    this.customFontName = "";

    // Render debounce & export cancel state
    this._renderTimer = null;
    this._exportCancelled = false;
    this._updatingUI = false;

    // Lightbox state
    this._lbIndex = 0;
    this._lbVideo = null;
    this._lbVideoUrl = "";
    this._lbPlaying = false;
    this._lbRafId = null;

    this._initUI();
    this._bindEvents();
    this._rebuildPresetSelect();
    this._applyConfigToUI(this.activeConfig);
    this._updateCountsAndButtons();
  }

  _initUI() {
    // Check File System Access API availability
    if (typeof window.showDirectoryPicker !== "function") {
      const dirBtn = $("btnExportDir");
      dirBtn.title = "当前浏览器不支持直接写入文件夹（推荐使用 Chrome / Edge，或使用上方 ZIP 导出）";
    }
  }

  // ---- Event Binding ----

  _bindEvents() {
    // Media import triggers
    const openFiles = () => $("fileInputMedia").click();
    const openFolder = () => $("fileInputFolder").click();
    $("btnAddFiles").addEventListener("click", openFiles);
    $("btnEmptyAddFiles").addEventListener("click", openFiles);
    $("btnMobileAdd")?.addEventListener("click", openFiles);
    $("btnAddFolder").addEventListener("click", openFolder);
    $("btnEmptyAddFolder").addEventListener("click", openFolder);

    // Mobile parameter category tabs
    document.querySelectorAll("#mobileParamTabs [data-mobile-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.mobileTab;
        $("controlPanel").dataset.activeMobileTab = tab;
        document.querySelectorAll("#mobileParamTabs [data-mobile-tab]").forEach((b) => {
          const active = b === btn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", String(active));
        });
      });
    });

    // Mobile pinned preview expand / collapse toggle
    $("btnMobileExpandGallery")?.addEventListener("click", () => {
      const pane = $("galleryPane");
      const expanded = pane.classList.toggle("mobile-expanded");
      $("btnMobileExpandGallery").textContent = expanded ? "收起画廊" : "展开画廊";
    });

    $("fileInputMedia").addEventListener("change", (e) => {
      if (e.target.files?.length) this.addFiles(Array.from(e.target.files));
      e.target.value = "";
    });
    $("fileInputFolder").addEventListener("change", (e) => {
      if (e.target.files?.length) this.addFiles(Array.from(e.target.files));
      e.target.value = "";
    });

    // Drag & drop files and folders onto gallery pane
    const galleryPane = $("galleryPane");
    let dragCounter = 0;
    galleryPane.addEventListener("dragenter", (e) => {
      e.preventDefault();
      dragCounter++;
      galleryPane.classList.add("drag-over");
    });
    galleryPane.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    });
    galleryPane.addEventListener("dragleave", () => {
      dragCounter = Math.max(0, dragCounter - 1);
      if (dragCounter === 0) galleryPane.classList.remove("drag-over");
    });
    galleryPane.addEventListener("drop", async (e) => {
      e.preventDefault();
      dragCounter = 0;
      galleryPane.classList.remove("drag-over");
      const files = await this._extractDroppedFiles(e.dataTransfer);
      if (files.length) this.addFiles(files);
    });

    // Clear all & card size
    $("btnClearAll").addEventListener("click", () => this.clearAll());
    $("cardSizeSlider").addEventListener("input", (e) => {
      const px = `${e.target.value}px`;
      $("primaryGrid").style.setProperty("--card-w", px);
      $("portraitGrid").style.setProperty("--card-w", px);
    });

    // Orientation isolation toggle
    $("btnIsolateToggle").addEventListener("click", () => {
      this.setOrientationIsolated(!this.orientationIsolated);
    });

    // Isolation view scope filter buttons
    document.querySelectorAll("#galleryFilterBar [data-scope]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.viewScope = btn.dataset.scope;
        document.querySelectorAll("#galleryFilterBar [data-scope]").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
        this._reflowGallery();
      });
    });

    // Independent landscape/portrait parameter mode
    $("chkIndependentParams").addEventListener("change", (e) => {
      this.independentParams = e.target.checked;
      $("orientSwitchHost").classList.toggle("hidden", !this.independentParams);
      if (this.independentParams) {
        this.landscapeConfig = cloneConfig(this.activeConfig);
        this.portraitConfig = cloneConfig(this.activeConfig);
        this.editingOrientation = "landscape";
        $("btnEditLandscape").classList.add("active");
        $("btnEditPortrait").classList.remove("active");
      } else {
        const cur = this._readConfigFromUI();
        this.landscapeConfig = cloneConfig(cur);
        this.portraitConfig = cloneConfig(cur);
      }
      this._scheduleRenderAll();
    });

    $("btnEditLandscape").addEventListener("click", () => this._switchEditingOrientation("landscape"));
    $("btnEditPortrait").addEventListener("click", () => this._switchEditingOrientation("portrait"));
    $("btnSyncOtherOrient").addEventListener("click", () => {
      const cur = this._readConfigFromUI();
      this.landscapeConfig = cloneConfig(cur);
      this.portraitConfig = cloneConfig(cur);
      this._scheduleRenderAll();
      this._toast("已将当前参数同步复制到另一方向");
    });

    // Presets
    $("presetSelect").addEventListener("change", () => this._onPresetSelected());
    $("btnResetParams").addEventListener("click", () => {
      $("presetSelect").value = "";
      this._updateDeletePresetState();
      this._applyConfigToUI(defaultWatermarkConfig());
      this._onControlChanged();
      this._toast("已重置为默认水印参数");
    });
    $("btnSavePreset").addEventListener("click", () => this._onSavePreset());
    $("btnDeletePreset").addEventListener("click", () => this._onDeletePreset());
    $("btnImportPreset").addEventListener("click", () => $("fileInputPreset").click());
    $("fileInputPreset").addEventListener("change", (e) => this._onImportPresetFile(e));

    // Export preset dropdown
    const expDrop = $("exportPresetDropdown");
    $("btnExportPresetMenu").addEventListener("click", (e) => {
      e.stopPropagation();
      expDrop.classList.toggle("hidden");
    });
    document.addEventListener("click", () => expDrop.classList.add("hidden"));
    $("btnExportCurPreset").addEventListener("click", () => this._onExportCurrentPreset());
    $("btnExportAllPresets").addEventListener("click", () => this._onExportAllPresets());

    // Type toggle (text / logo)
    $("btnTypeText").addEventListener("click", () => this._setWatermarkType("text"));
    $("btnTypeImage").addEventListener("click", () => this._setWatermarkType("image"));

    // Text controls
    $("txtWatermark").addEventListener("input", () => this._onControlChanged());
    $("fontSelect").addEventListener("change", () => {
      this.customFontFamily = "";
      this.customFontName = "";
      $("customFontInfo").classList.add("hidden");
      this._onControlChanged();
    });
    $("btnLoadCustomFont").addEventListener("click", () => $("fileInputFont").click());
    $("fileInputFont").addEventListener("change", (e) => this._onCustomFontFile(e));

    this._bindSliderNumber("rngFontSize", "numFontSize", 1);
    this._bindSliderNumber("rngLineSpacing", "numLineSpacing", 10);
    this._bindSliderNumber("rngStrokeWidth", "numStrokeWidth", 1);
    this._bindSliderNumber("rngShadowOffset", "numShadowOffset", 1);
    this._bindSliderNumber("rngLogoScale", "numLogoScale", 1);
    this._bindSliderNumber("rngOpacity", "numOpacity", 1);
    this._bindSliderNumber("rngRotation", "numRotation", 1);
    this._bindSliderNumber("rngTileX", "numTileX", 1);
    this._bindSliderNumber("rngTileY", "numTileY", 1);
    this._bindSliderNumber("rngMarginX", "numMarginX", 10);
    this._bindSliderNumber("rngMarginY", "numMarginY", 10);
    this._bindSliderNumber("rngOffsetX", "numOffsetX", 10);
    this._bindSliderNumber("rngOffsetY", "numOffsetY", 10);
    this._bindSliderNumber("rngQuality", "numQuality", 1, false);

    // Sync the two proportional checkboxes
    const syncProp = (checked) => {
      $("chkProportionalText").checked = checked;
      $("chkProportionalLogo").checked = checked;
      this._onControlChanged();
    };
    $("chkProportionalText").addEventListener("change", (e) => syncProp(e.target.checked));
    $("chkProportionalLogo").addEventListener("change", (e) => syncProp(e.target.checked));

    // Colors & swatches
    this._bindColorInput("clrText", "clrTextHex");
    this._bindColorInput("clrStroke", "clrStrokeHex");
    this._bindColorInput("clrShadow", "clrShadowHex");
    document.querySelectorAll("#textSwatches .swatch").forEach((sw) => {
      sw.addEventListener("click", () => {
        const hex = sw.dataset.color.toUpperCase();
        $("clrText").value = hex.toLowerCase();
        $("clrTextHex").textContent = hex;
        this._onControlChanged();
      });
    });

    $("chkStroke").addEventListener("change", () => {
      this._syncEffectEnabled();
      this._onControlChanged();
    });
    $("chkShadow").addEventListener("change", () => {
      this._syncEffectEnabled();
      this._onControlChanged();
    });

    // Logo upload
    $("btnPickLogo").addEventListener("click", () => $("fileInputLogo").click());
    $("fileInputLogo").addEventListener("change", (e) => this._onLogoFile(e));

    // Quick angle pills
    document.querySelectorAll(".quick-angles [data-angle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const deg = Number(btn.dataset.angle);
        $("rngRotation").value = deg;
        $("numRotation").value = deg;
        this._onControlChanged();
      });
    });

    // Layout mode toggle
    $("btnModeTiled").addEventListener("click", () => this._setLayoutMode("tiled"));
    $("btnModeSingle").addEventListener("click", () => this._setLayoutMode("single"));
    $("chkTileStagger").addEventListener("change", () => this._onControlChanged());

    // 3x3 Anchor Grid
    document.querySelectorAll("#anchorGrid .anchor-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#anchorGrid .anchor-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        this._onControlChanged();
      });
    });

    // Batch export buttons
    $("btnTopExport").addEventListener("click", () => this.startExport("zip"));
    $("btnExportZip").addEventListener("click", () => this.startExport("zip"));
    $("btnExportDir").addEventListener("click", () => this.startExport("directory"));
    $("btnCancelExport").addEventListener("click", () => {
      this._exportCancelled = true;
      $("btnCancelExport").disabled = true;
      $("btnCancelExport").textContent = "正在停止...";
    });

    // Lightbox events
    $("btnLbClose").addEventListener("click", () => this._closeLightbox());
    $("btnLbPrev").addEventListener("click", () => this._stepLightbox(-1));
    $("btnLbNext").addEventListener("click", () => this._stepLightbox(1));
    $("lightboxModal").addEventListener("click", (e) => {
      if (e.target === $("lightboxModal")) this._closeLightbox();
    });
    $("btnLbPlay").addEventListener("click", () => this._toggleLightboxVideoPlay());
    $("rngLbTime").addEventListener("input", () => this._onLightboxScrub());
    document.querySelectorAll("#lightboxVideoBar [data-jump]").forEach((btn) => {
      btn.addEventListener("click", () => this._jumpLightboxVideo(Number(btn.dataset.jump)));
    });

    document.addEventListener("keydown", (e) => {
      if ($("lightboxModal").classList.contains("hidden")) return;
      if (e.key === "Escape") this._closeLightbox();
      else if (e.key === "ArrowLeft") this._stepLightbox(-1);
      else if (e.key === "ArrowRight") this._stepLightbox(1);
    });
  }

  _bindSliderNumber(rangeId, numId, scale = 1, triggersRender = true) {
    const rng = $(rangeId);
    const num = $(numId);
    rng.addEventListener("input", () => {
      const val = scale === 1 ? Number(rng.value) : Number((Number(rng.value) / scale).toFixed(1));
      num.value = val;
      if (triggersRender) this._onControlChanged();
    });
    num.addEventListener("input", () => {
      const val = Number(num.value);
      if (!Number.isNaN(val)) {
        rng.value = Math.round(val * scale);
        if (triggersRender) this._onControlChanged();
      }
    });
  }

  _bindColorInput(inputId, hexId) {
    const inp = $(inputId);
    const lbl = $(hexId);
    inp.addEventListener("input", () => {
      lbl.textContent = inp.value.toUpperCase();
      this._onControlChanged();
    });
  }

  // ---- Media Import & Recursive Folder Drop ----

  async _extractDroppedFiles(dataTransfer) {
    if (!dataTransfer) return [];
    const items = dataTransfer.items ? Array.from(dataTransfer.items) : [];
    const entries = items
      .map((it) => (typeof it.webkitGetAsEntry === "function" ? it.webkitGetAsEntry() : null))
      .filter(Boolean);

    if (entries.length === 0) {
      return Array.from(dataTransfer.files || []);
    }

    const collected = [];
    const walkEntry = async (entry) => {
      if (entry.isFile) {
        const file = await new Promise((res) => entry.file(res, () => res(null)));
        if (file) collected.push(file);
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        const readBatch = () =>
          new Promise((res) => reader.readEntries(res, () => res([])));
        let batch = await readBatch();
        while (batch.length > 0) {
          for (const child of batch) await walkEntry(child);
          batch = await readBatch();
        }
      }
    };
    for (const entry of entries) await walkEntry(entry);
    return collected;
  }

  _classifyMediaFile(file) {
    const ext = getFileExtension(file.name);
    if (SUPPORTED_IMAGE_EXTS.has(ext) || (file.type && file.type.startsWith("image/"))) {
      return "image";
    }
    if (SUPPORTED_VIDEO_EXTS.has(ext) || (file.type && file.type.startsWith("video/"))) {
      return "video";
    }
    return null;
  }

  async addFiles(files) {
    const newItems = [];
    for (const file of files) {
      const mediaType = this._classifyMediaFile(file);
      if (!mediaType) continue;
      const key = `${file.webkitRelativePath || file.name}::${file.size}::${file.lastModified}`;
      if (this.dedupKeys.has(key)) continue;
      this.dedupKeys.add(key);

      const id = `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
      const item = {
        id,
        dedupKey: key,
        file,
        filename: file.name,
        mediaType,
        origW: 0,
        origH: 0,
        duration: 0,
        previewCanvas: null,
        error: "",
      };
      this.items.set(id, item);
      this.itemOrder.push(id);
      this._createCardElement(item);
      newItems.push(item);
    }

    if (newItems.length === 0) {
      this._setStatus("未检测到新的受支持图片或视频（已自动跳过不支持格式与重复项）");
      return;
    }

    $("emptyState").classList.add("hidden");
    $("galleryScroll").classList.remove("hidden");
    $("mobileGalleryBar")?.classList.remove("hidden");
    this._reflowGallery();
    this._updateCountsAndButtons();
    this._trackEvent("media_imported", {
      count: newItems.length,
      video_count: newItems.filter((x) => x.mediaType === "video").length,
    });
    this._setStatus(`正在本地解析 ${newItems.length} 项媒体并生成实时水印预览...`);

    // Decode previews with controlled concurrency so large batches stay responsive
    const concurrency = 4;
    let cursor = 0;
    const worker = async () => {
      while (cursor < newItems.length) {
        const item = newItems[cursor++];
        if (!this.items.has(item.id)) continue;
        try {
          if (item.mediaType === "video") {
            const { previewCanvas, origW, origH, duration } = await probeVideoAndExtractFrame(
              item.file,
              PREVIEW_MAX_EDGE,
            );
            item.previewCanvas = previewCanvas;
            item.origW = origW;
            item.origH = origH;
            item.duration = duration;
          } else {
            const { previewCanvas, origW, origH } = await loadImagePreview(item.file, PREVIEW_MAX_EDGE);
            item.previewCanvas = previewCanvas;
            item.origW = origW;
            item.origH = origH;
          }
          this._updateCardMetadata(item);
          this._renderSingleCard(item);
        } catch (err) {
          item.error = err?.message || "读取失败";
          this._updateCardMetadata(item);
        }
      }
    };

    await Promise.all(Array.from({ length: Math.min(concurrency, newItems.length) }, worker));
    this._reflowGallery();
    this._updateCountsAndButtons();
    this._setStatus(`实时预览已同步更新 · 共 ${this.itemOrder.length} 项媒体`);
  }

  _orientationOf(item) {
    return item.origH > item.origW && item.origW > 0 ? "portrait" : "landscape";
  }

  _createCardElement(item) {
    const el = document.createElement("div");
    el.className = "preview-card";
    el.dataset.id = item.id;

    const stage = document.createElement("div");
    stage.className = "card-stage";

    const canvas = document.createElement("canvas");
    stage.appendChild(canvas);

    const badgeEl = document.createElement("span");
    badgeEl.className = "video-badge" + (item.mediaType === "video" ? "" : " hidden");
    badgeEl.textContent = "▶ 视频";
    stage.appendChild(badgeEl);

    const actions = document.createElement("div");
    actions.className = "card-actions";

    const btnZoom = document.createElement("button");
    btnZoom.type = "button";
    btnZoom.className = "card-icon-btn";
    btnZoom.title = "高清大图预览（视频支持进度帧与实时播放）";
    btnZoom.textContent = "🔍";
    btnZoom.addEventListener("click", (e) => {
      e.stopPropagation();
      this._openLightbox(item.id);
    });

    const btnRemove = document.createElement("button");
    btnRemove.type = "button";
    btnRemove.className = "card-icon-btn remove";
    btnRemove.title = "从列表中移除";
    btnRemove.textContent = "✕";
    btnRemove.addEventListener("click", (e) => {
      e.stopPropagation();
      this.removeItem(item.id);
    });

    actions.append(btnZoom, btnRemove);
    stage.appendChild(actions);

    const footer = document.createElement("div");
    footer.className = "card-footer";
    const nameEl = document.createElement("span");
    nameEl.className = "card-name";
    nameEl.textContent = item.filename;
    nameEl.title = item.filename;

    const metaEl = document.createElement("span");
    metaEl.className = "card-meta";
    metaEl.textContent = "加载中...";

    footer.append(nameEl, metaEl);
    el.append(stage, footer);

    el.addEventListener("click", () => this._selectCard(item.id));
    el.addEventListener("dblclick", () => this._openLightbox(item.id));

    this.cards.set(item.id, { el, canvas, nameEl, metaEl, badgeEl });
  }

  _updateCardMetadata(item) {
    const rec = this.cards.get(item.id);
    if (!rec) return;
    if (item.error) {
      rec.metaEl.textContent = "读取失败";
      rec.nameEl.title = `${item.filename}\n${item.error}`;
      return;
    }
    const orientTxt = this._orientationOf(item) === "portrait" ? "竖版" : "横版";
    rec.metaEl.textContent = `${item.origW} × ${item.origH}`;
    if (item.mediaType === "video") {
      rec.badgeEl.textContent = `▶ ${formatDuration(item.duration)}`;
      rec.badgeEl.classList.remove("hidden");
      rec.nameEl.title = `${item.filename}\n视频 · ${formatDuration(item.duration)} · ${orientTxt} · ${item.origW}×${item.origH}`;
    } else {
      rec.nameEl.title = `${item.filename}\n图片 · ${orientTxt} · ${item.origW}×${item.origH}`;
    }
  }

  _selectCard(id) {
    if (this.selectedId && this.cards.has(this.selectedId)) {
      this.cards.get(this.selectedId).el.classList.remove("selected");
    }
    this.selectedId = id;
    if (this.cards.has(id)) {
      this.cards.get(id).el.classList.add("selected");
    }
  }

  removeItem(id) {
    const item = this.items.get(id);
    if (!item) return;
    this.items.delete(id);
    this.dedupKeys.delete(item.dedupKey);
    this.itemOrder = this.itemOrder.filter((x) => x !== id);
    const rec = this.cards.get(id);
    if (rec) {
      rec.el.remove();
      this.cards.delete(id);
    }
    if (this.selectedId === id) this.selectedId = null;

    if (this.itemOrder.length === 0) {
      $("emptyState").classList.remove("hidden");
      $("galleryScroll").classList.add("hidden");
      $("galleryFilterBar").classList.add("hidden");
      $("mobileGalleryBar")?.classList.add("hidden");
      $("galleryPane").classList.remove("mobile-expanded");
      if ($("btnMobileExpandGallery")) $("btnMobileExpandGallery").textContent = "展开画廊";
    } else {
      this._reflowGallery();
    }
    this._updateCountsAndButtons();
    this._setStatus(`已移除 ${item.filename} · 剩余 ${this.itemOrder.length} 项`);
  }

  clearAll() {
    this.items.clear();
    this.itemOrder = [];
    this.dedupKeys.clear();
    for (const rec of this.cards.values()) rec.el.remove();
    this.cards.clear();
    this.selectedId = null;
    $("emptyState").classList.remove("hidden");
    $("galleryScroll").classList.add("hidden");
    $("galleryFilterBar").classList.add("hidden");
    $("mobileGalleryBar")?.classList.add("hidden");
    $("galleryPane").classList.remove("mobile-expanded");
    if ($("btnMobileExpandGallery")) $("btnMobileExpandGallery").textContent = "展开画廊";
    this._updateCountsAndButtons();
    this._setStatus("已清空媒体列表");
  }

  // ---- Orientation Isolation & Reflow ----

  setOrientationIsolated(enabled) {
    this.orientationIsolated = enabled;
    const btn = $("btnIsolateToggle");
    btn.classList.toggle("active", enabled);
    btn.setAttribute("aria-pressed", String(enabled));

    $("orientationCard").classList.toggle("hidden", !enabled);
    $("exportIsolationHint").classList.toggle("hidden", !enabled);

    if (!enabled && this.independentParams) {
      this.independentParams = false;
      $("chkIndependentParams").checked = false;
      $("orientSwitchHost").classList.add("hidden");
      this.landscapeConfig = cloneConfig(this.activeConfig);
      this.portraitConfig = cloneConfig(this.activeConfig);
      this._scheduleRenderAll();
    }

    this._reflowGallery();
    this._updateCountsAndButtons();
    this._trackEvent("orientation_isolation_toggled", { enabled });
    this._setStatus(
      enabled
        ? "已开启横竖隔离：横版与竖版分开展示，导出时将自动分为「横版/」与「竖版/」子文件夹"
        : "已关闭横竖隔离：全部媒体统一展示与导出",
    );
  }

  _switchEditingOrientation(orient) {
    if (orient === this.editingOrientation) return;
    const cur = this._readConfigFromUI();
    if (this.editingOrientation === "landscape") this.landscapeConfig = cur;
    else this.portraitConfig = cur;

    this.editingOrientation = orient;
    $("btnEditLandscape").classList.toggle("active", orient === "landscape");
    $("btnEditPortrait").classList.toggle("active", orient === "portrait");
    const target = orient === "landscape" ? this.landscapeConfig : this.portraitConfig;
    this._applyConfigToUI(target);
  }

  getConfigForOrientation(orient) {
    if (this.orientationIsolated && this.independentParams) {
      return orient === "portrait" ? this.portraitConfig : this.landscapeConfig;
    }
    return this.activeConfig;
  }

  _reflowGallery() {
    const primaryGrid = $("primaryGrid");
    const portraitGrid = $("portraitGrid");
    const hasItems = this.itemOrder.length > 0;

    $("galleryFilterBar").classList.toggle("hidden", !this.orientationIsolated || !hasItems);
    if (!hasItems) return;

    if (!this.orientationIsolated) {
      $("landHeader").classList.add("hidden");
      $("landEmptyHint").classList.add("hidden");
      $("primarySection").classList.remove("hidden");
      $("portraitSection").classList.add("hidden");

      const frag = document.createDocumentFragment();
      for (const id of this.itemOrder) {
        const rec = this.cards.get(id);
        if (rec) frag.appendChild(rec.el);
      }
      primaryGrid.appendChild(frag);
      return;
    }

    const landIds = [];
    const portIds = [];
    for (const id of this.itemOrder) {
      const item = this.items.get(id);
      if (!item) continue;
      if (this._orientationOf(item) === "portrait") portIds.push(id);
      else landIds.push(id);
    }

    $("landCountBadge").textContent = `${landIds.length} 项`;
    $("portCountBadge").textContent = `${portIds.length} 项`;
    $("btnScopeLand").textContent = `仅看横版 (${landIds.length})`;
    $("btnScopePort").textContent = `仅看竖版 (${portIds.length})`;

    const showLand = this.viewScope === "both" || this.viewScope === "landscape";
    const showPort = this.viewScope === "both" || this.viewScope === "portrait";

    $("primarySection").classList.toggle("hidden", !showLand);
    $("landHeader").classList.toggle("hidden", !showLand);
    $("landEmptyHint").classList.toggle("hidden", !showLand || landIds.length > 0);

    $("portraitSection").classList.toggle("hidden", !showPort);
    $("portEmptyHint").classList.toggle("hidden", !showPort || portIds.length > 0);

    const landFrag = document.createDocumentFragment();
    for (const id of landIds) {
      const rec = this.cards.get(id);
      if (rec) landFrag.appendChild(rec.el);
    }
    primaryGrid.appendChild(landFrag);

    const portFrag = document.createDocumentFragment();
    for (const id of portIds) {
      const rec = this.cards.get(id);
      if (rec) portFrag.appendChild(rec.el);
    }
    portraitGrid.appendChild(portFrag);
  }

  _updateCountsAndButtons() {
    const total = this.itemOrder.length;
    if (total > 0 && this.orientationIsolated) {
      let land = 0;
      for (const id of this.itemOrder) {
        const it = this.items.get(id);
        if (it && this._orientationOf(it) === "landscape") land++;
      }
      const port = total - land;
      $("countBadge").textContent = `共 ${total} 项 · 横${land} / 竖${port}`;
    } else {
      let vids = 0;
      for (const id of this.itemOrder) {
        if (this.items.get(id)?.mediaType === "video") vids++;
      }
      $("countBadge").textContent = vids > 0 ? `共 ${total} 项 (视频 ${vids})` : `共 ${total} 项`;
    }

    $("btnClearAll").disabled = total === 0;
    $("btnTopExport").disabled = total === 0;
    $("btnExportZip").disabled = total === 0;
    $("btnExportZip").textContent =
      total === 1 ? "⬇ 直接导出文件 (1 项)" : `⬇ 打包导出 ZIP (${total} 项)`;
    $("btnExportDir").disabled = total === 0 || typeof window.showDirectoryPicker !== "function";
    if ($("mobileGallerySummary")) {
      $("mobileGallerySummary").textContent = `实时预览 · ${$("countBadge").textContent}`;
    }
  }

  // ---- Real-Time Multi-Preview Rendering ----

  _renderOpts() {
    return {
      logoImage: this.logoImage,
      customFontFamily: this.customFontFamily,
    };
  }

  _renderSingleCard(item) {
    if (!item.previewCanvas) return;
    const rec = this.cards.get(item.id);
    if (!rec) return;

    const pw = item.previewCanvas.width;
    const ph = item.previewCanvas.height;
    if (rec.canvas.width !== pw || rec.canvas.height !== ph) {
      rec.canvas.width = pw;
      rec.canvas.height = ph;
    }
    const ctx = rec.canvas.getContext("2d");
    ctx.clearRect(0, 0, pw, ph);
    ctx.drawImage(item.previewCanvas, 0, 0);

    const cfg = this.getConfigForOrientation(this._orientationOf(item));
    drawWatermarkOverlay(ctx, pw, ph, cfg, item.origW, item.origH, this._renderOpts());
  }

  _scheduleRenderAll() {
    if (this._renderTimer) clearTimeout(this._renderTimer);
    this._renderTimer = setTimeout(() => {
      this._renderTimer = null;
      this._renderAllNow();
    }, 30);
  }

  _renderAllNow() {
    if (this.itemOrder.length === 0) return;
    for (const id of this.itemOrder) {
      const item = this.items.get(id);
      if (item && item.previewCanvas) {
        this._renderSingleCard(item);
      }
    }
    this._setStatus(`实时预览已同步更新 · 共 ${this.itemOrder.length} 项媒体`);
  }

  // ---- Controls Sync ----

  _setWatermarkType(type) {
    $("btnTypeText").classList.toggle("active", type === "text");
    $("btnTypeImage").classList.toggle("active", type === "image");
    $("textControls").classList.toggle("hidden", type !== "text");
    $("logoControls").classList.toggle("hidden", type !== "image");
    this._onControlChanged();
  }

  _setLayoutMode(mode) {
    $("btnModeTiled").classList.toggle("active", mode === "tiled");
    $("btnModeSingle").classList.toggle("active", mode === "single");
    $("tiledControls").classList.toggle("hidden", mode !== "tiled");
    $("singleControls").classList.toggle("hidden", mode !== "single");
    this._onControlChanged();
  }

  _syncEffectEnabled() {
    const strokeOn = $("chkStroke").checked;
    const shadowOn = $("chkShadow").checked;
    $("strokeWidthRow").style.opacity = strokeOn ? "1" : "0.45";
    $("rngStrokeWidth").disabled = !strokeOn;
    $("numStrokeWidth").disabled = !strokeOn;
    $("clrStroke").disabled = !strokeOn;

    $("shadowOffsetRow").style.opacity = shadowOn ? "1" : "0.45";
    $("rngShadowOffset").disabled = !shadowOn;
    $("numShadowOffset").disabled = !shadowOn;
    $("clrShadow").disabled = !shadowOn;
  }

  _readConfigFromUI() {
    const activeAnchorBtn = document.querySelector("#anchorGrid .anchor-btn.active");
    return cloneConfig({
      watermark_type: $("btnTypeText").classList.contains("active") ? "text" : "image",
      text: $("txtWatermark").value,
      font_name: $("fontSelect").value,
      custom_font_path: this.customFontName,
      font_size: Number($("numFontSize").value) || 44,
      proportional_size: $("chkProportionalText").checked,
      text_color: $("clrText").value.toUpperCase(),
      line_spacing: Number($("numLineSpacing").value) || 1.25,
      stroke_enabled: $("chkStroke").checked,
      stroke_width: Number($("numStrokeWidth").value) || 2,
      stroke_color: $("clrStroke").value.toUpperCase(),
      shadow_enabled: $("chkShadow").checked,
      shadow_offset: Number($("numShadowOffset").value) || 3,
      shadow_color: $("clrShadow").value.toUpperCase(),
      logo_scale_percent: Number($("numLogoScale").value) || 22,
      opacity: Number($("numOpacity").value) ?? 55,
      rotation: Number($("numRotation").value) || 0,
      layout_mode: $("btnModeTiled").classList.contains("active") ? "tiled" : "single",
      anchor: activeAnchorBtn ? activeAnchorBtn.dataset.anchor : "bottom_right",
      margin_x_percent: Number($("numMarginX").value) || 0,
      margin_y_percent: Number($("numMarginY").value) || 0,
      offset_x_percent: Number($("numOffsetX").value) || 0,
      offset_y_percent: Number($("numOffsetY").value) || 0,
      tile_spacing_x: Number($("numTileX").value) || 120,
      tile_spacing_y: Number($("numTileY").value) || 100,
      tile_stagger: $("chkTileStagger").checked,
    });
  }

  _applyConfigToUI(cfg) {
    this._updatingUI = true;
    const c = cloneConfig(cfg);
    this._storeIntoSlots(c);

    const isText = c.watermark_type === "text";
    $("btnTypeText").classList.toggle("active", isText);
    $("btnTypeImage").classList.toggle("active", !isText);
    $("textControls").classList.toggle("hidden", !isText);
    $("logoControls").classList.toggle("hidden", isText);

    $("txtWatermark").value = c.text;
    if ([...$("fontSelect").options].some((o) => o.value === c.font_name)) {
      $("fontSelect").value = c.font_name;
    }

    $("rngFontSize").value = c.font_size;
    $("numFontSize").value = c.font_size;
    $("chkProportionalText").checked = Boolean(c.proportional_size);
    $("chkProportionalLogo").checked = Boolean(c.proportional_size);

    $("rngLineSpacing").value = Math.round(c.line_spacing * 10);
    $("numLineSpacing").value = Number(c.line_spacing).toFixed(1);

    $("clrText").value = c.text_color.toLowerCase();
    $("clrTextHex").textContent = c.text_color.toUpperCase();

    $("chkStroke").checked = Boolean(c.stroke_enabled);
    $("rngStrokeWidth").value = c.stroke_width;
    $("numStrokeWidth").value = c.stroke_width;
    $("clrStroke").value = c.stroke_color.toLowerCase();
    $("clrStrokeHex").textContent = c.stroke_color.toUpperCase();

    $("chkShadow").checked = Boolean(c.shadow_enabled);
    $("rngShadowOffset").value = c.shadow_offset;
    $("numShadowOffset").value = c.shadow_offset;
    $("clrShadow").value = c.shadow_color.toLowerCase();
    $("clrShadowHex").textContent = c.shadow_color.toUpperCase();
    this._syncEffectEnabled();

    $("rngLogoScale").value = c.logo_scale_percent;
    $("numLogoScale").value = c.logo_scale_percent;

    $("rngOpacity").value = c.opacity;
    $("numOpacity").value = c.opacity;
    $("rngRotation").value = c.rotation;
    $("numRotation").value = c.rotation;

    const isTiled = c.layout_mode === "tiled";
    $("btnModeTiled").classList.toggle("active", isTiled);
    $("btnModeSingle").classList.toggle("active", !isTiled);
    $("tiledControls").classList.toggle("hidden", !isTiled);
    $("singleControls").classList.toggle("hidden", isTiled);

    document.querySelectorAll("#anchorGrid .anchor-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.anchor === c.anchor);
    });

    $("rngMarginX").value = Math.round(c.margin_x_percent * 10);
    $("numMarginX").value = Number(c.margin_x_percent).toFixed(1);
    $("rngMarginY").value = Math.round(c.margin_y_percent * 10);
    $("numMarginY").value = Number(c.margin_y_percent).toFixed(1);
    $("rngOffsetX").value = Math.round(c.offset_x_percent * 10);
    $("numOffsetX").value = Number(c.offset_x_percent).toFixed(1);
    $("rngOffsetY").value = Math.round(c.offset_y_percent * 10);
    $("numOffsetY").value = Number(c.offset_y_percent).toFixed(1);

    $("rngTileX").value = c.tile_spacing_x;
    $("numTileX").value = c.tile_spacing_x;
    $("rngTileY").value = c.tile_spacing_y;
    $("numTileY").value = c.tile_spacing_y;
    $("chkTileStagger").checked = Boolean(c.tile_stagger);

    this._updatingUI = false;
  }

  _storeIntoSlots(cfg) {
    this.activeConfig = cloneConfig(cfg);
    if (this.orientationIsolated && this.independentParams) {
      if (this.editingOrientation === "portrait") this.portraitConfig = cloneConfig(cfg);
      else this.landscapeConfig = cloneConfig(cfg);
    } else {
      this.landscapeConfig = cloneConfig(cfg);
      this.portraitConfig = cloneConfig(cfg);
    }
  }

  _onControlChanged() {
    if (this._updatingUI) return;
    const cfg = this._readConfigFromUI();
    this._storeIntoSlots(cfg);
    this._scheduleRenderAll();
  }

  async _onLogoFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const img = await loadHtmlImageFromFile(file);
      this.logoImage = img;
      $("logoFileName").textContent = file.name;
      const thumb = $("logoThumbBox");
      thumb.innerHTML = "";
      const previewImg = document.createElement("img");
      previewImg.src = img.src;
      previewImg.alt = file.name;
      // Re-create preview data URL since object URL was revoked
      const c = document.createElement("canvas");
      c.width = Math.min(96, img.width);
      c.height = Math.max(1, Math.round((img.height / img.width) * c.width));
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      previewImg.src = c.toDataURL("image/png");
      thumb.appendChild(previewImg);
      this._onControlChanged();
      this._toast(`已载入 Logo：${file.name}`);
    } catch (err) {
      this._toast(err?.message || "Logo 图片读取失败");
    }
  }

  async _onCustomFontFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const familyName = `BWMCustomFont_${Date.now()}`;
      const buf = await file.arrayBuffer();
      const face = new FontFace(familyName, buf);
      await face.load();
      document.fonts.add(face);
      this.customFontFamily = familyName;
      this.customFontName = file.name;
      const info = $("customFontInfo");
      info.textContent = `已加载自定义字体：${file.name}`;
      info.classList.remove("hidden");
      this._onControlChanged();
      this._toast(`自定义字体已生效：${file.name}`);
    } catch {
      this._toast("字体加载失败，请确认文件为有效的 TTF / OTF / WOFF2");
    }
  }

  // ---- Preset Management ----

  _rebuildPresetSelect(selectValue = "") {
    const sel = $("presetSelect");
    sel.innerHTML = "";
    const optEmpty = document.createElement("option");
    optEmpty.value = "";
    optEmpty.textContent = "选择预设模板...";
    sel.appendChild(optEmpty);

    const custom = this.presetStore.listCustom();
    for (const name of Object.keys(custom)) {
      const opt = document.createElement("option");
      opt.value = `custom:${name}`;
      opt.textContent = `[自定义] ${name}`;
      sel.appendChild(opt);
    }
    for (const name of Object.keys(this.builtinPresets)) {
      const opt = document.createElement("option");
      opt.value = `builtin:${name}`;
      opt.textContent = `[内置] ${name}`;
      sel.appendChild(opt);
    }

    if (selectValue) sel.value = selectValue;
    this._updateDeletePresetState();
  }

  _updateDeletePresetState() {
    $("btnDeletePreset").disabled = !$("presetSelect").value.startsWith("custom:");
  }

  _onPresetSelected() {
    this._updateDeletePresetState();
    const val = $("presetSelect").value;
    if (!val) return;
    if (val.startsWith("builtin:")) {
      const name = val.slice("builtin:".length);
      if (this.builtinPresets[name]) {
        this._applyConfigToUI(this.builtinPresets[name]);
        this._scheduleRenderAll();
      }
    } else if (val.startsWith("custom:")) {
      const name = val.slice("custom:".length);
      const cfg = this.presetStore.getCustom(name);
      if (cfg) {
        this._applyConfigToUI(cfg);
        this._scheduleRenderAll();
      }
    }
  }

  _onSavePreset() {
    const curVal = $("presetSelect").value;
    const defaultName = curVal.startsWith("custom:") ? curVal.slice("custom:".length) : "";
    const name = window.prompt("请输入预设名称（将保存至浏览器本机存储，下次打开自动加载）：", defaultName);
    if (name === null) return;
    const clean = name.trim();
    if (!clean) {
      this._toast("预设名称不能为空");
      return;
    }
    if (this.presetStore.hasCustom(clean) && !window.confirm(`本机已存在预设「${clean}」，是否覆盖？`)) {
      return;
    }
    this.presetStore.saveCustom(clean, this._readConfigFromUI());
    this._rebuildPresetSelect(`custom:${clean}`);
    this._trackEvent("preset_saved", { preset_name: clean });
    this._toast(`已保存到本机预设：${clean}`);
  }

  _onDeletePreset() {
    const val = $("presetSelect").value;
    if (!val.startsWith("custom:")) return;
    const name = val.slice("custom:".length);
    if (!window.confirm(`确定删除本机自定义预设「${name}」吗？`)) return;
    this.presetStore.deleteCustom(name);
    this._rebuildPresetSelect("");
    this._toast(`已删除预设：${name}`);
  }

  async _onImportPresetFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const imported = this.presetStore.importFromText(text, stripExtension(file.name));
      const first = imported[0];
      this._rebuildPresetSelect(`custom:${first}`);
      const cfg = this.presetStore.getCustom(first);
      if (cfg) {
        this._applyConfigToUI(cfg);
        this._scheduleRenderAll();
      }
      this._toast(`已导入 ${imported.length} 个预设并保存到本机：${imported.join("、")}`);
    } catch (err) {
      window.alert(`导入预设失败：\n${err?.message || err}`);
    }
  }

  _onExportCurrentPreset() {
    const val = $("presetSelect").value;
    const presetName = val.includes(":") ? val.slice(val.indexOf(":") + 1) : "我的水印预设";
    const json = this.presetStore.buildExportJson({ [presetName]: this._readConfigFromUI() });
    const safeName = presetName.replace(/[\\/:*?"<>|]/g, "").trim() || "watermark_preset";
    this._downloadBlob(new Blob([json], { type: "application/json;charset=utf-8" }), `${safeName}.json`);
    this._toast(`已导出预设：${safeName}.json`);
  }

  _onExportAllPresets() {
    const all = this.presetStore.listCustom();
    const count = Object.keys(all).length;
    if (count === 0) {
      this._toast("当前没有已保存的本机自定义预设");
      return;
    }
    const json = this.presetStore.buildExportJson(all);
    this._downloadBlob(
      new Blob([json], { type: "application/json;charset=utf-8" }),
      "BatchWatermark_presets.json",
    );
    this._toast(`已导出全部 ${count} 个自定义预设`);
  }

  // ---- High-Res Lightbox & Live Video Preview ----

  async _openLightbox(itemId) {
    const idx = this.itemOrder.indexOf(itemId);
    if (idx < 0) return;
    this._lbIndex = idx;
    $("lightboxModal").classList.remove("hidden");
    await this._renderLightboxCurrent();
  }

  _closeLightbox() {
    this._stopLightboxVideo();
    $("lightboxModal").classList.add("hidden");
  }

  async _stepLightbox(delta) {
    const next = this._lbIndex + delta;
    if (next < 0 || next >= this.itemOrder.length) return;
    this._lbIndex = next;
    await this._renderLightboxCurrent();
  }

  _stopLightboxVideo() {
    this._lbPlaying = false;
    if (this._lbRafId) {
      cancelAnimationFrame(this._lbRafId);
      this._lbRafId = null;
    }
    if (this._lbVideo) {
      this._lbVideo.pause();
      this._lbVideo.removeAttribute("src");
      this._lbVideo.load();
      this._lbVideo = null;
    }
    if (this._lbVideoUrl) {
      URL.revokeObjectURL(this._lbVideoUrl);
      this._lbVideoUrl = "";
    }
    $("btnLbPlay").textContent = "▶ 实时预览播放";
  }

  async _renderLightboxCurrent() {
    this._stopLightboxVideo();
    const id = this.itemOrder[this._lbIndex];
    const item = this.items.get(id);
    if (!item) return;

    const orientTxt = this._orientationOf(item) === "portrait" ? "竖版" : "横版";
    const kindTxt = item.mediaType === "video" ? `视频 (${formatDuration(item.duration)})` : "图片";
    $("lightboxTitle").textContent =
      `[${this._lbIndex + 1}/${this.itemOrder.length}] ${item.filename} · ${kindTxt} · ${orientTxt} · ${item.origW} × ${item.origH}`;
    $("btnLbPrev").disabled = this._lbIndex <= 0;
    $("btnLbNext").disabled = this._lbIndex >= this.itemOrder.length - 1;

    const cfg = this.getConfigForOrientation(this._orientationOf(item));
    const canvas = $("lightboxCanvas");
    const ctx = canvas.getContext("2d");

    if (item.mediaType === "video") {
      $("lightboxVideoBar").classList.remove("hidden");
      const url = URL.createObjectURL(item.file);
      const vid = document.createElement("video");
      vid.playsInline = true;
      vid.muted = false;
      vid.preload = "auto";
      vid.src = url;
      this._lbVideo = vid;
      this._lbVideoUrl = url;

      await new Promise((res, rej) => {
        vid.addEventListener("loadeddata", res, { once: true });
        vid.addEventListener("error", () => rej(new Error("视频加载失败")), { once: true });
      });

      const scale = Math.min(1, 1440 / Math.max(vid.videoWidth, vid.videoHeight));
      canvas.width = Math.max(1, Math.round(vid.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(vid.videoHeight * scale));

      const drawVidFrame = () => {
        ctx.drawImage(vid, 0, 0, canvas.width, canvas.height);
        drawWatermarkOverlay(ctx, canvas.width, canvas.height, cfg, vid.videoWidth, vid.videoHeight, this._renderOpts());
        const dur = vid.duration || item.duration || 0;
        const pct = dur > 0 ? Math.round((vid.currentTime / dur) * 1000) : 0;
        $("rngLbTime").value = pct;
        $("lblLbTime").textContent = `${formatDuration(vid.currentTime)} / ${formatDuration(dur)}`;
      };

      vid.addEventListener("seeked", drawVidFrame);
      vid.addEventListener("ended", () => {
        this._lbPlaying = false;
        $("btnLbPlay").textContent = "▶ 实时预览播放";
      });
      this._lbDrawFrameFn = drawVidFrame;
      drawVidFrame();
      return;
    }

    $("lightboxVideoBar").classList.add("hidden");
    const img = await loadHtmlImageFromFile(item.file);
    const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    canvas.width = Math.max(1, Math.round(img.width * scale));
    canvas.height = Math.max(1, Math.round(img.height * scale));
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    drawWatermarkOverlay(ctx, canvas.width, canvas.height, cfg, img.width, img.height, this._renderOpts());
  }

  async _toggleLightboxVideoPlay() {
    if (!this._lbVideo) return;
    if (this._lbPlaying) {
      this._lbVideo.pause();
      this._lbPlaying = false;
      if (this._lbRafId) cancelAnimationFrame(this._lbRafId);
      $("btnLbPlay").textContent = "▶ 实时预览播放";
      return;
    }
    this._lbPlaying = true;
    $("btnLbPlay").textContent = "⏸ 暂停预览";
    try {
      await this._lbVideo.play();
    } catch {
      this._lbVideo.muted = true;
      await this._lbVideo.play();
    }
    const loop = () => {
      if (!this._lbPlaying || !this._lbVideo) return;
      if (this._lbDrawFrameFn) this._lbDrawFrameFn();
      this._lbRafId = requestAnimationFrame(loop);
    };
    loop();
  }

  _onLightboxScrub() {
    if (!this._lbVideo || !this._lbVideo.duration) return;
    const frac = Number($("rngLbTime").value) / 1000;
    this._lbVideo.currentTime = frac * this._lbVideo.duration;
  }

  _jumpLightboxVideo(frac) {
    if (!this._lbVideo || !this._lbVideo.duration) return;
    this._lbVideo.currentTime = Math.min(this._lbVideo.duration, Math.max(0, frac * this._lbVideo.duration));
  }

  // ---- Batch Export (ZIP & Direct Local Folder) ----

  _readExportConfig() {
    return {
      prefix: $("txtPrefix").value || "",
      suffix: $("txtSuffix").value || "",
      outputFormat: $("selOutputFormat").value,
      quality: Number($("numQuality").value) || 92,
      isolateOrientation: this.orientationIsolated,
      videoKeepAudio: $("chkVideoAudio").checked,
    };
  }

  async startExport(mode) {
    if (this.itemOrder.length === 0) return;

    let dirHandle = null;
    if (mode === "directory") {
      if (typeof window.showDirectoryPicker !== "function") {
        this._toast("当前浏览器不支持直接写入目录，请使用「打包导出 ZIP」");
        return;
      }
      try {
        dirHandle = await window.showDirectoryPicker({ mode: "readwrite" });
      } catch (err) {
        if (err?.name === "AbortError") return;
        this._toast(`无法访问文件夹：${err?.message || err}`);
        return;
      }
    }

    const exportConfig = this._readExportConfig();
    const list = this.itemOrder.map((id) => this.items.get(id)).filter(Boolean);
    const total = list.length;
    const directSingleDownload = mode === "zip" && total === 1;

    this._exportCancelled = false;
    $("btnCancelExport").disabled = false;
    $("btnCancelExport").textContent = "取消导出";
    $("exportModalTitle").textContent =
      mode === "directory"
        ? "正在批量导出到本地文件夹"
        : directSingleDownload
          ? "正在导出水印文件"
          : "正在批量处理并打包 ZIP";
    $("exportProgressFill").style.width = "0%";
    $("exportPercentText").textContent = "0%";
    $("exportStatusDetail").textContent = `准备导出共 ${total} 项媒体...`;
    $("exportModal").classList.remove("hidden");

    const zip = mode === "zip" && !directSingleDownload ? new ZipBuilder() : null;
    const usedRelPaths = new Set();
    let success = 0;
    let singleResult = null;
    const errors = [];

    const setProgress = (pct, detail) => {
      const clamped = Math.max(0, Math.min(100, Math.round(pct)));
      $("exportProgressFill").style.width = `${clamped}%`;
      $("exportPercentText").textContent = `${clamped}%`;
      $("exportStatusDetail").textContent = detail;
    };

    try {
      for (let i = 0; i < total; i++) {
        if (this._exportCancelled) break;
        const item = list[i];
        const orient = this._orientationOf(item);
        const cfg = this.getConfigForOrientation(orient);
        const kind = item.mediaType === "video" ? "视频" : "图片";
        const basePct = (i / total) * 100;

        setProgress(basePct, `(${i + 1}/${total}) 正在处理${kind}：${item.filename}`);

        try {
          let blob;
          let ext;
          if (item.mediaType === "video") {
            const res = await exportWatermarkedVideo(
              item,
              cfg,
              exportConfig,
              this._renderOpts(),
              (frac) => {
                const subPct = basePct + (frac * 100) / total;
                setProgress(subPct, `(${i + 1}/${total}) 正在录制导出视频 (${Math.round(frac * 100)}%)：${item.filename}`);
              },
              () => this._exportCancelled,
            );
            blob = res.blob;
            ext = res.ext;
          } else {
            const res = await exportImageBlob(item, cfg, exportConfig, this._renderOpts());
            blob = res.blob;
            ext = res.ext;
          }

          const subfolder = exportConfig.isolateOrientation ? (orient === "portrait" ? "竖版" : "横版") : "";
          const baseStem = `${exportConfig.prefix}${stripExtension(item.filename)}${exportConfig.suffix}`;
          let finalName = `${baseStem}${ext}`;
          let relPath = subfolder ? `${subfolder}/${finalName}` : finalName;
          let counter = 1;
          while (usedRelPaths.has(relPath.toLowerCase())) {
            finalName = `${baseStem}_${counter}${ext}`;
            relPath = subfolder ? `${subfolder}/${finalName}` : finalName;
            counter++;
          }
          usedRelPaths.add(relPath.toLowerCase());

          if (directSingleDownload) {
            singleResult = { blob, filename: finalName };
          } else if (mode === "zip") {
            await zip.addFile(relPath, blob);
          } else {
            let targetDir = dirHandle;
            if (subfolder) {
              targetDir = await dirHandle.getDirectoryHandle(subfolder, { create: true });
            }
            const fileHandle = await targetDir.getFileHandle(finalName, { create: true });
            const writable = await fileHandle.createWritable();
            await writable.write(blob);
            await writable.close();
          }

          success++;
        } catch (err) {
          if (err?.message === "__CANCELLED__") break;
          errors.push(`${item.filename}: ${err?.message || err}`);
        }

        setProgress(((i + 1) / total) * 100, `(${i + 1}/${total}) 已完成：${item.filename}`);
      }

      if (!this._exportCancelled && directSingleDownload && singleResult) {
        this._downloadBlob(singleResult.blob, singleResult.filename);
      } else if (!this._exportCancelled && mode === "zip" && success > 0) {
        setProgress(100, "正在生成 ZIP 压缩包...");
        const zipBlob = zip.buildBlob();
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
        this._downloadBlob(zipBlob, `BatchWatermark_${stamp}.zip`);
      }
    } finally {
      $("exportModal").classList.add("hidden");
    }

    if (!this._exportCancelled && success > 0) {
      this._trackEvent("watermark_exported", {
        mode: directSingleDownload ? "single" : mode,
        count: success,
        isolated: exportConfig.isolateOrientation,
      });
    }

    if (this._exportCancelled) {
      this._setStatus(`批量导出已取消 · 已完成 ${success} 项`);
      this._toast(`导出已取消（已完成 ${success} 项）`);
    } else if (errors.length === 0) {
      const isoNote = exportConfig.isolateOrientation ? "（已自动按「横版/」「竖版/」分类）" : "";
      this._setStatus(`批量导出成功 · 共导出 ${success} 项${isoNote}`);
      this._toast(`导出完成！共 ${success} 项${isoNote}`);
    } else {
      this._setStatus(`批量导出完成 · 成功 ${success} 项，失败 ${errors.length} 项`);
      window.alert(`导出完成：成功 ${success} 项，失败 ${errors.length} 项。\n\n${errors.slice(0, 6).join("\n")}`);
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

  _setStatus(text) {
    $("statusText").textContent = text;
  }

  _trackEvent(eventName, params = {}) {
    try {
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: eventName, ...params });
    } catch {
      // ignore if blocked
    }
  }

  _toast(message) {
    const host = $("toastHost");
    const item = document.createElement("div");
    item.className = "toast-item";
    item.textContent = message;
    host.appendChild(item);
    setTimeout(() => item.remove(), 3200);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const workApp = new BatchWatermarkApp();
  const creativeApp = new CreativeModeApp({
    toast: (msg) => workApp._toast(msg),
    trackEvent: (name, params) => workApp._trackEvent(name, params),
  });

  // Top Dual-Mode Tab Switcher (Work Mode vs Creative Mode — completely independent)
  const switchMode = (mode) => {
    const isCreative = mode === "creative";
    $("workModeView").classList.toggle("hidden", isCreative);
    $("creativeModeView").classList.toggle("hidden", !isCreative);

    $("tabModeWork").classList.toggle("active", !isCreative);
    $("tabModeWork").setAttribute("aria-selected", String(!isCreative));
    $("tabModeCreative").classList.toggle("active", isCreative);
    $("tabModeCreative").setAttribute("aria-selected", String(isCreative));

    if (isCreative) {
      requestAnimationFrame(() => creativeApp.renderCanvas());
    }
    workApp._trackEvent("app_mode_switched", { mode });
  };

  $("tabModeWork")?.addEventListener("click", () => switchMode("work"));
  $("tabModeCreative")?.addEventListener("click", () => switchMode("creative"));

  window.__batchWatermarkApp = workApp;
  window.__creativeApp = creativeApp;
  window.__switchAppMode = switchMode;
});
