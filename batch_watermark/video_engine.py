"""FFmpeg-backed video frame extraction and full-resolution watermarked video export."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

from PIL import Image

from .engine import PREVIEW_MAX_EDGE, build_watermark_overlay, resolve_output_path
from .models import (
    ExportConfig,
    OrientationGroup,
    SUPPORTED_VIDEO_EXTENSIONS,
    WatermarkConfig,
)


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def is_video_file(path: Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def _subprocess_creationflags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


@lru_cache(maxsize=1)
def find_ffmpeg_executable() -> str | None:
    """Locate FFmpeg binary: bundled PyInstaller bin -> local bin -> PATH -> imageio_ffmpeg."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "bin" / "ffmpeg.exe")
        candidates.append(Path(meipass) / "bin" / "ffmpeg")

    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "bin" / "ffmpeg.exe")
    candidates.append(exe_dir / "ffmpeg.exe")

    project_root = Path(__file__).resolve().parent.parent
    candidates.append(project_root / "bin" / "ffmpeg.exe")

    for cand in candidates:
        if cand.is_file():
            return str(cand)

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe
    except Exception:  # noqa: BLE001
        pass

    return None


def _parse_duration_from_stderr(stderr_text: str) -> float:
    match = _DURATION_RE.search(stderr_text)
    if not match:
        return 0.0
    hours = int(match.group(1))
    mins = int(match.group(2))
    secs = float(match.group(3))
    return hours * 3600.0 + mins * 60.0 + secs


def _decode_frame_with_ffmpeg(ffmpeg: str, path: Path, seek_sec: float) -> tuple[bytes, str]:
    cmd = [ffmpeg, "-hide_banner", "-nostdin"]
    if seek_sec > 0.0:
        cmd.extend(["-ss", f"{seek_sec:.3f}"])
    cmd.extend([
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ])
    proc = subprocess.run(
        cmd,
        capture_output=True,
        creationflags=_subprocess_creationflags(),
        timeout=30,
    )
    stderr_text = proc.stderr.decode("utf-8", errors="ignore")
    return proc.stdout, stderr_text


def extract_video_frame(
    path: Path,
    timestamp_sec: float | None = None,
    max_edge: int | None = None,
) -> tuple[Image.Image, int, int, float]:
    """Decode one auto-oriented RGBA frame from a video and return (rgba, orig_w, orig_h, duration_sec)."""
    ffmpeg = find_ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg，无法解析或处理视频文件")

    seek = 0.5 if timestamp_sec is None else max(0.0, float(timestamp_sec))
    png_bytes, stderr_text = _decode_frame_with_ffmpeg(ffmpeg, path, seek)
    duration = _parse_duration_from_stderr(stderr_text)

    # Short video fallback: retry from t=0 if seeking past duration returned empty frame
    if not png_bytes and seek > 0.0:
        png_bytes, stderr_fallback = _decode_frame_with_ffmpeg(ffmpeg, path, 0.0)
        if duration <= 0.0:
            duration = _parse_duration_from_stderr(stderr_fallback)

    if not png_bytes:
        err_tail = stderr_text.strip().splitlines()[-1] if stderr_text.strip() else "未知视频解码错误"
        raise RuntimeError(f"无法读取视频帧：{err_tail}")

    with Image.open(BytesIO(png_bytes)) as frame:
        orig_w, orig_h = frame.size
        img = frame.copy()

    if max_edge and max(orig_w, orig_h) > max_edge:
        scale = max_edge / max(orig_w, orig_h)
        img = img.resize(
            (max(1, int(round(orig_w * scale))), max(1, int(round(orig_h * scale)))),
            Image.Resampling.LANCZOS,
        )

    return img.convert("RGBA"), orig_w, orig_h, duration


def create_video_preview_base(
    path: Path,
    max_edge: int = PREVIEW_MAX_EDGE,
) -> tuple[Image.Image, int, int, str, int, float]:
    """Load representative video frame and metadata for gallery preview."""
    file_size = path.stat().st_size if path.exists() else 0
    rgba, orig_w, orig_h, duration = extract_video_frame(path, timestamp_sec=None, max_edge=max_edge)
    fmt = path.suffix.lstrip(".").upper() or "VIDEO"
    return rgba, orig_w, orig_h, fmt, file_size, duration


def _quality_to_crf(quality: int) -> int:
    """Map UI quality slider (50..100) to libx264 CRF (28..16, lower is higher quality)."""
    q = max(50, min(100, int(quality)))
    return int(round(28 - (q - 50) * (12.0 / 50.0)))


def export_single_video(
    src_path: Path,
    wm_config: WatermarkConfig,
    export_config: ExportConfig,
    progress_callback: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Composite watermark overlay onto every frame of `src_path` and export an H.264 MP4."""
    ffmpeg = find_ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg，无法导出视频水印")

    # Decode first frame once to obtain guaranteed post-rotation display dimensions & duration
    _, orig_w, orig_h, duration_sec = extract_video_frame(src_path, timestamp_sec=0.0, max_edge=64)
    orientation = OrientationGroup.PORTRAIT if orig_h > orig_w else OrientationGroup.LANDSCAPE

    # H.264 yuv420p requires even width and height
    even_w = max(2, orig_w - (orig_w % 2))
    even_h = max(2, orig_h - (orig_h % 2))

    overlay = build_watermark_overlay((even_w, even_h), wm_config, reference_size=(even_w, even_h))
    out_path = resolve_output_path(src_path, export_config, ".mp4", orientation=orientation)

    crf = _quality_to_crf(export_config.quality)

    with tempfile.TemporaryDirectory(prefix="bwm_vid_") as tmp_dir:
        overlay_path = Path(tmp_dir) / "watermark_overlay.png"
        overlay.save(overlay_path, format="PNG")

        if even_w != orig_w or even_h != orig_h:
            filter_complex = f"[0:v]scale={even_w}:{even_h}[base];[base][1:v]overlay=0:0:format=auto[v]"
        else:
            filter_complex = "[0:v][1:v]overlay=0:0:format=auto[v]"

        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            str(src_path),
            "-i",
            str(overlay_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
        ]

        if export_config.video_keep_audio:
            cmd.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.append("-an")

        cmd.extend([
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_path),
        ])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=_subprocess_creationflags(),
        )

        cancelled = False
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if is_cancelled and is_cancelled():
                    cancelled = True
                    proc.terminate()
                    break
                line = raw_line.strip()
                if progress_callback and duration_sec > 0.05 and line.startswith("out_time_us="):
                    val_str = line.split("=", 1)[1].strip()
                    if val_str.lstrip("-").isdigit():
                        cur_sec = max(0.0, int(val_str) / 1_000_000.0)
                        progress_callback(min(0.99, cur_sec / duration_sec))
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)
            raise

        if cancelled:
            try:
                if out_path.exists():
                    out_path.unlink()
            except OSError:
                pass
            raise InterruptedError("视频导出已取消")

        if proc.returncode != 0:
            err_msg = proc.stderr.read().strip() if proc.stderr else ""
            try:
                if out_path.exists():
                    out_path.unlink()
            except OSError:
                pass
            raise RuntimeError(f"FFmpeg 视频导出失败：{err_msg or f'exit code {proc.returncode}'}")

    if progress_callback:
        progress_callback(1.0)
    return out_path
