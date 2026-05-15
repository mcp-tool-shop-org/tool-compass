"""A deterministic, reproducible embedder for the golden-set benchmark.

The real production embedder talks to Ollama and produces dense semantic
vectors. We cannot run that in CI without an Ollama dependency, AND we want
the golden-set benchmark to be reproducible byte-for-byte across machines.

Strategy: build a tiny "concept vocabulary" — a fixed set of intent tokens
(read, write, delete, git, commit, push, search, image, audio, summarize,
sql, http, etc.) — and assign each concept a fixed orthogonal basis vector
in a 768-dim space (matching production EMBEDDING_DIM).

To embed a tool: tokenize its description + examples, collect the concept
tokens that appear, and the resulting vector is the L2-normalized sum of the
concept basis vectors.

To embed a query: same procedure on the query text.

Cosine similarity between the query vector and a tool vector then reflects
overlap in concept tokens. Adding more shared concept tokens raises the
score, which is the property a real semantic search retains. The benchmark
will catch regressions like "queries are no longer being tokenized" or
"normalization was dropped" — exactly the kinds of regressions that example-
based tests miss.

This is NOT a substitute for a real ML benchmark against Ollama. It is a
reproducible REGRESSION TEST — small enough to run on every PR, deterministic
enough to fail loudly on any retrieval-pipeline change.
"""

from __future__ import annotations

import re
from typing import Iterable
from unittest.mock import AsyncMock

import numpy as np


# Fixed concept vocabulary. Each token maps to a one-hot dimension; the
# embedding is the L2-normalized sum of one-hot vectors for the concept
# tokens that appear in the text.
_CONCEPTS: tuple[str, ...] = (
    # File concepts
    "file",
    "read",
    "write",
    "open",
    "view",
    "load",
    "save",
    "content",
    "create",
    "delete",
    "remove",
    "list",
    "directory",
    "folder",
    "disk",
    "document",
    # Git concepts
    "git",
    "status",
    "tree",
    "working",
    "changes",
    "commit",
    "message",
    "push",
    "upload",
    "publish",
    "remote",
    "pull",
    "fetch",
    "upstream",
    "sync",
    "repository",
    "branch",
    # Search concepts
    "search",
    "grep",
    "find",
    "locate",
    "pattern",
    "codebase",
    "docs",
    "documentation",
    "lookup",
    # AI concepts
    "ai",
    "generate",
    "image",
    "artwork",
    "prompt",
    "audio",
    "transcribe",
    "speech",
    "text",
    "summarize",
    "summary",
    "tldr",
    # Database concepts
    "sql",
    "query",
    "execute",
    "database",
    "insert",
    "row",
    "record",
    "table",
    # HTTP concepts
    "http",
    "request",
    "api",
    "call",
    "url",
    "download",
    "page",
    "web",
)

_CONCEPT_INDEX: dict[str, int] = {tok: i for i, tok in enumerate(_CONCEPTS)}

# Production EMBEDDING_DIM (matches indexer.py / embedder.py); the test
# embedder lives in this dimension so the HNSW index sized for production
# vectors accepts these vectors without reshaping.
EMBEDDING_DIM = 768

# Map each concept to a small random offset in the 768-dim space so the
# resulting vectors aren't perfectly orthogonal one-hot — they have a tiny
# amount of "noise" that better mirrors a real embedding distribution
# without breaking determinism (seed is fixed).
_RNG = np.random.default_rng(seed=4242)
_CONCEPT_BASIS: np.ndarray = _RNG.standard_normal(
    (len(_CONCEPTS), EMBEDDING_DIM)
).astype(np.float32)
# Normalize each row so summing isn't biased toward larger random vectors.
_CONCEPT_BASIS = _CONCEPT_BASIS / np.linalg.norm(
    _CONCEPT_BASIS, axis=1, keepdims=True
)

_WORD_RE = re.compile(r"[a-zA-Z]+")


def _tokens(text: str) -> Iterable[str]:
    """Lowercase word-level tokens; skips non-concept tokens at lookup time."""
    return (m.group(0).lower() for m in _WORD_RE.finditer(text))


def embed_text(text: str) -> np.ndarray:
    """Return a deterministic 768-dim L2-normalized vector for `text`.

    Sums the basis vectors of concept tokens that appear in `text`. If no
    concept token is present, returns a fixed fallback vector (the basis of
    the first concept) so the vector is never zero — hnswlib's cosine space
    cannot handle a zero vector.
    """
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    matched = 0
    for tok in _tokens(text):
        idx = _CONCEPT_INDEX.get(tok)
        if idx is not None:
            vec += _CONCEPT_BASIS[idx]
            matched += 1
    if matched == 0:
        # Never return a zero vector — hnswlib cosine space treats zero as
        # NaN. Use a deterministic fallback (basis[0]).
        vec = _CONCEPT_BASIS[0].copy()
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32)


def build_deterministic_embedder():
    """Build a unittest.mock-style embedder whose async methods route through
    embed_text(). The returned object has the same surface as the real
    embedder (embed / embed_batch / embed_query / health_check / close)
    plus the base_url and model attributes used by cache keying.
    """
    embedder = AsyncMock()

    async def _embed(text: str, **_kwargs) -> np.ndarray:
        return embed_text(text)

    async def _embed_batch(texts: list[str], **_kwargs) -> np.ndarray:
        return np.array([embed_text(t) for t in texts])

    async def _embed_query(query: str, **_kwargs) -> np.ndarray:
        # Production prepends `search_query:` for some embedders; we use the
        # raw query so the same token set drives tools and queries.
        return embed_text(query)

    async def _health_check() -> bool:
        return True

    embedder.embed = AsyncMock(side_effect=_embed)
    embedder.embed_batch = AsyncMock(side_effect=_embed_batch)
    embedder.embed_query = AsyncMock(side_effect=_embed_query)
    embedder.health_check = AsyncMock(side_effect=_health_check)
    embedder.close = AsyncMock()
    embedder.base_url = "deterministic://golden-set"
    embedder.model = "concept-basis-v1"
    return embedder
