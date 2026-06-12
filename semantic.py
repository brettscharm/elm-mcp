"""Local semantic search for ELM artifacts — air-gap safe.

Powers `find_similar_requirements` and the semantic ranking in
`query_elm`. Uses fastembed (ONNX-based, ~50 MB — NOT the 2 GB torch
stack) so it stays light AND runs fully locally: requirement text never
leaves the machine. Critical for regulated / defense customers.

fastembed is an OPTIONAL dependency. If it isn't installed, every entry
point here degrades gracefully (returns available=False with a clear
install hint) so the core MCP install stays dead-simple.

The model downloads once on first use (BAAI/bge-small-en-v1.5, ~130 MB
ONNX) and is cached by fastembed under the user's cache dir. In a true
air-gap deployment, pre-stage that cache; everything after is offline.

Embeddings are cached on disk per text hash so re-querying a module
doesn't re-embed unchanged requirements.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_CACHE_DIR = Path.home() / ".elm-mcp" / "embeddings"
_MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384-dim, fast, good quality

# Lazily-instantiated singleton model (loading is expensive)
_MODEL = None
_MODEL_TRIED = False


def is_available() -> bool:
    """True if fastembed is importable."""
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    """Lazy-load the embedding model once per process."""
    global _MODEL, _MODEL_TRIED
    if _MODEL is not None:
        return _MODEL
    if _MODEL_TRIED:
        return None
    _MODEL_TRIED = True
    try:
        from fastembed import TextEmbedding
        _MODEL = TextEmbedding(model_name=_MODEL_NAME)
        return _MODEL
    except Exception:
        return None


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cache_path(text: str) -> Path:
    return _CACHE_DIR / f"{_hash(text)}.json"


def _load_cached(text: str) -> Optional[List[float]]:
    p = _cache_path(text)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _save_cached(text: str, vec: List[float]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(text).write_text(json.dumps(vec))
    except Exception:
        pass


def embed(texts: List[str], use_cache: bool = True) -> Optional[List[List[float]]]:
    """Embed a list of texts. Returns one vector per text, or None if
    fastembed isn't available. Uses the on-disk cache to skip texts
    already embedded."""
    model = _get_model()
    if model is None:
        return None

    vectors: List[Optional[List[float]]] = [None] * len(texts)
    to_embed: List[Tuple[int, str]] = []

    for i, t in enumerate(texts):
        clean = (t or "").strip()
        if not clean:
            vectors[i] = []
            continue
        if use_cache:
            cached = _load_cached(clean)
            if cached is not None:
                vectors[i] = cached
                continue
        to_embed.append((i, clean))

    if to_embed:
        try:
            raw = list(model.embed([t for _, t in to_embed]))
        except Exception:
            return None
        for (idx, clean), vec in zip(to_embed, raw):
            v = [float(x) for x in vec]
            vectors[idx] = v
            if use_cache:
                _save_cached(clean, v)

    return [v if v is not None else [] for v in vectors]


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def rank_by_similarity(
    query_text: str,
    candidates: List[Dict[str, Any]],
    text_key: str = "title",
    top_k: int = 10,
    min_score: float = 0.0,
) -> Optional[List[Dict[str, Any]]]:
    """Rank candidate artifacts by semantic similarity to query_text.

    Each candidate dict gets a `_score` (0..1 cosine). Returns the top_k
    above min_score, or None if embeddings aren't available.
    """
    if not query_text or not candidates:
        return [] if candidates is not None else None

    texts = [str(c.get(text_key) or c.get("title") or "") for c in candidates]
    all_vecs = embed([query_text] + texts)
    if all_vecs is None:
        return None

    qvec = all_vecs[0]
    scored = []
    for c, vec in zip(candidates, all_vecs[1:]):
        s = _cosine(qvec, vec)
        if s >= min_score:
            item = dict(c)
            item["_score"] = round(s, 4)
            scored.append(item)
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:top_k]


def install_hint() -> str:
    return ("Semantic search needs the optional `fastembed` package "
            "(lightweight, ONNX-based, air-gap safe — no data leaves your "
            "machine). Install it with: `pip install fastembed` "
            "(or `python3 ~/.elm-mcp/setup.py --with-semantic`), then "
            "retry. The model downloads once (~130 MB) and runs offline "
            "after that.")
