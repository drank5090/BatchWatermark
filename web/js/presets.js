/**
 * Local preset persistence (localStorage) + JSON import/export compatible with Desktop EXE.
 */

import {
  PRESET_SCHEMA_ID,
  PRESET_SCHEMA_VERSION,
  cloneConfig,
  defaultWatermarkConfig,
  sanitizeConfig,
} from "./models.js";

const STORAGE_KEY = "batch_watermark_custom_presets_v1";

export class PresetStore {
  constructor() {
    this._custom = {};
    this.reload();
  }

  reload() {
    this._custom = {};
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      this._custom = PresetStore.parsePayload(parsed, "自定义预设");
    } catch {
      this._custom = {};
    }
    return this.listCustom();
  }

  _persist() {
    const payload = {
      schema: PRESET_SCHEMA_ID,
      version: PRESET_SCHEMA_VERSION,
      presets: this._custom,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }

  listCustom() {
    const copy = {};
    for (const [k, v] of Object.entries(this._custom)) {
      copy[k] = cloneConfig(v);
    }
    return copy;
  }

  hasCustom(name) {
    return Object.prototype.hasOwnProperty.call(this._custom, name);
  }

  getCustom(name) {
    return this.hasCustom(name) ? cloneConfig(this._custom[name]) : null;
  }

  saveCustom(name, config) {
    const clean = String(name || "").trim();
    if (!clean) throw new Error("预设名称不能为空");
    this._custom[clean] = sanitizeConfig(config);
    this._persist();
    return clean;
  }

  deleteCustom(name) {
    if (!this.hasCustom(name)) return false;
    delete this._custom[name];
    this._persist();
    return true;
  }

  buildExportJson(presetsObj) {
    const payload = {
      schema: PRESET_SCHEMA_ID,
      version: PRESET_SCHEMA_VERSION,
      presets: presetsObj,
    };
    return JSON.stringify(payload, null, 2);
  }

  importFromText(jsonText, fallbackName = "导入预设") {
    const raw = JSON.parse(jsonText);
    const incoming = PresetStore.parsePayload(raw, fallbackName);
    const entries = Object.entries(incoming);
    if (entries.length === 0) {
      throw new Error("文件中未找到有效的水印预设配置");
    }
    const importedNames = [];
    for (const [rawName, cfg] of entries) {
      let finalName = String(rawName || "").trim() || "导入预设";
      if (this.hasCustom(finalName)) {
        let idx = 2;
        while (this.hasCustom(`${finalName} (${idx})`)) idx++;
        finalName = `${finalName} (${idx})`;
      }
      this._custom[finalName] = sanitizeConfig(cfg);
      importedNames.push(finalName);
    }
    this._persist();
    return importedNames;
  }

  static parsePayload(raw, fallbackName = "导入预设") {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      throw new Error("预设 JSON 格式无效：根节点必须是对象");
    }
    const out = {};
    if (raw.presets && typeof raw.presets === "object" && !Array.isArray(raw.presets)) {
      for (const [name, cfg] of Object.entries(raw.presets)) {
        if (cfg && typeof cfg === "object") {
          out[String(name)] = sanitizeConfig(cfg);
        }
      }
      return out;
    }
    const knownKeys = new Set(Object.keys(defaultWatermarkConfig()));
    if (Object.keys(raw).some((k) => knownKeys.has(k))) {
      const name = String(raw.name || fallbackName).trim() || fallbackName;
      out[name] = sanitizeConfig(raw);
    }
    return out;
  }
}
