"""EmbeddingGemma 2 wrapper built on top of ``sentence-transformers``.

The model maps text, images, video frames and audio into a single shared
768-dimensional space. We use the prompt-aware ``encode_query`` /
``encode_document`` helpers so the model's task instruction prefixes are applied
automatically, and we truncate embeddings with Matryoshka MRL to save storage.

.. warning::
   ``torch.float16`` produces NaNs with this model. Use ``float32`` (default) or
   ``bfloat16`` (Ampere or newer GPUs).
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable, Sequence

import numpy as np

import config

log = logging.getLogger(__name__)


class EmbeddingModel:
    """Lazy-loading, thread-safe wrapper around the EmbeddingGemma 2 model."""

    def __init__(
        self,
        *,
        model_id: str | None = None,
        device: str | None = None,
        dtype: str | None = None,
        dim: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.model_id = model_id or config.MODEL_ID
        self.device = device or config.DEVICE
        self.dtype = (dtype or config.TORCH_DTYPE).lower()
        self.dim = int(dim or config.EMBEDDING_DIM)
        self.batch_size = int(batch_size or config.BATCH_SIZE)
        self._model = None
        self._encode_lock = threading.Lock()

    # -- loading --------------------------------------------------------------
    def load(self) -> None:
        import torch  # imported here so the module stays importable without torch
        from sentence_transformers import SentenceTransformer

        model_kwargs = {"dtype": self._torch_dtype(torch)}
        try:
            self._model = SentenceTransformer(
                self.model_id, device=self.device, model_kwargs=model_kwargs
            )
        except TypeError:
            # Older transformers builds still expect ``torch_dtype``.
            model_kwargs = {"torch_dtype": self._torch_dtype(torch)}
            self._model = SentenceTransformer(
                self.model_id, device=self.device, model_kwargs=model_kwargs
            )
        except Exception as exc:  # pragma: no cover - hardware dependent
            if self.device.startswith("cuda"):
                log.warning("GPU load failed (%s); falling back to CPU", exc)
                self.device = "cpu"
                self._model = SentenceTransformer(self.model_id, device="cpu")
            else:
                raise

        log.info(
            "Loaded %s on %s (dtype=%s, dim=%d, modalities=%s)",
            self.model_id, self.device, self.dtype, self.dim, self.modalities,
        )

    def _torch_dtype(self, torch):
        if self.dtype in {"bfloat16", "bf16"}:
            return torch.bfloat16
        if self.dtype in {"float16", "fp16", "half"}:
            log.warning("float16 is unsupported by this model; using float32 instead")
        return torch.float32

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def modalities(self) -> list[str]:
        if self._model is not None:
            try:
                return list(self._model.modalities)
            except Exception:
                pass
        return ["text", "image", "video", "audio"]

    def supports(self, modality: str) -> bool:
        modality = modality.lower()
        if self._model is not None:
            try:
                return bool(self._model.supports(modality))
            except Exception:
                pass
        return modality in config.ENABLED_MODALITIES

    # -- encoding helpers -----------------------------------------------------
    def _encode(self, inputs, *, query: bool = False, document: bool = False) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("model is not loaded")
        if isinstance(inputs, (str, dict)):
            inputs = [inputs]
        inputs = list(inputs)
        if not inputs:
            return np.zeros((0, self.dim), dtype="float32")

        kwargs = dict(
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            truncate_dim=self.dim,
            normalize_embeddings=True,
        )
        with self._encode_lock:
            if query:
                embeddings = self._model.encode_query(inputs, **kwargs)
            elif document:
                embeddings = self._model.encode_document(inputs, **kwargs)
            else:
                embeddings = self._model.encode(inputs, **kwargs)

        embeddings = np.atleast_2d(np.asarray(embeddings, dtype="float32"))
        return _l2_normalize(embeddings)

    def encode_query(self, text: str) -> np.ndarray | None:
        """Encode a single search query (applies the model's query prompt)."""
        text = (text or "").strip()
        if not text:
            return None
        return self._encode(text, query=True)[0]

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Encode text documents (applies the model's document prompt)."""
        return self._encode(list(texts), document=True)

    def encode_images(self, images: Iterable) -> np.ndarray:
        """Encode images given as file paths or PIL images."""
        return self._encode([{"image": item} for item in images])

    def encode_audio(self, paths: Sequence[str]) -> np.ndarray:
        """Encode audio files given as paths."""
        return self._encode([{"audio": str(p)} for p in paths])

    def encode_video(self, paths: Sequence[str]) -> np.ndarray:
        """Encode video files given as paths (the processor samples frames)."""
        return self._encode([{"video": str(p)} for p in paths])


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype("float32")
