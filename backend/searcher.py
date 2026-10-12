"""FAISS-backed vector index and semantic search.

The index is an ``IndexIDMap2`` wrapping an ``IndexFlatIP`` (inner product).
Because all embeddings are L2-normalised before insertion, inner product equals
cosine similarity. Using an ``IDMap2`` lets us map every vector directly to its
SQLite ``items.id`` so deletions stay cheap.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

log = logging.getLogger(__name__)


class FaissIndex:
    """Thread-safe wrapper around a FAISS flat inner-product index."""

    def __init__(self, dim: int, path: str | Path) -> None:
        self.dim = int(dim)
        self.path = Path(path)
        self._lock = threading.RLock()
        self._index: Optional[faiss.Index] = None

    # -- lifecycle ------------------------------------------------------------
    def _empty(self) -> faiss.Index:
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))

    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                index = faiss.read_index(str(self.path))
                if index.d != self.dim:
                    log.warning(
                        "Stored index has dim %d but config wants %d; starting empty",
                        index.d, self.dim,
                    )
                    index = self._empty()
                self._index = index
            else:
                self._index = self._empty()
        log.info("FAISS index loaded (%d vectors, dim=%d)", self.ntotal, self.dim)

    def save(self) -> None:
        with self._lock:
            if self._index is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(self.path))

    # -- mutations ------------------------------------------------------------
    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        if len(ids) == 0:
            return
        with self._lock:
            self._index.add_with_ids(
                np.ascontiguousarray(vectors, dtype="float32"),
                np.asarray(ids, dtype="int64"),
            )

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._index.remove_ids(np.asarray(ids, dtype="int64"))

    def reset(self) -> None:
        with self._lock:
            self._index = self._empty()

    # -- queries --------------------------------------------------------------
    def search(self, vector: np.ndarray, k: int) -> tuple[list[int], list[float]]:
        with self._lock:
            if self._index is None or self._index.ntotal == 0 or k <= 0:
                return [], []
            k = min(k, self._index.ntotal)
            query = np.ascontiguousarray(vector, dtype="float32").reshape(1, -1)
            scores, ids = self._index.search(query, k)
        return [int(i) for i in ids[0] if i >= 0], [float(s) for s in scores[0]]

    @property
    def ntotal(self) -> int:
        return int(self._index.ntotal) if self._index is not None else 0


def format_timestamp(seconds: float | None) -> str | None:
    """Format ``42.5`` -> ``"0:42"`` and ``3725`` -> ``"1:02:05"``."""
    if seconds is None:
        return None
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class Searcher:
    """Encode a natural-language query and return ranked file results."""

    def __init__(self, model, db, index: FaissIndex, *, min_score: float, max_results: int) -> None:
        self.model = model
        self.db = db
        self.index = index
        self.min_score = float(min_score)
        self.max_results = int(max_results)

    def search(self, query: str, max_results: int | None = None) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        limit = int(max_results) if max_results else self.max_results
        vector = self.model.encode_query(query)
        if vector is None:
            return []

        # Over-fetch so duplicates (many frames of one video) can be collapsed.
        ids, scores = self.index.search(vector, limit * 6)
        results: list[dict] = []
        seen_paths: set[str] = set()
        for item_id, score in zip(ids, scores):
            if score < self.min_score:
                continue
            item = self.db.get_item(item_id)
            if item is None or item["path"] in seen_paths:
                continue
            seen_paths.add(item["path"])
            results.append(self._format(item, score))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _format(item: dict, score: float) -> dict:
        kind = item["kind"]
        timestamp = item.get("timestamp")
        duration = item.get("duration")
        ts_text = format_timestamp(timestamp)
        dur_text = format_timestamp(duration)

        if kind == "video":
            description = "Video"
            if dur_text:
                description += f" • {dur_text}"
            if ts_text:
                description += f" • frame at {ts_text}"
        elif kind == "audio":
            description = f"Audio • {dur_text}" if dur_text else "Audio"
            if ts_text and timestamp:
                description += f" • at {ts_text}"
        elif kind == "image":
            description = "Image"
        else:
            snippet = (item.get("snippet") or "").strip().replace("\n", " ")
            description = snippet[:120] if snippet else "Document"

        return {
            "id": str(item["id"]),
            "kind": kind,
            "path": item["path"],
            "name": item["name"],
            "score": round(float(score), 4),
            "timestamp": timestamp,
            "duration": duration,
            "thumbnail": item.get("thumbnail"),
            "snippet": item.get("snippet"),
            "description": description,
            "path_display": _pretty_path(item["path"]),
        }


def _pretty_path(path: str) -> str:
    """Replace the home directory with ``~`` for display."""
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path
