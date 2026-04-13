
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover
    SentenceTransformer = None

from app.config import settings

_MODEL = None


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vec)) or 1.0
    return [value / norm for value in vec]


def _hashed_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode('utf-8')).digest()
        slot = int.from_bytes(digest[:4], 'big') % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[slot] += sign
    return _normalize(vector)


def _get_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    if settings.embedding_provider != 'local' or SentenceTransformer is None:
        return None
    try:
        _MODEL = SentenceTransformer(settings.embedding_model)
    except Exception:
        _MODEL = None
    return _MODEL


def embed_text(text: str) -> dict[str, Any]:
    clean = (text or '').strip()
    dimensions = settings.embedding_dimensions
    model = _get_model()
    if model is not None:
        try:
            vector = model.encode(clean, normalize_embeddings=True).tolist()
            return {
                'provider': settings.embedding_provider,
                'model': settings.embedding_model,
                'backend': 'sentence-transformers',
                'dimensions': len(vector),
                'vector': vector,
            }
        except Exception:
            pass
    vector = _hashed_embedding(clean, dimensions)
    return {
        'provider': settings.embedding_provider,
        'model': settings.embedding_model,
        'backend': 'hashed-local',
        'dimensions': dimensions,
        'vector': vector,
    }


def embedding_status() -> dict[str, Any]:
    model = _get_model()
    return {
        'provider': settings.embedding_provider,
        'model': settings.embedding_model,
        'dimensions': settings.embedding_dimensions,
        'backend': 'sentence-transformers' if model is not None else 'hashed-local',
        'ready': True,
    }
