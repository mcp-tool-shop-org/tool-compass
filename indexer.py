"""
Tool Compass - Indexer Module
Builds and manages the HNSW index for semantic tool discovery.
"""

import sqlite3
import json
import asyncio
import hashlib
import os
import threading
import numpy as np
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from typing import List, Dict, Optional, Sequence
from dataclasses import dataclass
import logging
import time

from embedder import Embedder, EMBEDDING_DIM
from tool_manifest import ToolDefinition, get_all_tools

logger = logging.getLogger(__name__)

# F-5b5841c7: never hard-crash at import if hnswlib is missing (Python 3.13
# cp313 wheel SIGILL / no wheel). Lazy factory below picks numpy instead.
try:
    import hnswlib
except ImportError:
    hnswlib = None

# Brute-force numpy backend is intended for catalogs at or under this size.
_NUMPY_VECTOR_ADVISED_MAX = 2000
DEFAULT_VECTOR_BACKEND = "hnswlib"


def _try_import_hnswlib():
    """Return the hnswlib module or None. Import is cached by the interpreter."""
    if hnswlib is not None:
        return hnswlib
    try:
        import hnswlib as _hnsw
        return _hnsw
    except ImportError:
        return None


def _sqlite_vec_available() -> bool:
    try:
        import sqlite_vec  # noqa: F401
        return True
    except ImportError:
        return False


class VectorStore(ABC):
    """Pluggable nearest-neighbor backend (IDX-FT-001 / F-5b5841c7).

    Duck-typed to the hnswlib.Index methods CompassIndex already calls
    (init_index, set_ef, add_items, knn_query, mark_deleted, save_index,
    load_index, get_current_count, get_max_elements, resize_index, ef).
    """

    name: str = "base"

    @abstractmethod
    def add_items(self, data, ids, replace_deleted: bool = False) -> None:
        raise NotImplementedError

    @abstractmethod
    def knn_query(self, data, k: int = 1):
        raise NotImplementedError

    @abstractmethod
    def mark_deleted(self, label: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_index(self, path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_index(
        self, path: str, max_elements: int = 0, allow_replace_deleted: bool = False
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError

    def get_current_count(self) -> int:
        return self.count()

    def get_items(self, ids: Sequence[int]):
        raise RuntimeError(f"{self.name} backend does not support get_items")


class HnswlibVectorStore(VectorStore):
    """Default backend: thin wrapper around hnswlib.Index."""

    name = "hnswlib"

    def __init__(self, dim: int, space: str = "cosine"):
        mod = _try_import_hnswlib()
        if mod is None:
            raise RuntimeError("hnswlib is not installed")
        # Look up Index at construction time so tests that patch
        # hnswlib.Index still intercept the native class.
        self._index = mod.Index(space=space, dim=dim)
        self.dim = dim
        self.space = space

    def init_index(self, **kwargs) -> None:
        self._index.init_index(**kwargs)

    def set_ef(self, ef: int) -> None:
        self._index.set_ef(ef)

    def add_items(self, data, ids, replace_deleted: bool = False) -> None:
        if replace_deleted:
            self._index.add_items(data, ids, replace_deleted=True)
        else:
            self._index.add_items(data, ids)

    def knn_query(self, data, k: int = 1):
        return self._index.knn_query(data, k=k)

    def mark_deleted(self, label: int) -> None:
        self._index.mark_deleted(int(label))

    def save_index(self, path: str) -> None:
        self._index.save_index(path)

    def load_index(
        self, path: str, max_elements: int = 0, allow_replace_deleted: bool = False
    ) -> None:
        self._index.load_index(
            path, max_elements=max_elements, allow_replace_deleted=allow_replace_deleted
        )

    def count(self) -> int:
        return int(self._index.get_current_count())

    def get_items(self, ids: Sequence[int]):
        return self._index.get_items(ids)

    def __getattr__(self, name):
        return getattr(self._index, name)


class NumpyVectorStore(VectorStore):
    """Pure-Python cosine brute-force fallback for <=~2k tools.

    Used when hnswlib is missing (e.g. Python 3.13) so indexer.py still
    imports and search still works.
    """

    name = "numpy"

    def __init__(self, dim: int, space: str = "cosine"):
        if space not in ("cosine", "ip", "l2"):
            raise ValueError(f"unsupported space {space!r}")
        self.dim = int(dim)
        self.space = space
        self._vectors: Dict[int, np.ndarray] = {}
        self._deleted: set = set()
        self._max_elements = 1000
        self._ef = 50
        self.M = 16
        self.ef_construction = 200

    def init_index(
        self,
        max_elements: int = 1000,
        ef_construction: int = 200,
        M: int = 16,
        allow_replace_deleted: bool = True,
    ) -> None:
        self._max_elements = int(max_elements)
        self.ef_construction = int(ef_construction)
        self.M = int(M)

    def set_ef(self, ef: int) -> None:
        self._ef = int(ef)

    @property
    def ef(self) -> int:
        return self._ef

    def add_items(self, data, ids, replace_deleted: bool = False) -> None:
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        for vec, raw_id in zip(arr, ids):
            label = int(raw_id)
            live = label in self._vectors and label not in self._deleted
            if live and not replace_deleted:
                raise RuntimeError(f"Duplicate label {label}")
            self._deleted.discard(label)
            v = np.asarray(vec, dtype=np.float32).reshape(-1)
            if v.shape[0] != self.dim:
                raise RuntimeError(
                    f"vector dim {v.shape[0]} != store dim {self.dim}"
                )
            self._vectors[label] = v

    def knn_query(self, data, k: int = 1):
        query = np.asarray(data, dtype=np.float32)
        if query.ndim == 1:
            query = query.reshape(1, -1)
        labels = []
        distances = []
        live_ids = [i for i in self._vectors if i not in self._deleted]
        if not live_ids:
            empty = np.zeros((query.shape[0], 0), dtype=np.int64)
            return empty, np.zeros((query.shape[0], 0), dtype=np.float32)
        mat = np.stack([self._vectors[i] for i in live_ids]).astype(np.float32)
        id_arr = np.asarray(live_ids, dtype=np.int64)
        for row in query:
            q = row.reshape(-1)
            if self.space == "l2":
                dists = np.linalg.norm(mat - q, axis=1)
            else:
                # cosine / inner-product: hnswlib cosine distance is 1 - cos.
                qn = np.linalg.norm(q)
                nn = np.linalg.norm(mat, axis=1)
                dots = mat @ q
                denom = np.clip(nn * (qn if qn > 0 else 1.0), 1e-12, None)
                sims = dots / denom
                dists = 1.0 - sims if self.space == "cosine" else -sims
            kk = max(1, min(int(k), len(live_ids)))
            idx = np.argpartition(dists, kk - 1)[:kk]
            order = np.argsort(dists[idx])
            labels.append(id_arr[idx[order]])
            distances.append(dists[idx[order]].astype(np.float32))
        return np.vstack(labels), np.vstack(distances)

    def mark_deleted(self, label: int) -> None:
        label = int(label)
        if label not in self._vectors:
            raise RuntimeError(f"label {label} not in index")
        self._deleted.add(label)

    def save_index(self, path: str) -> None:
        live_ids = [i for i in self._vectors if i not in self._deleted]
        if live_ids:
            vecs = np.stack([self._vectors[i] for i in live_ids]).astype(np.float32)
            ids = np.asarray(live_ids, dtype=np.int64)
        else:
            vecs = np.zeros((0, self.dim), dtype=np.float32)
            ids = np.zeros((0,), dtype=np.int64)
        # Use a file object so numpy does not append a surprise `.npz`.
        with open(path, "wb") as fh:
            np.savez(
                fh,
                ids=ids,
                vectors=vecs,
                dim=np.int32(self.dim),
                max_elements=np.int32(self._max_elements),
                ef=np.int32(self._ef),
                M=np.int32(self.M),
                ef_construction=np.int32(self.ef_construction),
            )

    def load_index(
        self, path: str, max_elements: int = 0, allow_replace_deleted: bool = False
    ) -> None:
        with open(path, "rb") as fh:
            payload = np.load(fh, allow_pickle=False)
            dim = int(payload["dim"])
            stored_max = int(payload["max_elements"])
            stored_ef = int(payload["ef"]) if "ef" in payload.files else self._ef
            stored_m = int(payload["M"]) if "M" in payload.files else self.M
            stored_efc = (
                int(payload["ef_construction"])
                if "ef_construction" in payload.files
                else self.ef_construction
            )
            ids = np.array(payload["ids"])
            vecs = np.array(payload["vectors"])
        self.dim = dim
        self._max_elements = stored_max if max_elements <= 0 else int(max_elements)
        self._ef = stored_ef
        self.M = stored_m
        self.ef_construction = stored_efc
        self._vectors = {}
        self._deleted = set()
        for i, vec in zip(ids, vecs):
            self._vectors[int(i)] = np.asarray(vec, dtype=np.float32).reshape(-1)

    def count(self) -> int:
        # Match hnswlib: current_count includes deleted slots still occupying
        # the structure. Operators use orphaned_vector_count to decide compact.
        return len(self._vectors)

    def get_max_elements(self) -> int:
        return self._max_elements

    def resize_index(self, new_max: int) -> None:
        self._max_elements = int(new_max)

    def get_items(self, ids: Sequence[int]):
        out = []
        for raw in ids:
            label = int(raw)
            if label not in self._vectors or label in self._deleted:
                raise RuntimeError(f"label {label} not in index")
            out.append(self._vectors[label])
        return np.stack(out).astype(np.float32)


class SqliteVecStore(NumpyVectorStore):
    """Optional sqlite-vec extra. Persists vectors in SQLite; knn is numpy
    brute-force unless the sqlite_vec extension loaded successfully.
    """

    name = "sqlite-vec"

    def __init__(self, dim: int, space: str = "cosine"):
        super().__init__(dim=dim, space=space)
        if not _sqlite_vec_available():
            raise RuntimeError("sqlite-vec is not installed")
        self._conn: Optional[sqlite3.Connection] = sqlite3.connect(":memory:")
        try:
            import sqlite_vec

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
        except Exception as e:
            logger.debug("sqlite_vec.load failed, using BLOB table: %s", e)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors "
            "(id INTEGER PRIMARY KEY, embedding BLOB NOT NULL)"
        )

    def add_items(self, data, ids, replace_deleted: bool = False) -> None:
        super().add_items(data, ids, replace_deleted=replace_deleted)
        if self._conn is None:
            return
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        for vec, raw_id in zip(arr, ids):
            blob = np.asarray(vec, dtype=np.float32).tobytes()
            self._conn.execute(
                "INSERT OR REPLACE INTO vectors (id, embedding) VALUES (?, ?)",
                (int(raw_id), blob),
            )

    def mark_deleted(self, label: int) -> None:
        super().mark_deleted(label)
        if self._conn is not None:
            self._conn.execute("DELETE FROM vectors WHERE id = ?", (int(label),))

    def save_index(self, path: str) -> None:
        super().save_index(path)
        if self._conn is None:
            return
        disk = sqlite3.connect(str(path) + ".sqlite")
        try:
            self._conn.backup(disk)
        finally:
            disk.close()

    def load_index(
        self, path: str, max_elements: int = 0, allow_replace_deleted: bool = False
    ) -> None:
        sidecar = str(path) + ".sqlite"
        if os.path.exists(sidecar):
            disk = sqlite3.connect(sidecar)
            try:
                if self._conn is None:
                    self._conn = sqlite3.connect(":memory:")
                disk.backup(self._conn)
                rows = self._conn.execute(
                    "SELECT id, embedding FROM vectors"
                ).fetchall()
                self._vectors = {}
                self._deleted = set()
                for row_id, blob in rows:
                    vec = np.frombuffer(blob, dtype=np.float32)
                    self._vectors[int(row_id)] = vec.copy()
                    if self.dim and vec.size:
                        self.dim = int(vec.size)
            finally:
                disk.close()
            if max_elements > 0:
                self._max_elements = int(max_elements)
            return
        super().load_index(
            path, max_elements=max_elements, allow_replace_deleted=allow_replace_deleted
        )


def resolve_vector_backend(requested: Optional[str] = None) -> str:
    """Pick a VectorStore name. Missing hnswlib falls back to numpy."""
    if requested:
        key = str(requested).strip().lower()
        if key in ("hnswlib", "hnsw"):
            return "hnswlib" if _try_import_hnswlib() is not None else "numpy"
        if key in ("numpy", "brute", "memory", "inmemory"):
            return "numpy"
        if key in ("sqlite-vec", "sqlite_vec", "sqlitevec"):
            return "sqlite-vec" if _sqlite_vec_available() else "numpy"
        logger.warning("Unknown vector backend %r; using default", requested)
    if _try_import_hnswlib() is not None:
        return "hnswlib"
    return "numpy"


def create_vector_store(
    backend: Optional[str],
    dim: int,
    space: str = "cosine",
) -> VectorStore:
    """Factory: hnswlib default, numpy fallback, optional sqlite-vec."""
    name = resolve_vector_backend(backend)
    if name == "hnswlib":
        try:
            return HnswlibVectorStore(dim=dim, space=space)
        except RuntimeError:
            logger.warning(
                "hnswlib unavailable; using numpy brute-force VectorStore "
                "(advised for <= %d tools)",
                _NUMPY_VECTOR_ADVISED_MAX,
            )
            return NumpyVectorStore(dim=dim, space=space)
    if name == "sqlite-vec":
        try:
            return SqliteVecStore(dim=dim, space=space)
        except RuntimeError as e:
            logger.warning("%s; using numpy brute-force VectorStore", e)
            return NumpyVectorStore(dim=dim, space=space)
    return NumpyVectorStore(dim=dim, space=space)


def available_vector_backends() -> tuple:
    names = ["numpy"]
    if _try_import_hnswlib() is not None:
        names.insert(0, "hnswlib")
    if _sqlite_vec_available():
        names.append("sqlite-vec")
    return tuple(names)


# Configuration
DB_DIR = Path(__file__).parent / "db"
HNSW_INDEX_PATH = DB_DIR / "compass.hnsw"
SQLITE_DB_PATH = DB_DIR / "tools.db"

# HNSW Parameters (tuned for ~100-1000 tools). Defaults preserved here;
# CompassConfig (BE-B-008) overrides them at CompassIndex.__init__.
HNSW_M = 16  # Number of connections per element
HNSW_EF_CONSTRUCTION = 200  # Size of dynamic candidate list during construction
HNSW_EF_SEARCH = 50  # Size of dynamic candidate list during search

# BE-B-008: log a one-time warning when corpus crosses this threshold so
# operators consider raising M / ef_search before recall starts drifting.
_HNSW_SCALE_WARN_TOOLS = 5000


@dataclass
class SearchResult:
    """Result from compass search."""

    tool: ToolDefinition
    score: float  # Cosine similarity (higher = better)
    rank: int


class CompassIndex:
    """
    HNSW-based index for semantic tool discovery.

    Architecture:
    - HNSW index stores tool embeddings for O(log n) search
    - SQLite stores tool metadata for retrieval
    - Embedder generates vectors via Ollama
    """

    def __init__(
        self,
        index_path: Path = HNSW_INDEX_PATH,
        db_path: Path = SQLITE_DB_PATH,
        embedder: Optional[Embedder] = None,
        hnsw_m: Optional[int] = None,
        hnsw_ef_construction: Optional[int] = None,
        hnsw_ef_search: Optional[int] = None,
        vector_backend: Optional[str] = None,
    ):
        """Initialize CompassIndex.

        BE-B-008: hnsw_m / hnsw_ef_construction / hnsw_ef_search are now
        runtime-tunable via CompassConfig. Defaults preserved; callers pass
        explicit overrides when they have a config in hand.

        F-5b5841c7: vector_backend selects the VectorStore implementation
        (hnswlib default, numpy fallback, optional sqlite-vec). None resolves
        via resolve_vector_backend() so a missing hnswlib still imports.
        """
        self.index_path = Path(index_path)
        self.db_path = Path(db_path)
        self.embedder = embedder or Embedder()
        self.hnsw_m = int(hnsw_m) if hnsw_m is not None else HNSW_M
        self.hnsw_ef_construction = (
            int(hnsw_ef_construction)
            if hnsw_ef_construction is not None
            else HNSW_EF_CONSTRUCTION
        )
        self.hnsw_ef_search = (
            int(hnsw_ef_search) if hnsw_ef_search is not None else HNSW_EF_SEARCH
        )
        self.vector_backend = resolve_vector_backend(vector_backend)

        self.index: Optional[VectorStore] = None
        self.db: Optional[sqlite3.Connection] = None
        self._id_to_name: Dict[int, str] = {}
        # BE-B-008: histogram of returned similarity scores (bounded) to
        # surface recall drift before users complain.
        self._score_samples: deque = deque(maxlen=2000)
        self._scale_warn_emitted = False

        # Embedding cache counters (IDX-FT-003).
        self._cache_hits = 0
        self._cache_misses = 0

        # IDX-COMPOSED-002: while build_index holds its BEGIN IMMEDIATE
        # rebuild transaction, embedding-cache mutations must NOT commit the
        # shared connection (a mid-rebuild commit prematurely persists the
        # DELETE + INSERTs, so a later HNSW-save failure can't roll them back →
        # DB/HNSW divergence). During a rebuild this holds a list of deferred
        # cache ops; _cache_put / _cache_get's self-heal append to it instead
        # of committing, and build_index flushes it AFTER its own commit. When
        # None (the normal case, e.g. add_single_tool), cache writes commit
        # immediately as before.
        self._deferred_cache_ops: Optional[List[tuple]] = None

        # BE-A-003 + F-acb311bc: serialize EVERY use of self.db (SELECT and
        # write) across threads. search_sync() dispatches search() to a worker
        # thread via ThreadPoolExecutor when called from inside a running
        # event loop (Gradio, nested MCP). The sqlite3 connection is opened
        # with check_same_thread=False (below in _init_db) so cross-thread
        # access is permitted, but that is not a substitute for a lock —
        # concurrent use of one connection is sqlite3 recursive-use-of-connection.
        # F-5ce336e7: search() also takes this lock around knn_query +
        # tools-table reads so a rebuild's DELETE+INSERT is never visible
        # mid-transaction, and hnswlib add_items/knn_query are serialized.
        # RLock: nested helpers (_cache_get → _delete_cache_row, search →
        # _get_tool_by_id, build_index → _load_id_mapping) re-enter on the
        # same thread. Do not await while holding this lock.
        self._db_write_lock = threading.RLock()

        # Ensure db directory exists
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def _embedding_dim(self) -> int:
        """Provider/embedder dim, falling back to the nomic 768 default.

        Mock embedders in tests are unittest.mock.Mock and would otherwise
        invent a Mock for ``embedding_dim``. Only a positive int is trusted.
        """
        dim = getattr(self.embedder, "embedding_dim", None)
        if isinstance(dim, int) and dim > 0:
            return dim
        return EMBEDDING_DIM

    def _hnsw_tmp_path(self) -> Path:
        return Path(str(self.index_path) + ".tmp")

    def _unlink_quietly(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.debug(f"failed to remove {path}: {e}")

    def _new_vector_store(self, dim: Optional[int] = None) -> VectorStore:
        store = create_vector_store(
            self.vector_backend, dim=dim or self._embedding_dim()
        )
        self.vector_backend = getattr(store, "name", self.vector_backend)
        return store

    def _publish_hnsw(self, new_index: VectorStore, tmp_path: Path) -> None:
        """os.replace tmp onto the live HNSW path, then assign self.index.

        Called only AFTER sqlite commit (F-57869654). A replace failure still
        publishes the in-memory index so search matches the committed tools
        table; the next successful save heals disk.
        """
        try:
            os.replace(str(tmp_path), str(self.index_path))
        except OSError as e:
            logger.error(
                "sqlite committed but HNSW os.replace(%s -> %s) failed: %s. "
                "Using in-memory index; disk HNSW may be stale until next save.",
                tmp_path,
                self.index_path,
                e,
            )
        self.index = new_index

    def _reload_hnsw_from_disk(self) -> None:
        """Restore self.index from the last committed HNSW file."""
        if not self.index_path.exists():
            return
        restored = self._new_vector_store()
        restored.load_index(str(self.index_path), allow_replace_deleted=True)
        restored.set_ef(self.hnsw_ef_search)
        self.index = restored

    def _compute_text_hash(self, text: str) -> str:
        """Compute stable cache key from (text, provider, base_url, model).

        BE-FT-PE-001: with a pluggable embedding backend the same text+model
        can produce DIFFERENT vectors across providers (e.g. ollama
        nomic-embed-text vs an OpenAI-compatible server), and even across
        endpoints of the same provider. Folding the provider NAME and the
        base_url into the key — in addition to the model — guarantees a cache
        entry written by one provider can never be served to another, so
        switching ``embedding_provider`` / ``embedding_base_url`` can't return
        a stale cross-provider vector. The dim self-heal in ``_cache_get`` is
        unaffected (it keys on embedding_dim + BLOB byte length, not this hash).

        ``provider_name`` is read defensively: test mocks and any embedder
        predating the seam expose only ``base_url`` / ``model``, so a missing
        attribute degrades to "unknown" rather than raising.
        """
        provider_name = getattr(self.embedder, "provider_name", "unknown")
        base_url = getattr(self.embedder, "base_url", "unknown")
        model = getattr(self.embedder, "model", "unknown")
        payload = f"{text}||{provider_name}||{base_url}||{model}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _cache_get(self, text_hash: str) -> Optional[np.ndarray]:
        """Return cached float32 vector or None.

        On dim mismatch (e.g., stale row from old model), treat as miss and
        delete the bad row so it gets re-populated with the current model.
        """
        if self.db is None:
            return None
        # F-acb311bc: SELECT on the shared check_same_thread=False connection
        # must take _db_write_lock. search_sync holds that lock on a worker
        # thread for the whole tools-table read; an unlocked cache lookup on
        # the event loop is sqlite3 recursive-use-of-connection.
        with self._db_write_lock:
            try:
                row = self.db.execute(
                    "SELECT vector, dim FROM embedding_cache WHERE text_hash = ?",
                    (text_hash,),
                ).fetchone()
            except sqlite3.OperationalError:
                # Table may not exist yet on a freshly-opened legacy DB.
                return None
            if row is None:
                return None
            dim = int(row["dim"])
            expected_dim = self._embedding_dim()
            if dim != expected_dim:
                # Stale entry from a different-dim model — drop and miss.
                self._delete_cache_row(text_hash)
                return None
            # SC-002: the column-dim check above is NOT sufficient. A row whose
            # dim==expected but whose BLOB byte length is inconsistent
            # (truncated / corrupt write) makes reshape(dim) raise ValueError.
            # Because _cache_get runs inside build_index's BEGIN IMMEDIATE txn,
            # an uncaught ValueError there rolls back and re-raises EVERY rebuild
            # forever, defeating the documented self-heal. Validate the actual
            # byte length (float32 == 4 bytes/element) before reshape; on
            # mismatch, treat as a miss and delete the bad row (mirroring the
            # column-dim-mismatch branch above) so the next pass re-populates it.
            blob = row["vector"]
            if blob is None or len(blob) != dim * 4:
                self._delete_cache_row(text_hash)
                return None
            vector = np.frombuffer(blob, dtype=np.float32).reshape(dim)
            # frombuffer returns a read-only view; copy so hnswlib can use it.
            return vector.copy()

    def _delete_cache_row(self, text_hash: str) -> None:
        """Self-heal delete of a bad embedding_cache row (IDX-COMPOSED-002).

        During a build_index rebuild (``self._deferred_cache_ops`` is a list)
        the delete is DEFERRED — committing here would end build_index's open
        BEGIN IMMEDIATE transaction prematurely. Otherwise it deletes + commits
        immediately, preserving the original self-heal behaviour outside a
        rebuild (e.g. add_single_tool, direct _cache_get probes).
        """
        if self.db is None:
            return
        if self._deferred_cache_ops is not None:
            self._deferred_cache_ops.append(("delete", text_hash))
            return
        with self._db_write_lock:
            self.db.execute(
                "DELETE FROM embedding_cache WHERE text_hash = ?", (text_hash,)
            )
            self.db.commit()

    def _cache_put(
        self, text_hash: str, vector: np.ndarray, dim: int, provider: str
    ) -> None:
        """BLOB-encode and store a vector. No-op if DB is unavailable.

        IDX-COMPOSED-002: during a build_index rebuild the write is DEFERRED
        (appended to ``self._deferred_cache_ops``) and flushed AFTER the
        rebuild's own commit, so it can't prematurely commit the open
        transaction. Outside a rebuild it writes + commits immediately.
        """
        if self.db is None:
            return
        vec_f32 = np.asarray(vector, dtype=np.float32).reshape(-1)
        if self._deferred_cache_ops is not None:
            self._deferred_cache_ops.append(
                ("put", text_hash, vec_f32.tobytes(), int(dim), provider)
            )
            return
        try:
            with self._db_write_lock:
                self.db.execute(
                    """
                    INSERT OR REPLACE INTO embedding_cache (text_hash, vector, dim, provider)
                    VALUES (?, ?, ?, ?)
                    """,
                    (text_hash, vec_f32.tobytes(), int(dim), provider),
                )
                self.db.commit()
        except sqlite3.OperationalError as e:
            logger.debug(f"embedding_cache put failed: {e}")

    def _flush_deferred_cache_ops_list(self, ops: List[tuple]) -> None:
        """Apply deferred embedding-cache ops AFTER build_index's own commit.

        IDX-COMPOSED-002: cache puts/deletes accumulated during a rebuild are
        applied here in a single committed batch. Called only on the success
        path (after the rebuild's commit); the failure path discards the
        pending ops so a rolled-back rebuild leaves no cache side effects.
        Best-effort: a cache-table problem must never fail the rebuild that
        already succeeded.
        """
        if not ops or self.db is None:
            return
        try:
            with self._db_write_lock:
                for op in ops:
                    if op[0] == "put":
                        _, text_hash, blob, dim, provider = op
                        self.db.execute(
                            """
                            INSERT OR REPLACE INTO embedding_cache
                                (text_hash, vector, dim, provider)
                            VALUES (?, ?, ?, ?)
                            """,
                            (text_hash, blob, dim, provider),
                        )
                    elif op[0] == "delete":
                        _, text_hash = op
                        self.db.execute(
                            "DELETE FROM embedding_cache WHERE text_hash = ?",
                            (text_hash,),
                        )
                self.db.commit()
        except sqlite3.OperationalError as e:
            logger.debug(f"deferred embedding_cache flush failed: {e}")

    def get_cache_stats(self) -> Dict:
        """Return embedding-cache hit/miss/size stats (IDX-FT-003)."""
        size = 0
        if self.db is not None:
            try:
                with self._db_write_lock:
                    row = self.db.execute(
                        "SELECT COUNT(*) AS c FROM embedding_cache"
                    ).fetchone()
                size = int(row["c"]) if row else 0
            except sqlite3.OperationalError:
                size = 0
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total) if total > 0 else 0.0
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": size,
            "hit_rate": hit_rate,
        }

    def _init_db(self):
        """Initialize SQLite database for tool metadata."""
        # BE-A-003: check_same_thread=False allows the connection to be used
        # from worker threads (search_sync ThreadPoolExecutor path).
        # F-acb311bc: connect + DDL take _db_write_lock; check_same_thread=False
        # is not a substitute for serializing this connection.
        with self._db_write_lock:
            self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.db.row_factory = sqlite3.Row

            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS tools (
                    id INTEGER PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    server TEXT NOT NULL,
                    parameters TEXT,  -- JSON (collapsed {param:type} view)
                    examples TEXT,    -- JSON
                    is_core INTEGER DEFAULT 0,
                    embedding_text TEXT,
                    raw_schema TEXT,  -- FEAT-01: full JSON inputSchema (nullable)
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tools_category ON tools(category);
                CREATE INDEX IF NOT EXISTS idx_tools_server ON tools(server);
                CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name);

                CREATE TABLE IF NOT EXISTS index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS embedding_cache (
                    text_hash TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    dim INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # FEAT-01: idempotent migration for pre-existing DBs. A tools table
            # created by an older build (before the raw_schema column existed)
            # is created by CREATE TABLE IF NOT EXISTS above WITHOUT the new
            # column, so a bare ALTER upgrades it in place — no rebuild needed.
            # On a fresh DB the column already exists and the ALTER raises
            # "duplicate column name", which we swallow (mirrors the
            # backend_sync_state forward-compat pattern in sync_manager).
            try:
                self.db.execute("ALTER TABLE tools ADD COLUMN raw_schema TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists

            self.db.commit()

        # Runtime cache hit/miss counters (IDX-FT-003). Reset only on process
        # lifetime — persisted cache entries live across runs.
        if not hasattr(self, "_cache_hits"):
            self._cache_hits = 0
        if not hasattr(self, "_cache_misses"):
            self._cache_misses = 0

    def _load_id_mapping(self):
        """Load ID to name mapping from database."""
        with self._db_write_lock:
            cursor = self.db.execute("SELECT id, name FROM tools")
            self._id_to_name = {row["id"]: row["name"] for row in cursor.fetchall()}

    async def build_index(
        self,
        tools: Optional[List[ToolDefinition]] = None,
        use_cache: bool = True,
    ):
        """
        Build HNSW index from tool definitions.

        Args:
            tools: List of tools to index. Uses manifest if not provided.
            use_cache: When True (default), reuse cached embeddings for any
                tool whose embedding_text (+ provider+model) has been seen
                before. Set False to force a fresh Ollama pass.
        """
        if tools is None:
            tools = get_all_tools()

        logger.info(f"Building index for {len(tools)} tools...")
        start_time = time.time()

        # Initialize database
        self._init_db()

        dim = self._embedding_dim()

        # Empty tool set: clear state and initialize an empty HNSW index so
        # search() returns [] cleanly (see IDX-A-002 regression).
        if not tools:
            built_at = time.time()
            tmp_path = self._hnsw_tmp_path()
            with self._db_write_lock:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    self.db.execute("DELETE FROM tools")
                    new_index = self._new_vector_store(dim)
                    # BE-A2-001: allow_replace_deleted=True permits re-adding a
                    # previously-deleted label on the UPDATE path in
                    # add_single_tool. Without it, hnswlib raises on duplicate
                    # labels and silently breaks updates of changed tools.
                    new_index.init_index(
                        max_elements=1000,
                        ef_construction=self.hnsw_ef_construction,
                        M=self.hnsw_m,
                        allow_replace_deleted=True,
                    )
                    new_index.set_ef(self.hnsw_ef_search)
                    new_index.save_index(str(tmp_path))
                    # BE-A-013: persist a wall-clock timestamp so
                    # tool_compass_index_age_seconds can compute real age.
                    # F-5b5841c7: persist vector_backend so a backend switch
                    # forces a rebuild instead of a silent load.
                    self.db.execute(
                        "INSERT OR REPLACE INTO index_meta (key, value) VALUES "
                        "('built_at_unix', ?), ('tool_count', '0'), "
                        "('embedding_dim', ?), ('vector_backend', ?)",
                        (str(built_at), str(dim), self.vector_backend),
                    )
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    self._unlink_quietly(tmp_path)
                    raise
                self._publish_hnsw(new_index, tmp_path)
            self._id_to_name = {}
            logger.info("build_index completed with 0 tools")
            # BE-A-012: callers (gateway.sync_from_backends) read
            # result['tools_indexed']; previously this branch returned None
            # and the caller TypeError'd on subscription. Return the same
            # dict shape as the populated branch.
            return {
                "tools_indexed": 0,
                "embedding_time": 0.0,
                "total_time": time.time() - start_time,
                "index_path": str(self.index_path),
                "db_path": str(self.db_path),
            }

        # F-5ce336e7: embed FIRST (no tools-table txn), then take
        # _db_write_lock for a short DELETE+INSERT+add_items+save+commit.
        # Awaiting embed_batch while BEGIN IMMEDIATE was open let search()
        # and add_single_tool see a half-rebuilt catalog / nested txn.
        embedding_texts = [tool.embedding_text() for tool in tools]

        provider = getattr(self.embedder, "base_url", "unknown")
        hashes: List[str] = []
        cached_vecs: Dict[int, np.ndarray] = {}
        miss_indices: List[int] = []
        miss_texts: List[str] = []

        for i, text in enumerate(embedding_texts):
            h = self._compute_text_hash(text) if use_cache else ""
            hashes.append(h)
            hit = self._cache_get(h) if use_cache else None
            if hit is not None:
                cached_vecs[i] = hit
                self._cache_hits += 1
            else:
                miss_indices.append(i)
                miss_texts.append(text)
                if use_cache:
                    self._cache_misses += 1

        logger.info(
            f"Embedding cache: {len(cached_vecs)} hits, {len(miss_texts)} misses"
        )

        embed_start = time.time()
        if miss_texts:
            logger.info(
                f"Generating {len(miss_texts)} embeddings via Ollama..."
            )
            miss_embeddings = await self.embedder.embed_batch(miss_texts)
            if miss_embeddings.shape != (len(miss_texts), dim):
                raise RuntimeError(
                    f"Embedding shape mismatch: got {miss_embeddings.shape}, "
                    f"expected ({len(miss_texts)}, {dim}). Rebuild after "
                    f"setting embedding_dim to the model's width."
                )
            if use_cache:
                for j, mi in enumerate(miss_indices):
                    self._cache_put(
                        hashes[mi],
                        miss_embeddings[j],
                        dim,
                        provider,
                    )
        else:
            miss_embeddings = np.zeros((0, dim), dtype=np.float32)
        embed_time = time.time() - embed_start

        embeddings = np.zeros((len(tools), dim), dtype=np.float32)
        for i, vec in cached_vecs.items():
            embeddings[i] = vec
        for j, mi in enumerate(miss_indices):
            embeddings[mi] = miss_embeddings[j]
        logger.info(
            f"Assembled {len(embeddings)} embeddings in {embed_time:.2f}s"
        )

        if embeddings.shape != (len(tools), dim):
            raise RuntimeError(
                f"Embedding shape mismatch: got {embeddings.shape}, "
                f"expected ({len(tools)}, {dim}). Rebuild after setting "
                f"embedding_dim to the model's width."
            )

        if len(tools) >= _HNSW_SCALE_WARN_TOOLS and not self._scale_warn_emitted:
            logger.warning(
                f"Indexing {len(tools)} tools — at this scale, consider "
                f"reviewing hnsw_m ({self.hnsw_m}), hnsw_ef_construction "
                f"({self.hnsw_ef_construction}), hnsw_ef_search "
                f"({self.hnsw_ef_search}) in CompassConfig."
            )
            self._scale_warn_emitted = True

        # IDX-COMPOSED-002: cache mutations during the short txn still go
        # through the deferred list so a stray _cache_put cannot commit the
        # tools-table transaction. Embed-time cache writes already committed
        # above (no tools txn was open).
        tmp_path = self._hnsw_tmp_path()
        pending: Optional[List[tuple]] = None
        with self._db_write_lock:
            self.db.execute("BEGIN IMMEDIATE")
            self._deferred_cache_ops = []
            try:
                self.db.execute("DELETE FROM tools")

                tool_ids = []
                for tool, embedding_text in zip(tools, embedding_texts):
                    raw_schema = getattr(tool, "raw_schema", None)
                    raw_schema_json = (
                        json.dumps(raw_schema)
                        if raw_schema is not None
                        else None
                    )
                    cursor = self.db.execute(
                        """
                        INSERT INTO tools (name, description, category, server, parameters, examples, is_core, embedding_text, raw_schema)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            tool.name,
                            tool.description,
                            tool.category,
                            tool.server,
                            json.dumps(tool.parameters),
                            json.dumps(tool.examples),
                            1 if tool.is_core else 0,
                            embedding_text,
                            raw_schema_json,
                        ),
                    )
                    tool_ids.append(cursor.lastrowid)

                logger.info(
                    f"Inserted {len(tools)} tools into database (uncommitted)"
                )

                logger.info("Building HNSW index...")
                # F-57869654: build into a local Index; assign self.index
                # only after sqlite commit. Save to a temp path and
                # os.replace after commit so disk HNSW cannot move ahead
                # of the tools table.
                new_index = self._new_vector_store(dim)
                # BE-A2-001: allow_replace_deleted=True permits replacing a
                # label marked deleted on the UPDATE path in add_single_tool.
                new_index.init_index(
                    max_elements=max(len(tools) * 2, 1000),
                    ef_construction=self.hnsw_ef_construction,
                    M=self.hnsw_m,
                    allow_replace_deleted=True,
                )
                new_index.add_items(embeddings, tool_ids)
                new_index.set_ef(self.hnsw_ef_search)
                new_index.save_index(str(tmp_path))

                # BE-A-013: persist both build_time (elapsed seconds; legacy)
                # and built_at_unix (wall-clock timestamp).
                # F-5b5841c7: persist vector_backend next to embedding_dim.
                self.db.execute(
                    """
                    INSERT OR REPLACE INTO index_meta (key, value) VALUES
                    ('tool_count', ?),
                    ('embedding_dim', ?),
                    ('vector_backend', ?),
                    ('hnsw_m', ?),
                    ('hnsw_ef_construction', ?),
                    ('hnsw_ef_search', ?),
                    ('build_time', ?),
                    ('built_at_unix', ?)
                """,
                    (
                        str(len(tools)),
                        str(dim),
                        self.vector_backend,
                        str(self.hnsw_m),
                        str(self.hnsw_ef_construction),
                        str(self.hnsw_ef_search),
                        str(time.time() - start_time),
                        str(time.time()),
                    ),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                self._deferred_cache_ops = None
                self._unlink_quietly(tmp_path)
                logger.error(
                    "build_index failed; rolled back SQLite transaction"
                )
                raise
            self._publish_hnsw(new_index, tmp_path)
            self._load_id_mapping()
            pending = self._deferred_cache_ops
            self._deferred_cache_ops = None

        if pending:
            self._flush_deferred_cache_ops_list(pending)

        total_time = time.time() - start_time
        logger.info(f"Index built in {total_time:.2f}s")

        return {
            "tools_indexed": len(tools),
            "embedding_time": embed_time,
            "total_time": total_time,
            "index_path": str(self.index_path),
            "db_path": str(self.db_path),
        }

    def load_index(self) -> bool:
        """
        Load existing index from disk.

        Integrity checks (IDX-B-001):
        - Compare persisted embedding_dim to the embedder's embedding_dim and
          raise RuntimeError on mismatch, so the gateway can degrade to
          lexical search instead of crashing searches silently with bad
          vectors.
        - After load, warn (don't crash) if HNSW count and DB row count
          disagree — user sees degraded recall but the server still runs.

        Returns:
            True if loaded successfully, False otherwise.
        """
        if not self.index_path.exists() or not self.db_path.exists():
            logger.warning("Index files not found")
            return False

        try:
            # Load database
            self._init_db()
            self._load_id_mapping()

            # Pre-load integrity check: read persisted dim/M/backend from
            # index_meta. A backend switch (F-5b5841c7) must force a rebuild
            # instead of silently loading the wrong on-disk format.
            with self._db_write_lock:
                cursor = self.db.execute(
                    "SELECT key, value FROM index_meta WHERE key IN "
                    "('embedding_dim', 'hnsw_m', 'vector_backend')"
                )
                meta = {row["key"]: row["value"] for row in cursor.fetchall()}
            saved_dim = meta.get("embedding_dim")
            expected_dim = self._embedding_dim()
            if saved_dim is not None:
                try:
                    saved_dim_int = int(saved_dim)
                except (TypeError, ValueError):
                    saved_dim_int = None
                if saved_dim_int is not None and saved_dim_int != expected_dim:
                    msg = (
                        f"Index file uses {saved_dim}-dim vectors but code "
                        f"expects {expected_dim}. The embedding model likely "
                        f"changed. Delete {self.index_path} and run sync to "
                        f"rebuild."
                    )
                    logger.error(msg)
                    raise RuntimeError(msg)

            saved_backend = meta.get("vector_backend")
            if saved_backend is not None and saved_backend != self.vector_backend:
                msg = (
                    f"Index file uses vector backend {saved_backend!r} but "
                    f"code expects {self.vector_backend!r}. Delete "
                    f"{self.index_path} and run sync to rebuild."
                )
                logger.error(msg)
                raise RuntimeError(msg)

            # Load HNSW index
            self.index = self._new_vector_store(expected_dim)
            # BE-A2-001: pass allow_replace_deleted=True at load so the
            # restored index supports mark_deleted + replace_deleted on the
            # add_single_tool UPDATE path. Without it, persisted indexes
            # silently revert to default-strict mode after restart.
            self.index.load_index(
                str(self.index_path), allow_replace_deleted=True
            )
            self.index.set_ef(self.hnsw_ef_search)

            # Post-load sanity: HNSW count vs DB mapping. A mismatch hurts
            # recall but isn't fatal — warn and continue. Rebuild via sync
            # will heal this.
            hnsw_count = self.index.get_current_count()
            db_count = len(self._id_to_name)
            if hnsw_count != db_count:
                logger.warning(
                    f"Index integrity: HNSW has {hnsw_count} vectors but DB "
                    f"has {db_count} tools. Search quality may be degraded — "
                    f"rebuild the index to resolve."
                )

            logger.info(f"Loaded index with {len(self._id_to_name)} tools")
            return True

        except RuntimeError:
            # Dim mismatch is a hard error the gateway needs to see.
            raise
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            return False

    def _get_tool_by_id(self, tool_id: int) -> Optional[ToolDefinition]:
        """Retrieve tool definition by ID."""
        with self._db_write_lock:
            cursor = self.db.execute(
                """
                SELECT name, description, category, server, parameters, examples, is_core
                FROM tools WHERE id = ?
            """,
                (tool_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None

        # GW-A-002 sibling: guard json.loads on possibly-corrupt tools-table
        # rows. _get_tool_by_id runs per-result inside search(); without this a
        # single malformed row raised JSONDecodeError and poisoned the ENTIRE
        # result set (everything degraded to lexical) instead of dropping the
        # one bad field. Fall back to empty defaults for the corrupt column.
        try:
            parameters = json.loads(row["parameters"]) if row["parameters"] else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning("tool %r: malformed parameters JSON; using {}", row["name"])
            parameters = {}
        try:
            examples = json.loads(row["examples"]) if row["examples"] else []
        except (json.JSONDecodeError, TypeError):
            logger.warning("tool %r: malformed examples JSON; using []", row["name"])
            examples = []
        return ToolDefinition(
            name=row["name"],
            description=row["description"],
            category=row["category"],
            server=row["server"],
            parameters=parameters,
            examples=examples,
            is_core=bool(row["is_core"]),
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category_filter: Optional[str] = None,
        server_filter: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Search for tools matching the query intent.

        Args:
            query: Natural language description of task/intent
            top_k: Number of results to return
            category_filter: Optional category to filter by
            server_filter: Optional server to filter by

        Returns:
            List of SearchResult ordered by relevance
        """
        if self.index is None:
            raise RuntimeError(
                "Index not loaded. Call load_index() or build_index() first."
            )

        # Generate query embedding outside the DB/HNSW lock — embed may
        # await, and F-5ce336e7 forbids awaiting while a tools-table txn
        # (or this lock's rebuild section) is held on the search connection.
        query_embedding = await self.embedder.embed_query(query)

        with self._db_write_lock:
            index = self.index
            if index is None:
                raise RuntimeError(
                    "Index not loaded. Call load_index() or build_index() first."
                )

            # Guard against empty index — knn_query crashes on k=0 or k > count.
            count = index.get_current_count()
            if count == 0:
                return []

            # Search HNSW (get more than needed for filtering), clamped to [1, count].
            search_k = max(1, min(top_k * 3, count))
            # BE-B-002: time the HNSW search separately from Ollama-side latency
            # so dashboards can split slow-HNSW-with-healthy-Ollama from the
            # inverse failure mode.
            knn_start = time.monotonic()
            labels, distances = index.knn_query(
                query_embedding.reshape(1, -1), k=search_k
            )
            knn_latency_ms = (time.monotonic() - knn_start) * 1000.0
            if not hasattr(self, "_hnsw_latency_samples"):
                self._hnsw_latency_samples = deque(maxlen=1000)
            self._hnsw_latency_samples.append(knn_latency_ms)

            # Convert distances to similarities (hnswlib returns 1 - cosine for cosine space)
            similarities = 1 - distances[0]
            # BE-B-008: track score samples so a leftward drift in p50 surfaces
            # degrading recall (e.g. corpus outgrew the HNSW knobs).
            for s in similarities[: min(top_k, len(similarities))]:
                try:
                    self._score_samples.append(float(s))
                except Exception:
                    pass

            results = []
            for label, similarity in zip(labels[0], similarities):
                tool = self._get_tool_by_id(int(label))
                if tool is None:
                    continue

                # Apply filters
                if category_filter and tool.category != category_filter:
                    continue
                if server_filter and tool.server != server_filter:
                    continue

                results.append(
                    SearchResult(
                        tool=tool, score=float(similarity), rank=len(results) + 1
                    )
                )

                if len(results) >= top_k:
                    break

            return results

    def search_sync(self, query: str, top_k: int = 5, **kwargs) -> List[SearchResult]:
        """Synchronous search wrapper.

        Safe to call from either a normal synchronous context or inside an
        active event loop (e.g., Gradio, FastMCP). Mirrors SyncEmbedder._run.
        """
        coro = self.search(query, top_k, **kwargs)
        try:
            asyncio.get_running_loop()
            # A loop is already running — dispatch to a worker thread with
            # its own loop so we don't deadlock the caller's loop.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        except RuntimeError:
            # No running loop — safe to use asyncio.run directly.
            return asyncio.run(coro)

    def get_stats(self) -> Dict:
        """Get index statistics."""
        if self.db is None:
            self._init_db()

        stats = {}

        # F-acb311bc: all tools-table / index_meta reads take _db_write_lock.
        # Do not call embedder.get_stats() while holding it (may await-path).
        with self._db_write_lock:
            # Tool counts
            cursor = self.db.execute("SELECT COUNT(*) as count FROM tools")
            stats["total_tools"] = cursor.fetchone()["count"]

            cursor = self.db.execute(
                "SELECT COUNT(*) as count FROM tools WHERE is_core = 1"
            )
            stats["core_tools"] = cursor.fetchone()["count"]

            # Category breakdown
            cursor = self.db.execute(
                "SELECT category, COUNT(*) as count FROM tools GROUP BY category"
            )
            stats["by_category"] = {
                row["category"]: row["count"] for row in cursor.fetchall()
            }

            # Server breakdown
            cursor = self.db.execute(
                "SELECT server, COUNT(*) as count FROM tools GROUP BY server"
            )
            stats["by_server"] = {
                row["server"]: row["count"] for row in cursor.fetchall()
            }

            # Index metadata
            cursor = self.db.execute("SELECT key, value FROM index_meta")
            stats["index_meta"] = {
                row["key"]: row["value"] for row in cursor.fetchall()
            }

        # Index age + orphan counts (IDX-B-008 + BE-A-013).
        # build_time is the duration of the most recent build in seconds.
        # built_at_unix (added in BE-A-013) is the wall-clock timestamp of
        # when that build completed; tool_compass_index_age_seconds reads
        # this. We keep build_time around for backwards compatibility but
        # prefer built_at_unix where present.
        build_time_raw = stats["index_meta"].get("build_time")
        built_at_raw = stats["index_meta"].get("built_at_unix")
        stats["last_build_at"] = built_at_raw or build_time_raw
        stats["index_age_seconds"] = None
        try:
            if built_at_raw is not None:
                stats["index_age_seconds"] = max(
                    0.0, time.time() - float(built_at_raw)
                )
            elif build_time_raw is not None:
                # Legacy: if build_time happens to look like a unix timestamp,
                # treat it as one. Otherwise leave as None.
                bt = float(build_time_raw)
                if bt > 1_000_000_000:
                    stats["index_age_seconds"] = max(0.0, time.time() - bt)
        except (TypeError, ValueError):
            stats["index_age_seconds"] = None

        # HNSW stats
        stats["vector_backend"] = self.vector_backend
        if self.index:
            hnsw_count = self.index.get_current_count()
            stats["hnsw"] = {
                "current_count": hnsw_count,
                "max_elements": self.index.get_max_elements(),
                "ef": self.index.ef,
                "m": self.hnsw_m,
                "ef_construction": self.hnsw_ef_construction,
                "ef_search": self.hnsw_ef_search,
                "backend": getattr(self.index, "name", self.vector_backend),
            }
            # Orphaned vectors = HNSW has entries that aren't in the DB
            # mapping. Clamp at 0 — DB can legitimately have rows not yet
            # loaded into the id mapping, and we don't want a negative count
            # confusing operators.
            stats["orphaned_vector_count"] = max(
                0, hnsw_count - len(self._id_to_name)
            )
        else:
            stats["orphaned_vector_count"] = 0

        # BE-B-002: HNSW search-latency percentiles (separate from Ollama).
        hnsw_samples = list(getattr(self, "_hnsw_latency_samples", []) or [])
        if hnsw_samples:
            sorted_s = sorted(hnsw_samples)
            n = len(sorted_s)
            stats["hnsw_search_latency_ms_p50"] = sorted_s[n // 2]
            stats["hnsw_search_latency_ms_p95"] = sorted_s[min(n - 1, int(n * 0.95))]
        else:
            stats["hnsw_search_latency_ms_p50"] = 0.0
            stats["hnsw_search_latency_ms_p95"] = 0.0

        # BE-B-008: returned similarity score percentiles. A persistent
        # leftward drift in p50 means recall is degrading.
        score_samples = list(self._score_samples or [])
        if score_samples:
            sorted_sc = sorted(score_samples)
            n = len(sorted_sc)
            stats["search_score_p50"] = sorted_sc[n // 2]
            stats["search_score_p95"] = sorted_sc[min(n - 1, int(n * 0.95))]
        else:
            stats["search_score_p50"] = 0.0
            stats["search_score_p95"] = 0.0

        # Embedder metrics (IDX-B-003 + IDX-B-008 surface).
        try:
            stats["embedder_stats"] = self.embedder.get_stats()
        except Exception as e:  # defensive — never let stats crash
            logger.debug(f"embedder.get_stats failed: {e}")
            stats["embedder_stats"] = None

        return stats

    async def add_single_tool(self, tool: ToolDefinition) -> bool:
        """
        Add a single tool to the index without full rebuild.
        HNSW supports dynamic element addition.

        Args:
            tool: The tool definition to add

        Returns:
            True if added successfully, False otherwise
        """
        if self.index is None or self.db is None:
            logger.error("Index not initialized. Call load_index() first.")
            return False

        try:
            # Generate embedding FIRST — if Ollama fails we never touched the DB.
            embedding_text = tool.embedding_text()
            # Consult embedding cache (IDX-FT-003) — skip Ollama on hit.
            text_hash = self._compute_text_hash(embedding_text)
            embedding = self._cache_get(text_hash)
            if embedding is not None:
                self._cache_hits += 1
            else:
                self._cache_misses += 1
                embedding = await self.embedder.embed(embedding_text)
                provider = getattr(self.embedder, "base_url", "unknown")
                self._cache_put(
                    text_hash, embedding, self._embedding_dim(), provider
                )

            expected_dim = self._embedding_dim()
            if (
                getattr(embedding, "shape", None) is not None
                and embedding.shape[-1] != expected_dim
            ):
                raise RuntimeError(
                    f"Embedding dim {embedding.shape[-1]} != {expected_dim}. "
                    f"Rebuild the index after setting embedding_dim."
                )

            # FEAT-01: preserve the full inputSchema on the incremental path too
            # (as JSON, or SQL NULL when absent) so sync's add-based branch keeps
            # schema fidelity alongside the full-rebuild branch.
            raw_schema = getattr(tool, "raw_schema", None)
            raw_schema_json = (
                json.dumps(raw_schema) if raw_schema is not None else None
            )

            # F-acb311bc: existence SELECT + writes share one lock so a
            # concurrent search_sync cannot use the connection mid-read.
            # Embed already completed above — do not await while holding.
            with self._db_write_lock:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    cursor = self.db.execute(
                        "SELECT id FROM tools WHERE name = ?", (tool.name,)
                    )
                    existing = cursor.fetchone()
                    if existing:
                        # Update existing tool
                        tool_id = existing["id"]

                        self.db.execute(
                            """
                            UPDATE tools SET
                                description = ?, category = ?, server = ?,
                                parameters = ?, examples = ?, is_core = ?,
                                embedding_text = ?, raw_schema = ?
                            WHERE id = ?
                        """,
                            (
                                tool.description,
                                tool.category,
                                tool.server,
                                json.dumps(tool.parameters),
                                json.dumps(tool.examples),
                                1 if tool.is_core else 0,
                                embedding_text,
                                raw_schema_json,
                                tool_id,
                            ),
                        )
                    else:
                        # Insert new tool
                        cursor = self.db.execute(
                            """
                            INSERT INTO tools (name, description, category, server, parameters, examples, is_core, embedding_text, raw_schema)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                tool.name,
                                tool.description,
                                tool.category,
                                tool.server,
                                json.dumps(tool.parameters),
                                json.dumps(tool.examples),
                                1 if tool.is_core else 0,
                                embedding_text,
                                raw_schema_json,
                            ),
                        )
                        tool_id = cursor.lastrowid

                    # Check if we need to resize the index
                    if self.index.get_current_count() >= self.index.get_max_elements() - 1:
                        # Need to resize - HNSW doesn't support dynamic resize, so we extend
                        new_max = self.index.get_max_elements() * 2
                        self.index.resize_index(new_max)
                        logger.info(f"Resized HNSW index to {new_max} elements")

                    # BE-A2-001: on the UPDATE path, hnswlib raises on a
                    # duplicate label by default. The index is initialized
                    # with allow_replace_deleted=True so we can mark the old
                    # label deleted and re-add with replace_deleted=True. This
                    # is the supported way to overwrite an existing vector.
                    if existing:
                        try:
                            self.index.mark_deleted(tool_id)
                        except RuntimeError as mark_err:
                            # mark_deleted raises if the label is already
                            # marked deleted (idempotent for our purposes) or
                            # not present in the index (HNSW/DB drift — treat
                            # as a fresh add). Log and continue.
                            logger.debug(
                                f"mark_deleted({tool_id}) skipped: {mark_err}"
                            )
                        self.index.add_items(
                            embedding.reshape(1, -1),
                            [tool_id],
                            replace_deleted=True,
                        )
                    else:
                        self.index.add_items(embedding.reshape(1, -1), [tool_id])

                    # F-57869654 sibling: save to a temp path; os.replace
                    # only after sqlite commit so disk HNSW cannot move
                    # ahead of the tools table. In-memory add_items already
                    # mutated self.index — reload from disk on rollback.
                    tmp_path = self._hnsw_tmp_path()
                    self.index.save_index(str(tmp_path))

                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    self._unlink_quietly(self._hnsw_tmp_path())
                    try:
                        self._reload_hnsw_from_disk()
                    except Exception as reload_err:
                        logger.error(
                            "add_single_tool rollback: failed to reload HNSW: %s",
                            reload_err,
                        )
                    raise
                else:
                    try:
                        os.replace(str(tmp_path), str(self.index_path))
                    except OSError as e:
                        logger.error(
                            "sqlite committed but HNSW os.replace failed: %s",
                            e,
                        )

            # Update ID mapping (post-commit, in-memory only)
            self._id_to_name[tool_id] = tool.name

            logger.info(f"Added tool to index: {tool.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to add tool {tool.name}: {e}")
            return False

    async def remove_tool(self, tool_name: str) -> bool:
        """
        Remove a tool from the database and mark its vector deleted.

        HNSW mark_deleted hides the label from knn_query; the slot still
        occupies current_count until compact_index() rebuilds from SQLite.

        Args:
            tool_name: Name of tool to remove

        Returns:
            True if removed from DB, False otherwise
        """
        if self.db is None:
            logger.error("Database not initialized")
            return False

        try:
            with self._db_write_lock:
                cursor = self.db.execute(
                    "SELECT id FROM tools WHERE name = ?", (tool_name,)
                )
                row = cursor.fetchone()

                if not row:
                    logger.warning(f"Tool not found: {tool_name}")
                    return False

                tool_id = row["id"]

                self.db.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
                self.db.commit()

                if self.index is not None:
                    try:
                        self.index.mark_deleted(tool_id)
                    except RuntimeError as mark_err:
                        logger.debug(
                            f"mark_deleted({tool_id}) skipped: {mark_err}"
                        )

            # Remove from ID mapping
            self._id_to_name.pop(tool_id, None)

            logger.info(f"Removed tool from index: {tool_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to remove tool {tool_name}: {e}")
            return False

    def compact_index(self) -> Dict:
        """Rebuild the vector index from live SQLite rows without re-embedding.

        F-98218381: after incremental deny/remove churn, knn_query can fill
        with orphan labels. compact_index() harvests vectors from
        embedding_cache (or the live index via get_items) and os.replace's a
        fresh store. Does not call the embedder.
        """
        if self.db is None:
            self._init_db()

        before = 0
        try:
            before = int(self.get_stats().get("orphaned_vector_count") or 0)
        except Exception:
            before = 0

        dim = self._embedding_dim()
        with self._db_write_lock:
            rows = self.db.execute(
                "SELECT id, name, embedding_text FROM tools ORDER BY id"
            ).fetchall()

        if not rows:
            tmp_path = self._hnsw_tmp_path()
            new_index = self._new_vector_store(dim)
            new_index.init_index(
                max_elements=1000,
                ef_construction=self.hnsw_ef_construction,
                M=self.hnsw_m,
                allow_replace_deleted=True,
            )
            new_index.set_ef(self.hnsw_ef_search)
            new_index.save_index(str(tmp_path))
            with self._db_write_lock:
                self.db.execute(
                    "INSERT OR REPLACE INTO index_meta (key, value) VALUES "
                    "('vector_backend', ?), ('embedding_dim', ?), "
                    "('tool_count', '0')",
                    (self.vector_backend, str(dim)),
                )
                self.db.commit()
                self._publish_hnsw(new_index, tmp_path)
                self._id_to_name = {}
            logger.info("compact_index cleared empty catalog")
            return {
                "tools_compacted": 0,
                "orphaned_vector_count_before": before,
                "orphaned_vector_count_after": 0,
                "index_path": str(self.index_path),
            }

        ids: List[int] = []
        vectors: List[np.ndarray] = []
        names: Dict[int, str] = {}
        skipped = 0
        for row in rows:
            tool_id = int(row["id"])
            names[tool_id] = row["name"]
            text = row["embedding_text"] or ""
            vec = self._cache_get(self._compute_text_hash(text)) if text else None
            if vec is None and self.index is not None:
                try:
                    harvested = self.index.get_items([tool_id])
                    vec = np.asarray(harvested, dtype=np.float32).reshape(-1)
                except Exception:
                    vec = None
            if vec is None:
                skipped += 1
                logger.warning(
                    "compact_index: no cached vector for tool id=%s name=%s; skip",
                    tool_id,
                    row["name"],
                )
                continue
            if vec.shape[-1] != dim:
                skipped += 1
                logger.warning(
                    "compact_index: dim mismatch for tool id=%s; skip", tool_id
                )
                continue
            ids.append(tool_id)
            vectors.append(np.asarray(vec, dtype=np.float32).reshape(-1))

        if rows and not ids:
            logger.error(
                "compact_index: no cached vectors; refusing to replace index"
            )
            return {
                "tools_compacted": 0,
                "orphaned_vector_count_before": before,
                "orphaned_vector_count_after": before,
                "reason": "no_cached_vectors",
                "index_path": str(self.index_path),
            }

        tmp_path = self._hnsw_tmp_path()
        new_index = self._new_vector_store(dim)
        new_index.init_index(
            max_elements=max(len(ids) * 2, 1000),
            ef_construction=self.hnsw_ef_construction,
            M=self.hnsw_m,
            allow_replace_deleted=True,
        )
        new_index.set_ef(self.hnsw_ef_search)
        if ids:
            new_index.add_items(np.stack(vectors).astype(np.float32), ids)
        new_index.save_index(str(tmp_path))
        with self._db_write_lock:
            self.db.execute(
                "INSERT OR REPLACE INTO index_meta (key, value) VALUES "
                "('vector_backend', ?), ('embedding_dim', ?), "
                "('tool_count', ?), ('built_at_unix', ?)",
                (
                    self.vector_backend,
                    str(dim),
                    str(len(ids)),
                    str(time.time()),
                ),
            )
            self.db.commit()
            self._publish_hnsw(new_index, tmp_path)
            self._id_to_name = {i: names[i] for i in ids}
        after = 0
        try:
            after = int(self.get_stats().get("orphaned_vector_count") or 0)
        except Exception:
            after = 0
        logger.info(
            "compact_index rebuilt %d vectors (skipped %d); orphans %d -> %d",
            len(ids),
            skipped,
            before,
            after,
        )
        return {
            "tools_compacted": len(ids),
            "skipped": skipped,
            "orphaned_vector_count_before": before,
            "orphaned_vector_count_after": after,
            "index_path": str(self.index_path),
        }

    async def close(self):
        """Clean up resources."""
        with self._db_write_lock:
            if self.db:
                self.db.close()
                self.db = None
        await self.embedder.close()


async def build_compass_index():
    """Build the compass index from scratch."""
    logging.basicConfig(level=logging.INFO)

    index = CompassIndex()

    # Check Ollama
    print("Checking Ollama availability...")
    if not await index.embedder.health_check():
        print("ERROR: Ollama not available or nomic-embed-text not loaded")
        print("Run: ollama pull nomic-embed-text")
        return

    # Build index
    print("\nBuilding Tool Compass index...")
    result = await index.build_index()

    print("\n✓ Index built successfully!")
    print(f"  Tools indexed: {result['tools_indexed']}")
    print(f"  Embedding time: {result['embedding_time']:.2f}s")
    print(f"  Total time: {result['total_time']:.2f}s")
    print(f"  Index path: {result['index_path']}")
    print(f"  Database path: {result['db_path']}")
    stats = index.get_stats()
    orphans = stats.get("orphaned_vector_count", 0)
    print(f"  Vector backend: {stats.get('vector_backend', index.vector_backend)}")
    print(f"  Orphaned vectors: {orphans}")
    if orphans:
        print(
            "  Hint: index.compact_index() rebuilds HNSW from SQLite "
            "without re-embedding"
        )

    # Test search
    print("\n--- Testing search ---")
    test_queries = [
        "read a file from disk",
        "generate an image with AI",
        "search for text in documents",
        "check git status",
        "analyze code quality",
    ]

    for query in test_queries:
        results = await index.search(query, top_k=3)
        print(f"\nQuery: '{query}'")
        for r in results:
            print(f"  {r.rank}. {r.tool.name} (score: {r.score:.3f})")

    await index.close()


if __name__ == "__main__":
    asyncio.run(build_compass_index())
