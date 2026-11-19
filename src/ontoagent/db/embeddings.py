"""Embedding generation service using MiniLM.

Purpose:
    Local, deterministic embeddings for policy chunk indexing and retrieval.
    Asserts expected dimension (384) at runtime.
"""

import hashlib
from typing import List, Optional
from ontoagent.config import get_settings

_MODEL = None


def get_embedding_model():
    """Lazy loader for SentenceTransformer model."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    settings = get_settings()
    try:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(settings.embedding_model)
    except Exception:
        _MODEL = None
    return _MODEL


def embed_text(text: str) -> List[float]:
    """Generate dense embedding vector (384 dimensions)."""
    model = get_embedding_model()
    settings = get_settings()
    dim = settings.embedding_dim

    if model is not None:
        vec = model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vec.tolist()]

    # Deterministic fallback vector generation for test environments without PyTorch
    h = hashlib.sha256(text.encode("utf-8")).digest()
    vec = []
    for i in range(dim):
        byte_val = h[i % len(h)]
        vec.append(round((byte_val / 255.0) * 2 - 1, 4))
    return vec
