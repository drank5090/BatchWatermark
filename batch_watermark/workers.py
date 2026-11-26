"""Background Qt worker classes for async media loading, live preview rendering, and batch export."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThread, Signal
from PySide6.QtGui import QImage

from .engine import apply_watermark, create_preview_base, export_single_image
from .models import ExportConfig, ImageItem, WatermarkConfig
from .video_engine import create_video_preview_base, export_single_video, is_video_file


def pil_rgba_to_qimage(img: Image.Image) -> QImage:
    """Convert a PIL RGBA Image to an owned, thread-safe QImage."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return qimg.copy()


class MediaLoadSignals(QObject):
    # item_id, pil_base, w, h, fmt, file_size, duration_sec
    loaded = Signal(str, object, int, int, str, int, float)
    failed = Signal(str, str)


class MediaLoadWorker(QRunnable):
    """Loads image or video representative frame and metadata off the UI thread."""

    def __init__(self, item_id: str, path: Path) -> None:
        super().__init__()
        self.item_id = item_id
        self.path = path
        self.signals = MediaLoadSignals()

    def run(self) -> None:
        try:
            if is_video_file(self.path):
                rgba, orig_w, orig_h, orig_fmt, file_size, duration = create_video_preview_base(self.path)
            else:
                rgba, orig_w, orig_h, orig_fmt, file_size = create_preview_base(self.path)
                duration = 0.0
            self.signals.loaded.emit(self.item_id, rgba, orig_w, orig_h, orig_fmt, file_size, duration)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self.item_id, str(exc))


# Backwards-compatible alias
ImageLoadWorker = MediaLoadWorker


class PreviewRenderSignals(QObject):
    rendered = Signal(str, int, QImage)  # item_id, epoch, qimage


class PreviewRenderWorker(QRunnable):
    """Renders watermark preview for one image/video frame if the render epoch is still current."""

    def __init__(
        self,
        item_id: str,
        preview_base: Image.Image,
        orig_size: tuple[int, int],
        config: WatermarkConfig,
        epoch: int,
        is_epoch_current: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.item_id = item_id
        self.preview_base = preview_base
        self.orig_size = orig_size
        self.config = config
        self.epoch = epoch
        self.is_epoch_current = is_epoch_current
        self.signals = PreviewRenderSignals()

    def run(self) -> None:
        if not self.is_epoch_current(self.epoch):
            return
        try:
            result = apply_watermark(
                self.preview_base,
                self.config,
                reference_size=self.orig_size,
            )
            if not self.is_epoch_current(self.epoch):
                return
            qimg = pil_rgba_to_qimage(result)
            self.signals.rendered.emit(self.item_id, self.epoch, qimg)
        except Exception:  # noqa: BLE001
            pass


class BatchExportThread(QThread):
    """Exports all selected images and videos with live progress reporting and cancellation."""

    # completed_percent_x100 (0..total*100), total_units (total*100), status_detail
    progress = Signal(int, int, str)
    finished_summary = Signal(int, int, list, bool)  # success_count, fail_count, errors, cancelled

    def __init__(
        self,
        items: list[ImageItem],
        wm_config: WatermarkConfig,
        export_config: ExportConfig,
        portrait_config: WatermarkConfig | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.items = list(items)
        self.wm_config = wm_config.clone()
        self.portrait_config = portrait_config.clone() if portrait_config is not None else None
        self.export_config = export_config
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _is_cancelled(self) -> bool:
        return self._cancel_requested

    def _config_for_item(self, item: ImageItem) -> WatermarkConfig:
        if self.portrait_config is not None and item.orig_height > item.orig_width > 0:
            return self.portrait_config
        return self.wm_config

    def run(self) -> None:
        total = len(self.items)
        total_units = max(1, total * 100)
        success = 0
        errors: list[tuple[str, str]] = []
        cancelled = False

        for idx, item in enumerate(self.items):
            if self._cancel_requested:
                cancelled = True
                break

            base_units = idx * 100
            kind = "视频" if item.is_video else "图片"
            self.progress.emit(base_units, total_units, f"({idx + 1}/{total}) 正在处理{kind}：{item.filename}")

            cfg = self._config_for_item(item)
            try:
                if item.is_video:
                    def _on_vid_prog(frac: float, b=base_units, i=idx, fn=item.filename) -> None:
                        pct = int(round(frac * 100))
                        self.progress.emit(
                            min(total_units, b + pct),
                            total_units,
                            f"({i + 1}/{total}) 正在导出视频 ({pct}%)：{fn}",
                        )

                    export_single_video(
                        item.path,
                        cfg,
                        self.export_config,
                        progress_callback=_on_vid_prog,
                        is_cancelled=self._is_cancelled,
                    )
                else:
                    export_single_image(item.path, cfg, self.export_config)
                success += 1
            except InterruptedError:
                cancelled = True
                break
            except Exception as exc:  # noqa: BLE001
                errors.append((item.filename, str(exc)))

            self.progress.emit((idx + 1) * 100, total_units, f"({idx + 1}/{total}) 已完成：{item.filename}")

        self.finished_summary.emit(success, len(errors), errors, cancelled)
