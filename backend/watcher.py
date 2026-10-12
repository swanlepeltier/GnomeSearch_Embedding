"""Real-time file watching.

Uses ``watchdog`` (inotify on Linux) to notice created/modified/deleted files and
feeds them to the indexer. Events are debounced so that a burst of writes to a
single file results in one re-index.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config

log = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, on_event) -> None:
        self._on_event = on_event

    def on_created(self, event):
        if not event.is_directory:
            self._on_event(event.src_path, "modified")

    def on_modified(self, event):
        if not event.is_directory:
            self._on_event(event.src_path, "modified")

    def on_deleted(self, event):
        if not event.is_directory:
            self._on_event(event.src_path, "deleted")

    def on_moved(self, event):
        if event.is_directory:
            return
        self._on_event(event.src_path, "deleted")
        self._on_event(event.dest_path, "modified")


class FileWatcher:
    """Watch the configured directories and keep the index up to date."""

    def __init__(self, indexer, *, debounce: float = 0.5) -> None:
        self.indexer = indexer
        self.debounce = float(debounce)
        self._pending: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._observer: Optional[Observer] = None

    def start(self, dirs=None) -> None:
        self._observer = Observer()
        handler = _Handler(self._on_event)
        for directory in (dirs if dirs is not None else config.WATCH_DIRS):
            path = Path(directory)
            if path.exists():
                self._observer.schedule(handler, str(path), recursive=True)
                log.info("Watching %s", path)
        self._observer.start()
        self._thread = threading.Thread(
            target=self._worker, name="embedding-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _on_event(self, path: str, kind: str) -> None:
        if not self.indexer.is_supported(path):
            return
        with self._lock:
            self._pending[path] = (kind, time.time())

    def _worker(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.25)
            now = time.time()
            batch: list[tuple[str, str]] = []
            with self._lock:
                for path, (kind, queued_at) in list(self._pending.items()):
                    if now - queued_at >= self.debounce:
                        batch.append((path, kind))
                        del self._pending[path]
            for path, kind in batch:
                try:
                    if kind == "deleted" or not Path(path).exists():
                        self.indexer.remove_path(path)
                    else:
                        self.indexer.index_path(path)
                    self.indexer.index.save()
                except Exception:
                    log.exception("Watcher failed to process %s", path)
