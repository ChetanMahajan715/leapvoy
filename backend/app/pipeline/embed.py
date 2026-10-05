"""Stage 2 helper: local embeddings (no API cost). bge-small-en-v1.5 via fastembed (ONNX, no PyTorch)."""

from functools import lru_cache

import numpy as np
from fastembed import TextEmbedding

from app.core.config import ROOT_ENV

MODEL = "BAAI/bge-small-en-v1.5"
LIB = "fastembed"  # stored next to each vector; a MODEL/LIB change triggers re-embedding
CACHE_DIR = ROOT_ENV.parent / ".cache" / "models"


@lru_cache
def _model() -> TextEmbedding:
    return TextEmbedding(MODEL, cache_dir=str(CACHE_DIR))


def embed(texts: list[str]) -> list[list[float]]:
    """Unit-length vectors, so dot product = cosine similarity."""
    vectors = np.array(list(_model().embed(texts)), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors.tolist()
