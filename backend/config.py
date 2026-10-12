"""Central configuration for the GNOME Embedding Search backend.

Configuration is read from environment variables, typically provided by a
``.env`` file at the project root. See ``.env.example`` for every option and
its default value.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the directory that contains ``backend/`` and ``extension/``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from the project root. ``override=False`` keeps variables that were
# already exported in the environment (handy for the systemd unit and tests).
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _get(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _expand(value: str) -> Path:
    """Expand ``~`` / ``$VARS`` and return an absolute :class:`Path`."""
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


def _get_list(name: str, default: str) -> list[str]:
    return [part.strip() for part in _get(name, default).split(",") if part.strip()]


def _get_exts(name: str, default: str) -> frozenset[str]:
    return frozenset(
        part.strip().lower() if part.strip().startswith(".") else f".{part.strip().lower()}"
        for part in _get(name, default).split(",")
        if part.strip()
    )


# --- GPU / device ------------------------------------------------------------
# CUDA device index to dedicate to the embedding model. -1 forces CPU-only mode.
CUDA_DEVICE_INDEX = _get_int("CUDA_DEVICE_INDEX", 0)
# torch dtype used for inference. ``float16`` must never be used (NaNs).
TORCH_DTYPE = _get("TORCH_DTYPE", "float32").strip().lower()

# Restrict the process to a single GPU before torch is ever imported so that the
# configured device always shows up as ``cuda:0`` inside the backend.
if CUDA_DEVICE_INDEX >= 0:
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(CUDA_DEVICE_INDEX))
DEVICE = "cuda:0" if CUDA_DEVICE_INDEX >= 0 else "cpu"

# --- Model -------------------------------------------------------------------
MODEL_ID = _get("MODEL_ID", "google/embeddinggemma-2")
# Matryoshka truncation dimension: 128, 256, 512 or 768.
EMBEDDING_DIM = _get_int("EMBEDDING_DIM", 256)
# text_only | text_vision | text_audio | multimodal
MODALITY = _get("MODALITY", "multimodal").strip().lower()
BATCH_SIZE = _get_int("BATCH_SIZE", 16)

# Modalities that get indexed. Queries are always text.
MODALITIES_BY_NAME: dict[str, frozenset[str]] = {
    "text_only": frozenset({"text"}),
    "text_vision": frozenset({"text", "image", "video"}),
    "text_audio": frozenset({"text", "audio"}),
    "multimodal": frozenset({"text", "image", "video", "audio"}),
}
ENABLED_MODALITIES = MODALITIES_BY_NAME.get(MODALITY, MODALITIES_BY_NAME["multimodal"])

# --- Indexing -----------------------------------------------------------------
WATCH_DIRS = [_expand(p) for p in _get_list("WATCH_DIRS", "~/Documents,~/Pictures,~/Videos")]
DATA_DIR = _expand(_get("DATA_DIR", str(PROJECT_ROOT / "data")))
INDEX_DIR = DATA_DIR / "index"
INDEX_PATH = INDEX_DIR / "index.faiss"
DB_PATH = DATA_DIR / "metadata.db"
THUMBNAIL_DIR = DATA_DIR / "thumbnails"

VIDEO_FRAME_INTERVAL = _get_float("VIDEO_FRAME_INTERVAL", 3.0)
THUMBNAIL_WIDTH = _get_int("THUMBNAIL_WIDTH", 320)
# Maximum number of characters read from a text document before embedding.
TEXT_MAX_CHARS = _get_int("TEXT_MAX_CHARS", 8000)

VIDEO_EXTENSIONS = _get_exts("VIDEO_EXTENSIONS", ".mp4,.mkv,.avi,.webm,.mov,.flv,.wmv")
IMAGE_EXTENSIONS = _get_exts("IMAGE_EXTENSIONS", ".jpg,.jpeg,.png,.webp,.bmp,.gif,.tiff")
AUDIO_EXTENSIONS = _get_exts("AUDIO_EXTENSIONS", ".mp3,.flac,.wav,.ogg,.m4a,.aac")
TEXT_EXTENSIONS = _get_exts(
    "TEXT_EXTENSIONS",
    ".txt,.md,.py,.js,.ts,.rs,.c,.cpp,.h,.json,.yaml,.yml,.toml,.csv,.xml,.html",
)

# --- D-Bus --------------------------------------------------------------------
DBUS_BUS_NAME = _get("DBUS_BUS_NAME", "org.gnome.EmbeddingSearch")
DBUS_OBJECT_PATH = _get("DBUS_OBJECT_PATH", "/org/gnome/EmbeddingSearch")

# --- Search -------------------------------------------------------------------
MAX_RESULTS = _get_int("MAX_RESULTS", 8)
MIN_SCORE = _get_float("MIN_SCORE", 0.15)

# --- Logging ------------------------------------------------------------------
LOG_LEVEL = _get("LOG_LEVEL", "INFO").strip().upper()


def ensure_dirs() -> None:
    """Create the runtime data directories if they do not exist yet."""
    for directory in (DATA_DIR, INDEX_DIR, THUMBNAIL_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Quiet libraries that otherwise log every HTTP request / file lock at INFO.
    for name in ("httpx", "httpcore", "urllib3", "filelock", "fsspec", "PIL"):
        logging.getLogger(name).setLevel(logging.WARNING)


def classify_extension(suffix: str) -> str | None:
    """Return the media kind for a file suffix (``.mp4`` -> ``video``)."""
    suffix = suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    return None
