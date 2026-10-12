"""SQLite metadata store for indexed files.

Each indexed embedding lives in one row of the ``items`` table. Text documents
produce a single row, images a single row, and videos/audio one row *per*
sampled frame/segment (with a ``timestamp``). Vectors are stored as raw
little-endian float32 blobs so the FAISS index can be rebuilt from the database.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Iterator, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    size        INTEGER,
    mtime       REAL,
    timestamp   REAL,
    duration    REAL,
    thumbnail   TEXT,
    snippet     TEXT,
    dim         INTEGER NOT NULL,
    vector      BLOB    NOT NULL,
    indexed_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_path ON items(path);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_LIGHT_COLUMNS = (
    "id, path, name, kind, size, mtime, timestamp, duration, thumbnail, snippet, dim"
)


class Database:
    """Thread-safe SQLite wrapper (a single connection guarded by a lock)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._con: Optional[sqlite3.Connection] = None

    # -- lifecycle ------------------------------------------------------------
    def connect(self) -> None:
        with self._lock:
            if self._con is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(str(self.path), check_same_thread=False)
            self._con.row_factory = sqlite3.Row
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.executescript(_SCHEMA)
            self._con.commit()

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.commit()
                self._con.close()
                self._con = None

    # -- metadata -------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            self._con.commit()

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def clear_meta(self, key: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM meta WHERE key=?", (key,))
            self._con.commit()

    # -- writes ---------------------------------------------------------------
    def add_item(
        self,
        *,
        path: str,
        name: str,
        kind: str,
        size: int,
        mtime: float,
        timestamp: Optional[float],
        duration: Optional[float],
        thumbnail: Optional[str],
        snippet: Optional[str],
        dim: int,
        vector: bytes,
    ) -> int:
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO items"
                " (path, name, kind, size, mtime, timestamp, duration, thumbnail,"
                "  snippet, dim, vector, indexed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    path, name, kind, size, mtime, timestamp, duration,
                    thumbnail, snippet, dim, vector, time.time(),
                ),
            )
            self._con.commit()
            return int(cur.lastrowid)

    def delete_by_path(self, path: str) -> list[dict]:
        """Delete every row for ``path`` and return the removed rows."""
        with self._lock:
            rows = self._con.execute(
                f"SELECT {_LIGHT_COLUMNS} FROM items WHERE path=?", (path,)
            ).fetchall()
            if rows:
                self._con.execute("DELETE FROM items WHERE path=?", (path,))
                self._con.commit()
        return [dict(r) for r in rows]

    def clear(self) -> list[dict]:
        """Remove every row and return them (used before a full rebuild)."""
        with self._lock:
            rows = self._con.execute(f"SELECT {_LIGHT_COLUMNS} FROM items").fetchall()
            self._con.execute("DELETE FROM items")
            self._con.commit()
        return [dict(r) for r in rows]

    # -- reads ----------------------------------------------------------------
    def count(self) -> int:
        with self._lock:
            return int(self._con.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"])

    def get_item(self, item_id: int) -> Optional[dict]:
        with self._lock:
            row = self._con.execute(
                f"SELECT {_LIGHT_COLUMNS} FROM items WHERE id=?", (item_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_items(self, ids: Iterable[int]) -> list[dict]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            rows = self._con.execute(
                f"SELECT {_LIGHT_COLUMNS} FROM items WHERE id IN ({placeholders})", ids
            ).fetchall()
        by_id = {int(r["id"]): dict(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def all_items(self) -> list[dict]:
        with self._lock:
            rows = self._con.execute(f"SELECT {_LIGHT_COLUMNS} FROM items").fetchall()
        return [dict(r) for r in rows]

    def iter_vectors(self) -> Iterator[tuple[int, int, bytes]]:
        """Yield ``(id, dim, vector_bytes)`` for every stored item."""
        with self._lock:
            rows = self._con.execute("SELECT id, dim, vector FROM items").fetchall()
        for row in rows:
            yield int(row["id"]), int(row["dim"]), row["vector"]

    def paths(self) -> dict[str, float]:
        """Return a ``{path: mtime}`` mapping of every indexed file."""
        with self._lock:
            rows = self._con.execute("SELECT path, mtime FROM items").fetchall()
        return {r["path"]: r["mtime"] for r in rows}
