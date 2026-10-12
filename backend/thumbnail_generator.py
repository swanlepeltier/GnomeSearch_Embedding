"""Thumbnail generation and caching for search results.

Thumbnails are written to the configured cache directory (``DATA_DIR/thumbnails``)
and referenced by absolute path in the D-Bus result payload. Their filename is a
stable hash of the source file plus the timestamp, so re-indexing reuses them.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from PIL import Image

import config


def _dest_path(source: str, timestamp: Optional[float]) -> Path:
    key = f"{source}@{timestamp}" if timestamp is not None else source
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return config.THUMBNAIL_DIR / f"{digest}.jpg"


def _scale_to_width(image: Image.Image, width: int) -> Image.Image:
    if image.width <= width:
        return image
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.LANCZOS)


def _pad_to(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Letterbox an image into a fixed-size box, preserving aspect ratio."""
    box_w, box_h = size
    scale = min(box_w / image.width, box_h / image.height)
    new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGB", (box_w, box_h), (0, 0, 0))
    canvas.paste(resized, ((box_w - new_size[0]) // 2, (box_h - new_size[1]) // 2))
    return canvas


def generate_thumbnail(
    image: Image.Image,
    source: str,
    *,
    timestamp: Optional[float] = None,
    size: Optional[tuple[int, int]] = None,
) -> str:
    """Write a thumbnail for ``image`` and return its absolute path.

    ``size`` fixes the output box (used for video frames, 16:9). When omitted the
    image is scaled to ``THUMBNAIL_WIDTH`` keeping its aspect ratio.
    """
    config.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    dest = _dest_path(source, timestamp)
    image = image.convert("RGB")
    image = _pad_to(image, size) if size else _scale_to_width(image, config.THUMBNAIL_WIDTH)
    image.save(dest, "JPEG", quality=82)
    return str(dest)


def delete_thumbnail(path: Optional[str]) -> None:
    """Best-effort removal of a single cached thumbnail file."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
