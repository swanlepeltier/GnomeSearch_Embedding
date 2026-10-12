"""File indexing: embed supported files and keep FAISS + SQLite in sync.

The indexer walks the configured directories, embeds text/images/video/audio and
stores one SQLite row per embedding (videos contribute one row per sampled frame).
It is safe to call concurrently with searches: the database and FAISS index own
their own locks, and embedding is serialised inside the model wrapper.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np
from PIL import Image

import config
import thumbnail_generator as thumbs
import video_processor

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]

# Number of video frames embedded per batch (keeps RAM/VRAM bounded).
_VIDEO_CHUNK = 32
# Directories that are never descended into.
_SKIP_DIRS = {".git", ".cache", "node_modules", "__pycache__", ".venv", "venv"}


def _read_text(path: Path) -> str:
    """Read the beginning of a text file, tolerating encoding errors."""
    for encoding in ("utf-8", "latin-1"):
        try:
            with path.open("r", encoding=encoding, errors="strict") as handle:
                return handle.read(config.TEXT_MAX_CHARS)
        except (UnicodeDecodeError, OSError):
            continue
    try:
        with path.open("rb") as handle:
            return handle.read(config.TEXT_MAX_CHARS).decode("utf-8", errors="ignore")
    except OSError:
        return ""


class Indexer:
    """Indexes files into SQLite (metadata) and FAISS (vectors)."""

    def __init__(self, model, db, index, *, frame_interval: Optional[float] = None) -> None:
        self.model = model
        self.db = db
        self.index = index
        self.frame_interval = float(frame_interval or config.VIDEO_FRAME_INTERVAL)

    # -- classification ------------------------------------------------------
    def kind_of(self, path) -> Optional[str]:
        return config.classify_extension(Path(path).suffix)

    def is_supported(self, path) -> bool:
        kind = self.kind_of(path)
        return kind is not None and kind in config.ENABLED_MODALITIES

    # -- single file ---------------------------------------------------------
    def index_path(self, path: str | Path) -> int:
        """(Re)index a single file, replacing any previous entries."""
        key = str(Path(path))
        self.remove_path(key)
        target = Path(key)
        if not target.is_file() or not self.is_supported(target):
            return 0
        kind = self.kind_of(target)
        try:
            stat = target.stat()
        except OSError:
            return 0
        try:
            if kind == "text":
                return self._index_text(target, stat)
            if kind == "image":
                return self._index_image(target, stat)
            if kind == "video":
                return self._index_video(target, stat)
            if kind == "audio":
                return self._index_audio(target, stat)
        except Exception:
            log.exception("Failed to index %s", key)
        return 0

    def remove_path(self, path: str | Path) -> int:
        """Remove all rows/vectors/thumbnails belonging to a file."""
        rows = self.db.delete_by_path(str(Path(path)))
        if not rows:
            return 0
        self.index.remove([int(r["id"]) for r in rows])
        for row in rows:
            thumbs.delete_thumbnail(row.get("thumbnail"))
        return len(rows)

    # -- low-level storage ---------------------------------------------------
    def _add_rows(
        self,
        *,
        path: str,
        name: str,
        kind: str,
        size: int,
        mtime: float,
        duration: Optional[float],
        rows: list[tuple],
    ) -> int:
        if not rows:
            return 0
        vectors = np.stack([row[3] for row in rows]).astype("float32")
        ids: list[int] = []
        for timestamp, thumbnail, snippet, vector in rows:
            item_id = self.db.add_item(
                path=path, name=name, kind=kind, size=size, mtime=mtime,
                timestamp=timestamp, duration=duration, thumbnail=thumbnail,
                snippet=snippet, dim=int(vector.shape[0]), vector=vector.tobytes(),
            )
            ids.append(item_id)
        self.index.add(ids, vectors)
        return len(ids)

    # -- per-kind indexers ---------------------------------------------------
    def _index_text(self, path: Path, stat) -> int:
        text = _read_text(path)
        if not text.strip():
            return 0
        vector = self.model.encode_texts([text])[0]
        snippet = " ".join(text.split())[:400]
        return self._add_rows(
            path=str(path), name=path.name, kind="text",
            size=stat.st_size, mtime=stat.st_mtime, duration=None,
            rows=[(None, None, snippet, vector)],
        )

    def _index_image(self, path: Path, stat) -> int:
        if not self.model.supports("image"):
            return 0
        with Image.open(path) as handle:
            image = handle.convert("RGB")
            vector = self.model.encode_images([image])[0]
            thumbnail = thumbs.generate_thumbnail(image, str(path))
        return self._add_rows(
            path=str(path), name=path.name, kind="image",
            size=stat.st_size, mtime=stat.st_mtime, duration=None,
            rows=[(None, thumbnail, None, vector)],
        )

    def _index_audio(self, path: Path, stat) -> int:
        if not self.model.supports("audio"):
            return 0
        duration = video_processor.probe_audio_duration(str(path))
        vector = self.model.encode_audio([str(path)])[0]
        return self._add_rows(
            path=str(path), name=path.name, kind="audio",
            size=stat.st_size, mtime=stat.st_mtime, duration=duration,
            rows=[(None, None, None, vector)],
        )

    def _index_video(self, path: Path, stat) -> int:
        if not self.model.supports("video") and not self.model.supports("image"):
            return 0
        duration = (
            video_processor.probe_duration(str(path))
            or video_processor.probe_audio_duration(str(path))
        )
        total = 0
        images: list[Image.Image] = []
        timestamps: list[float] = []
        for frame in video_processor.iter_frames(str(path), self.frame_interval):
            images.append(frame.image)
            timestamps.append(frame.timestamp)
            if len(images) >= _VIDEO_CHUNK:
                total += self._flush_video_chunk(path, stat, duration, images, timestamps)
                images, timestamps = [], []
        total += self._flush_video_chunk(path, stat, duration, images, timestamps)
        log.debug("Indexed %d frames from %s", total, path.name)
        return total

    def _flush_video_chunk(self, path, stat, duration, images, timestamps) -> int:
        if not images:
            return 0
        vectors = self.model.encode_images(images)
        box = (config.THUMBNAIL_WIDTH, round(config.THUMBNAIL_WIDTH * 9 / 16))
        rows = []
        for image, timestamp, vector in zip(images, timestamps, vectors):
            thumbnail = thumbs.generate_thumbnail(
                image, str(path), timestamp=timestamp, size=box
            )
            rows.append((timestamp, thumbnail, None, vector))
        return self._add_rows(
            path=str(path), name=path.name, kind="video",
            size=stat.st_size, mtime=stat.st_mtime, duration=duration, rows=rows,
        )

    # -- directory walks -----------------------------------------------------
    def iter_supported_files(self, dirs: Iterable[str | Path]) -> Iterable[Path]:
        for root in dirs:
            root = Path(root)
            if not root.exists():
                log.debug("Watched directory does not exist: %s", root)
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames
                    if d not in _SKIP_DIRS and not d.startswith(".")
                ]
                for filename in filenames:
                    if filename.startswith("."):
                        continue
                    candidate = Path(dirpath) / filename
                    if self.is_supported(candidate):
                        yield candidate

    def index_dirs(
        self,
        dirs: Optional[Iterable[str | Path]] = None,
        *,
        force: bool = False,
        on_progress: Optional[ProgressCallback] = None,
    ) -> int:
        """Index every supported file under ``dirs`` (defaults to WATCH_DIRS)."""
        targets = [Path(d) for d in (dirs if dirs is not None else config.WATCH_DIRS)]
        files = list(self.iter_supported_files(targets))
        known = self.db.paths()
        total = len(files)
        added = 0

        for processed, path in enumerate(files, start=1):
            key = str(path)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            unchanged = key in known and abs(known[key] - mtime) < 1e-6
            if force or not unchanged:
                added += self.index_path(key)
            if on_progress and (processed % 5 == 0 or processed == total):
                on_progress(processed, total)

        # Drop entries whose files no longer exist on disk.
        for key in list(known.keys()):
            if not Path(key).exists():
                self.remove_path(key)

        self.index.save()
        if on_progress:
            on_progress(total, total)
        return added

    def reindex(
        self,
        *,
        full: bool = False,
        on_progress: Optional[ProgressCallback] = None,
    ) -> int:
        """Run a (full) reindex over the configured directories."""
        if full:
            log.info("Full reindex requested: clearing index, metadata and thumbnails")
            rows = self.db.clear()
            self.index.reset()
            for row in rows:
                thumbs.delete_thumbnail(row.get("thumbnail"))
            return self.index_dirs(config.WATCH_DIRS, force=True, on_progress=on_progress)
        return self.index_dirs(config.WATCH_DIRS, force=False, on_progress=on_progress)
