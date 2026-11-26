"""Built-in presets and local persistent custom preset storage with JSON import/export."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from .models import AnchorPosition, LayoutMode, WatermarkConfig, WatermarkType

PRESET_SCHEMA_ID = "batch_watermark_presets"
PRESET_SCHEMA_VERSION = 1


def get_builtin_presets() -> dict[str, WatermarkConfig]:
    """Return built-in starter watermark presets."""
    return {
        "全图斜向平铺 (防盗)": WatermarkConfig(
            watermark_type=WatermarkType.TEXT,
            text="© 仅供内部使用",
            font_size=42,
            proportional_size=True,
            text_color="#FFFFFF",
            stroke_enabled=True,
            stroke_width=2,
            stroke_color="#000000",
            shadow_enabled=True,
            opacity=48,
            rotation=-25,
            layout_mode=LayoutMode.TILED,
            tile_spacing_x=130,
            tile_spacing_y=110,
            tile_stagger=True,
        ),
        "右下角精致签名": WatermarkConfig(
            watermark_type=WatermarkType.TEXT,
            text="© 2026 Photography",
            font_size=34,
            proportional_size=True,
            text_color="#FFFFFF",
            stroke_enabled=False,
            shadow_enabled=True,
            shadow_offset=2,
            opacity=82,
            rotation=0,
            layout_mode=LayoutMode.SINGLE,
            anchor=AnchorPosition.BOTTOM_RIGHT,
            margin_x_percent=3.5,
            margin_y_percent=3.5,
        ),
        "正中心醒目样图": WatermarkConfig(
            watermark_type=WatermarkType.TEXT,
            text="SAMPLE · 样图",
            font_size=76,
            proportional_size=True,
            text_color="#FFFFFF",
            stroke_enabled=True,
            stroke_width=3,
            stroke_color="#000000",
            shadow_enabled=True,
            opacity=62,
            rotation=-20,
            layout_mode=LayoutMode.SINGLE,
            anchor=AnchorPosition.CENTER,
        ),
        "底部居中版权栏": WatermarkConfig(
            watermark_type=WatermarkType.TEXT,
            text="版权所有 · 严禁未经授权转载",
            font_size=30,
            proportional_size=True,
            text_color="#F3F4F6",
            stroke_enabled=True,
            stroke_width=2,
            stroke_color="#111827",
            shadow_enabled=False,
            opacity=85,
            rotation=0,
            layout_mode=LayoutMode.SINGLE,
            anchor=AnchorPosition.BOTTOM_CENTER,
            margin_y_percent=2.5,
        ),
    }


def default_preset_storage_path() -> Path:
    """Return per-user local storage path for custom presets."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "BatchWatermark" / "custom_presets.json"


class PresetStore:
    """Manages local persistence and JSON import/export for custom watermark presets."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path: Path = Path(storage_path) if storage_path else default_preset_storage_path()
        self._custom: dict[str, WatermarkConfig] = {}
        self.reload()

    def reload(self) -> dict[str, WatermarkConfig]:
        """Load custom presets from local JSON storage."""
        self._custom = {}
        if not self.storage_path.is_file():
            return {}
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            parsed = self._parse_payload(raw, fallback_name=self.storage_path.stem)
            self._custom = parsed
        except Exception:  # noqa: BLE001
            self._custom = {}
        return self.list_custom()

    def _persist(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": PRESET_SCHEMA_ID,
            "version": PRESET_SCHEMA_VERSION,
            "presets": {name: cfg.to_dict() for name, cfg in self._custom.items()},
        }
        tmp_path = self.storage_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.storage_path)

    def list_custom(self) -> dict[str, WatermarkConfig]:
        return {k: v.clone() for k, v in self._custom.items()}

    def has_custom(self, name: str) -> bool:
        return name in self._custom

    def get_custom(self, name: str) -> WatermarkConfig | None:
        cfg = self._custom.get(name)
        return cfg.clone() if cfg is not None else None

    def save_custom(self, name: str, config: WatermarkConfig) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("预设名称不能为空")
        self._custom[clean_name] = config.clone()
        self._persist()
        return clean_name

    def delete_custom(self, name: str) -> bool:
        if name not in self._custom:
            return False
        del self._custom[name]
        self._persist()
        return True

    def export_presets_to_file(self, target_path: Path, presets: dict[str, WatermarkConfig]) -> Path:
        """Write one or more presets to a portable UTF-8 JSON file."""
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": PRESET_SCHEMA_ID,
            "version": PRESET_SCHEMA_VERSION,
            "presets": {name: cfg.to_dict() for name, cfg in presets.items()},
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def export_single_to_file(self, target_path: Path, name: str, config: WatermarkConfig) -> Path:
        clean_name = name.strip() or Path(target_path).stem or "自定义预设"
        return self.export_presets_to_file(target_path, {clean_name: config})

    def export_all_custom_to_file(self, target_path: Path) -> Path:
        if not self._custom:
            raise ValueError("当前没有已保存的本机自定义预设可供导出")
        return self.export_presets_to_file(target_path, self._custom)

    def import_from_file(self, source_path: Path, overwrite: bool = False) -> list[str]:
        """Import preset(s) from JSON file, save them locally, and return the imported names."""
        src = Path(source_path)
        raw = json.loads(src.read_text(encoding="utf-8"))
        incoming = self._parse_payload(raw, fallback_name=src.stem or "导入预设")
        if not incoming:
            raise ValueError("文件中未找到有效的水印预设配置")

        imported_names: list[str] = []
        for raw_name, cfg in incoming.items():
            final_name = raw_name.strip() or "导入预设"
            if not overwrite and final_name in self._custom:
                idx = 2
                candidate = f"{final_name} ({idx})"
                while candidate in self._custom:
                    idx += 1
                    candidate = f"{final_name} ({idx})"
                final_name = candidate
            self._custom[final_name] = cfg.clone()
            imported_names.append(final_name)

        self._persist()
        return imported_names

    @staticmethod
    def _parse_payload(raw: Any, fallback_name: str = "导入预设") -> dict[str, WatermarkConfig]:
        if not isinstance(raw, dict):
            raise ValueError("预设 JSON 格式无效：根节点必须是对象")

        result: dict[str, WatermarkConfig] = {}
        if "presets" in raw and isinstance(raw["presets"], dict):
            for name, cfg_dict in raw["presets"].items():
                if isinstance(cfg_dict, dict):
                    result[str(name)] = WatermarkConfig.from_dict(cfg_dict)
            return result

        # Support single flat preset JSON format (e.g. {"text": "...", "opacity": 60, ...})
        wm_keys = set(WatermarkConfig.__dataclass_fields__.keys())
        if any(k in wm_keys for k in raw):
            preset_name = str(raw.get("name") or fallback_name).strip() or fallback_name
            result[preset_name] = WatermarkConfig.from_dict(raw)
            return result

        return result
