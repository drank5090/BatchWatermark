"""Direct script entry point for BatchWatermark (also used by PyInstaller)."""

from __future__ import annotations

from batch_watermark.app import main


if __name__ == "__main__":
    raise SystemExit(main())
