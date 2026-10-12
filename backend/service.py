"""D-Bus service entry point for the GNOME Embedding Search backend.

Publishes ``org.gnome.EmbeddingSearch`` on the session bus and keeps the model
loaded in VRAM. Layout:

* the GLib main loop serves D-Bus calls,
* a background thread loads the model and performs the initial index scan,
* the file watcher keeps the index fresh in real time.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from gi.repository import GLib
from pydbus import SessionBus
from pydbus.generic import signal

import numpy as np

import config
from db import Database
from indexer import Indexer
from model import EmbeddingModel
from searcher import FaissIndex, Searcher
from watcher import FileWatcher

log = logging.getLogger(__name__)

# The introspection XML doubles as the pydbus interface definition.
_IFACE_XML = (Path(__file__).with_name("dbus_interface.xml")).read_text(encoding="utf-8")


class EmbeddingSearchService:
    """Implementation of the ``org.gnome.EmbeddingSearch`` interface."""

    IndexingProgress = signal()
    IndexingComplete = signal()

    def __init__(self) -> None:
        config.ensure_dirs()
        self._status_lock = threading.Lock()
        self._indexing = False
        self._processed = 0
        self._total = 0
        self._ready = False
        self._error: str | None = None

        self.db = Database(config.DB_PATH)
        self.db.connect()
        self.model = EmbeddingModel()
        self.index = FaissIndex(config.EMBEDDING_DIM, config.INDEX_PATH)
        self.index.load()
        self.indexer = Indexer(self.model, self.db, self.index)
        self.searcher = Searcher(
            self.model, self.db, self.index,
            min_score=config.MIN_SCORE, max_results=config.MAX_RESULTS,
        )
        self.watcher: FileWatcher | None = None

    # -- D-Bus methods -------------------------------------------------------
    def Search(self, query: str, max_results: int) -> str:
        """Run a semantic search and return a JSON object ``{"results": [...]}``."""
        if not self._ready:
            return json.dumps({"results": [], "error": "model not ready"})
        try:
            results = self.searcher.search(query, int(max_results) or config.MAX_RESULTS)
        except Exception as exc:  # never let an exception cross the bus
            log.exception("Search failed for %r", query)
            return json.dumps({"results": [], "error": str(exc)})
        return json.dumps({"results": results}, ensure_ascii=False)

    def GetStatus(self) -> str:
        """Return service/state information as JSON."""
        with self._status_lock:
            indexing = self._indexing
            processed, total = self._processed, self._total
        status = {
            "ready": self._ready,
            "error": self._error,
            "model": config.MODEL_ID,
            "device": self.model.device,
            "dim": config.EMBEDDING_DIM,
            "modality": config.MODALITY,
            "indexed_items": self.db.count(),
            "indexed_files": len(self.db.paths()),
            "indexing": indexing,
            "processed": processed,
            "total": total,
            "watch_dirs": [str(d) for d in config.WATCH_DIRS],
        }
        return json.dumps(status, ensure_ascii=False)

    def Reindex(self, full: bool) -> None:
        """Kick off a (full) reindex on a background thread."""
        if self._indexing or not self._ready:
            return
        threading.Thread(
            target=self._run_index, kwargs={"full": bool(full)},
            name="embedding-reindex", daemon=True,
        ).start()

    # -- background work -----------------------------------------------------
    def start_background(self) -> None:
        """Load the model and index off the main loop, then start watching."""
        threading.Thread(target=self._bootstrap, name="embedding-bootstrap", daemon=True).start()

    def _bootstrap(self) -> None:
        try:
            self.model.load()
        except Exception as exc:
            log.exception("Failed to load the embedding model")
            self._error = str(exc)
            return

        # Rebuild the FAISS index from SQLite if it was lost or is out of sync.
        if self.index.ntotal < self.db.count():
            self._rebuild_index_from_db()

        self._ready = True
        self._run_index(full=False)

        self.watcher = FileWatcher(self.indexer)
        self.watcher.start()

    def _rebuild_index_from_db(self) -> None:
        log.info("Rebuilding FAISS index from metadata database")
        ids: list[int] = []
        vectors: list[np.ndarray] = []
        for item_id, _dim, blob in self.db.iter_vectors():
            ids.append(item_id)
            vectors.append(np.frombuffer(blob, dtype="float32"))
        self.index.reset()
        if vectors:
            self.index.add(ids, np.vstack(vectors))
            self.index.save()

    def _emit_indexing_progress(self, processed: int, total: int) -> None:
        with self._status_lock:
            self._processed, self._total = processed, total
        try:
            self.IndexingProgress(processed, total)
        except Exception:  # pragma: no cover - only if not registered yet
            log.debug("Could not emit IndexingProgress", exc_info=True)

    def _run_index(self, *, full: bool) -> None:
        with self._status_lock:
            if self._indexing:
                return
            self._indexing = True
            self._processed = self._total = 0
        log.info("Starting %s index", "full" if full else "incremental")
        try:
            added = self.indexer.reindex(full=full, on_progress=self._emit_indexing_progress)
            log.info("Index run finished (%d new items)", added)
        except Exception:
            log.exception("Indexing failed")
        finally:
            with self._status_lock:
                self._indexing = False
            try:
                self.IndexingComplete()
            except Exception:  # pragma: no cover
                log.debug("Could not emit IndexingComplete", exc_info=True)

    def shutdown(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
        self.index.save()
        self.db.close()


# pydbus reads the interface definition from the class docstring.
EmbeddingSearchService.__doc__ = _IFACE_XML


def main() -> None:
    config.setup_logging()
    log.info("Starting GNOME Embedding Search backend (%s)", config.DBUS_BUS_NAME)
    if config.DBUS_OBJECT_PATH != "/" + config.DBUS_BUS_NAME.replace(".", "/"):
        log.warning(
            "DBUS_OBJECT_PATH (%s) differs from the path derived from DBUS_BUS_NAME",
            config.DBUS_OBJECT_PATH,
        )

    service = EmbeddingSearchService()
    bus = SessionBus()
    bus.publish(config.DBUS_BUS_NAME, service)  # published at /org/gnome/EmbeddingSearch
    service.start_background()

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        service.shutdown()


if __name__ == "__main__":
    main()
