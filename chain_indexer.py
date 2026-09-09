"""
Tool Compass - Chain Indexer
Makes tool chains (workflows) searchable via semantic search.
"""

import json
import os
import sqlite3
import numpy as np
import logging
from pathlib import Path
from typing import Optional, List, Dict, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from analytics import CompassAnalytics

# SC-004: import EMBEDDING_DIM from embedder as the single source of truth.
# Previously chain_indexer hardcoded its own `EMBEDDING_DIM = 768`; if the
# embedding model changed (different dim), the chain index silently diverged
# from the main index and the only symptom was an opaque error swallowed by
# the bare `except Exception` in load_chain_index. Importing keeps the two
# indexes in lockstep and lets us emit an actionable rebuild message on a
# persisted-dim mismatch (see _chain_index_dim_path below). Embedder is also
# imported here so the runtime type annotations resolve without TYPE_CHECKING.
from embedder import Embedder, EMBEDDING_DIM  # noqa: F401

try:
    import hnswlib
except ImportError:
    hnswlib = None

logger = logging.getLogger(__name__)

# Paths
DB_DIR = Path(__file__).parent / "db"
CHAIN_INDEX_PATH = DB_DIR / "chains.hnsw"
ANALYTICS_DB_PATH = DB_DIR / "compass_analytics.db"

# HNSW settings for chains (smaller than main index)
CHAIN_HNSW_M = 12
CHAIN_HNSW_EF_CONSTRUCTION = 100
CHAIN_HNSW_EF_SEARCH = 30


def _chain_index_dim_path() -> Path:
    """Sidecar file recording the dim the chain HNSW index was built with.

    Derived from the *current* module-level CHAIN_INDEX_PATH at call time so
    tests that monkeypatch CHAIN_INDEX_PATH point the sidecar at the temp
    index too. hnswlib's load_index silently reinterprets on-disk vectors at
    the constructor dim (it does NOT raise on a dim mismatch), so .index.dim
    is useless for post-load detection — we persist the build-time dim here
    and compare it to EMBEDDING_DIM on load.
    """
    return Path(CHAIN_INDEX_PATH).with_suffix(".dim")


def _chain_index_backend_path() -> Path:
    """Sidecar recording the VectorStore backend the chain index was built with."""
    return Path(CHAIN_INDEX_PATH).with_suffix(".backend")


@dataclass
class ToolChain:
    """A sequence of tools that form a workflow."""

    id: int
    name: str
    tools: List[str]  # ["bridge:read_file", "bridge:write_file"]
    description: str
    use_count: int
    is_auto_detected: bool
    embedding: Optional[np.ndarray] = None
    embedding_text: Optional[str] = None


@dataclass
class ChainSearchResult:
    """Result from chain search."""

    chain: ToolChain
    score: float  # Similarity score 0-1


class ChainIndexer:
    """
    Manages tool chains as first-class searchable entities.

    Features:
    - Auto-detect chains from usage patterns
    - Index chains in HNSW for semantic search
    - Cache top 5 most-used chains
    """

    def __init__(
        self,
        embedder: "Embedder",
        analytics: Optional["CompassAnalytics"] = None,
        top_chains_cache_size: int = 5,
        vector_backend: Optional[str] = None,
    ):
        self.embedder = embedder
        self.analytics = analytics
        self.top_chains_cache_size = top_chains_cache_size
        if vector_backend:
            self.vector_backend = str(vector_backend).strip().lower()
        else:
            self.vector_backend = "hnswlib" if hnswlib is not None else "numpy"

        self.index = None
        self._chain_cache: List[ToolChain] = []
        self._id_to_chain: Dict[int, ToolChain] = {}
        self._db: Optional[sqlite3.Connection] = None

        # Ensure db directory exists
        DB_DIR.mkdir(parents=True, exist_ok=True)

    def _embedding_dim(self) -> int:
        """Provider/embedder dim, falling back to the nomic 768 default."""
        dim = getattr(self.embedder, "embedding_dim", None)
        if isinstance(dim, int) and dim > 0:
            return dim
        return EMBEDDING_DIM

    def _get_db(self) -> sqlite3.Connection:
        """Get database connection (uses analytics DB).

        BE-A-008 + BE-B-010: opened with check_same_thread=False because the
        analytics DB is shared across analytics.py + sync_manager.py +
        chain_indexer.py — these three each held independent connections
        that raced for the file lock. WAL + busy_timeout serialize them
        cleanly at the SQLite level.
        """
        if self._db is None:
            self._db = sqlite3.connect(
                str(ANALYTICS_DB_PATH), check_same_thread=False
            )
            self._db.row_factory = sqlite3.Row
            try:
                self._db.execute("PRAGMA busy_timeout = 5000")
                self._db.execute("PRAGMA journal_mode = WAL")
                self._db.execute("PRAGMA synchronous = NORMAL")
            except sqlite3.Error as e:
                logger.debug(f"sqlite PRAGMA setup failed: {e}")
        return self._db

    def create_chain_embedding_text(self, chain: ToolChain) -> str:
        """
        Generate rich text for chain embedding.
        Combines workflow name, steps, and tool names for better semantic matching.
        """
        # Extract simple tool names
        tool_names = [t.split(":")[-1].replace("_", " ") for t in chain.tools]

        parts = [
            f"Workflow: {chain.name.replace('_', ' ')}",
            f"Steps: {', '.join(tool_names)}",
            f"Description: {chain.description}",
            f"Tools: {', '.join(chain.tools)}",
            f"Use cases: {' then '.join(tool_names)}",
        ]

        return " | ".join(parts)

    async def load_chains_from_db(self) -> List[ToolChain]:
        """Load all chains from database."""
        db = self._get_db()

        cursor = db.execute("""
            SELECT id, chain_name, chain_tools, description, use_count, is_auto_detected, embedding_text
            FROM tool_chains
            ORDER BY use_count DESC
        """)

        chains = []
        for row in cursor.fetchall():
            chain = ToolChain(
                id=row["id"],
                name=row["chain_name"],
                tools=json.loads(row["chain_tools"]),
                description=row["description"] or "",
                use_count=row["use_count"],
                is_auto_detected=bool(row["is_auto_detected"]),
                embedding_text=row["embedding_text"],
            )
            chains.append(chain)

        return chains

    def _new_vector_store(self, dim: Optional[int] = None):
        # Lazy import so chain_indexer can load without pulling indexer.py
        # (and its tool_manifest) at module import time.
        from indexer import create_vector_store

        store = create_vector_store(
            self.vector_backend, dim=dim or self._embedding_dim()
        )
        self.vector_backend = getattr(store, "name", self.vector_backend)
        return store

    async def build_chain_index(self, chains: Optional[List[ToolChain]] = None):
        """
        Build HNSW index for chains.
        If chains not provided, loads from database.
        """
        if chains is None:
            chains = await self.load_chains_from_db()

        if not chains:
            logger.info("No chains to index")
            return

        logger.info(f"Building chain index with {len(chains)} chains...")

        # F-c987c9d3: one embed_batch instead of N sequential embed() calls.
        need = [c for c in chains if c.embedding is None]
        if need:
            texts = [
                (c.embedding_text or self.create_chain_embedding_text(c))
                for c in need
            ]
            for chain, text in zip(need, texts):
                chain.embedding_text = text
            batch = await self.embedder.embed_batch(texts)
            for chain, vec in zip(need, batch):
                chain.embedding = vec

        dim = self._embedding_dim()
        # F-57869654 sibling: build into a local Index; assign self.index
        # only after the on-disk save commits via os.replace.
        new_index = self._new_vector_store(dim)
        # BE-A2-002: allow_replace_deleted=True permits the ON CONFLICT path
        # in add_chain to mark the old label deleted and re-add with
        # replace_deleted=True. Without this flag, hnswlib raises on duplicate
        # labels and the DB row updates while HNSW stays stale.
        new_index.init_index(
            max_elements=max(len(chains) * 2, 100),
            M=CHAIN_HNSW_M,
            ef_construction=CHAIN_HNSW_EF_CONSTRUCTION,
            allow_replace_deleted=True,
        )
        new_index.set_ef(CHAIN_HNSW_EF_SEARCH)

        # Add chains to index
        id_to_chain: Dict[int, ToolChain] = {}
        embeddings = []
        ids = []

        for chain in chains:
            id_to_chain[chain.id] = chain
            embeddings.append(chain.embedding)
            ids.append(chain.id)

        if embeddings:
            embeddings_array = np.vstack(embeddings).astype(np.float32)
            if embeddings_array.shape[1] != dim:
                raise RuntimeError(
                    f"Chain embedding shape mismatch: got "
                    f"{embeddings_array.shape}, expected (*, {dim}). "
                    f"Rebuild the chain index after setting embedding_dim."
                )
            new_index.add_items(embeddings_array, ids)

        tmp_path = Path(str(CHAIN_INDEX_PATH) + ".tmp")
        new_index.save_index(str(tmp_path))
        try:
            os.replace(str(tmp_path), str(CHAIN_INDEX_PATH))
        except OSError:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        self.index = new_index
        self._id_to_chain = id_to_chain
        # SC-004: persist the build-time embedding dim so a later load can
        # detect a model-dim change with an actionable message.
        try:
            _chain_index_dim_path().write_text(str(dim), encoding="utf-8")
        except OSError as e:
            logger.debug(f"failed to write chain index dim sidecar: {e}")
        try:
            _chain_index_backend_path().write_text(
                self.vector_backend, encoding="utf-8"
            )
        except OSError as e:
            logger.debug(f"failed to write chain index backend sidecar: {e}")
        logger.info(f"Chain index saved to {CHAIN_INDEX_PATH}")

        # Update cache
        await self.refresh_chain_cache()

    def _read_persisted_index_dim(self) -> Optional[int]:
        """Read the dim the chain index was built with, or None.

        SC-004: returns None when the sidecar is absent (legacy index built
        before this check existed) or unparseable, so a missing sidecar
        never blocks load — only a *known* mismatch does.
        """
        dim_path = _chain_index_dim_path()
        try:
            if not dim_path.exists():
                return None
            return int(dim_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _read_persisted_index_backend(self) -> Optional[str]:
        path = _chain_index_backend_path()
        try:
            if not path.exists():
                return None
            value = path.read_text(encoding="utf-8").strip()
            return value or None
        except OSError:
            return None

    async def load_chain_index(self) -> bool:
        """Load existing chain index from disk."""
        if not CHAIN_INDEX_PATH.exists():
            return False

        try:
            chains = await self.load_chains_from_db()
            if not chains:
                return False

            # SC-004: persisted-dim sanity check. If the chain index was
            # built with a different embedding dim (model changed), loading
            # it would either crash opaquely later (add_chain's add_items) or
            # silently return wrong neighbors. Detect it here and fail the
            # load with an actionable rebuild message instead of swallowing
            # an opaque error in the bare except below.
            persisted_dim = self._read_persisted_index_dim()
            expected_dim = self._embedding_dim()
            if persisted_dim is not None and persisted_dim != expected_dim:
                logger.error(
                    "Chain index was built with %d-dim vectors but the "
                    "embedder now produces %d-dim vectors. The embedding "
                    "model likely changed. Delete %s (and %s) and rebuild "
                    "the chain index via build_chain_index().",
                    persisted_dim,
                    expected_dim,
                    CHAIN_INDEX_PATH,
                    _chain_index_dim_path(),
                )
                return False

            persisted_backend = self._read_persisted_index_backend()
            if (
                persisted_backend is not None
                and persisted_backend != self.vector_backend
            ):
                logger.error(
                    "Chain index was built with vector backend %r but "
                    "code expects %r. Delete %s (and %s) and rebuild via "
                    "build_chain_index().",
                    persisted_backend,
                    self.vector_backend,
                    CHAIN_INDEX_PATH,
                    _chain_index_backend_path(),
                )
                return False

            self.index = self._new_vector_store(expected_dim)
            # BE-A2-002: pass allow_replace_deleted=True at load so the
            # restored chain index supports mark_deleted + replace_deleted on
            # add_chain's ON CONFLICT path after a restart.
            self.index.load_index(
                str(CHAIN_INDEX_PATH), allow_replace_deleted=True
            )
            self.index.set_ef(CHAIN_HNSW_EF_SEARCH)

            # Build ID mapping
            self._id_to_chain = {chain.id: chain for chain in chains}

            await self.refresh_chain_cache()
            logger.info(f"Loaded chain index with {len(chains)} chains")
            return True
        except Exception as e:
            logger.error(f"Failed to load chain index: {e}")
            return False

    async def search_chains(
        self, query: str, top_k: int = 3, min_confidence: float = 0.3
    ) -> List[ChainSearchResult]:
        """
        Search for relevant tool chains.

        Args:
            query: Natural language search query
            top_k: Maximum number of results
            min_confidence: Minimum similarity threshold

        Returns:
            List of ChainSearchResult sorted by score
        """
        if self.index is None or self.index.get_current_count() == 0:
            return []

        # Generate query embedding
        query_embedding = await self.embedder.embed_query(query)

        # Search HNSW
        search_k = min(top_k * 2, self.index.get_current_count())
        labels, distances = self.index.knn_query(
            query_embedding.reshape(1, -1), k=search_k
        )

        # Convert to results
        results = []
        for label, distance in zip(labels[0], distances[0]):
            # Convert cosine distance to similarity
            similarity = 1 - distance

            if similarity < min_confidence:
                continue

            # Cast numpy int64 → Python int so dict lookup matches int keys.
            chain = self._id_to_chain.get(int(label))
            if chain:
                results.append(ChainSearchResult(
                    chain=chain,
                    score=float(similarity)  # Convert numpy float to Python float
                ))

        # Sort by score and limit
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def refresh_chain_cache(self):
        """Update cache with top N most-used chains."""
        chains = await self.load_chains_from_db()

        # Sort by use count and take top N
        chains.sort(key=lambda c: c.use_count, reverse=True)
        self._chain_cache = chains[: self.top_chains_cache_size]

        logger.debug(f"Refreshed chain cache with {len(self._chain_cache)} chains")

    async def add_chain(
        self,
        name: str,
        tools: List[str],
        description: Optional[str] = None,
        is_auto_detected: bool = False,
    ) -> ToolChain:
        """
        Add a new chain to the index.

        Args:
            name: Unique chain name
            tools: List of tool names in order
            description: Human-readable description
            is_auto_detected: Whether this was auto-detected from patterns

        Returns:
            The created ToolChain
        """
        db = self._get_db()

        # Generate description if not provided
        if not description:
            tool_names = [t.split(":")[-1].replace("_", " ") for t in tools]
            description = f"Workflow: {' → '.join(tool_names)}"

        # Generate embedding text
        embedding_text = f"Workflow: {name.replace('_', ' ')} | Steps: {description} | Tools: {', '.join(tools)}"

        # Generate embedding (use embed() for documents, embed_query() for searches)
        embedding = await self.embedder.embed(embedding_text)
        expected_dim = self._embedding_dim()
        if (
            getattr(embedding, "shape", None) is not None
            and embedding.shape[-1] != expected_dim
        ):
            raise RuntimeError(
                f"Chain embedding dim {embedding.shape[-1]} != {expected_dim}. "
                f"Rebuild the chain index after setting embedding_dim."
            )

        # BE-A2-002: detect UPDATE vs INSERT BEFORE the write, so the HNSW
        # branch below can mark_deleted + replace_deleted on the duplicate-
        # label case. Without this, add_items raises after the DB row was
        # already updated, leaving DB and HNSW divergent.
        pre_existing_row = db.execute(
            "SELECT id FROM tool_chains WHERE chain_name = ?", (name,)
        ).fetchone()
        is_update = pre_existing_row is not None

        # Insert into DB
        db.execute(
            """
            INSERT INTO tool_chains (chain_name, chain_tools, description, embedding_text, is_auto_detected)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chain_name) DO UPDATE SET
                chain_tools = excluded.chain_tools,
                description = excluded.description,
                embedding_text = excluded.embedding_text
        """,
            (
                name,
                json.dumps(tools),
                description,
                embedding_text,
                1 if is_auto_detected else 0,
            ),
        )
        db.commit()

        # BE-A-005: cursor.lastrowid is unreliable after INSERT...ON CONFLICT
        # DO UPDATE — on SQLite <3.35 it returns 0 because no actual INSERT
        # happened on the conflict path, which would corrupt _id_to_chain and
        # leave the chain unreachable in HNSW. Re-SELECT the canonical id by
        # chain_name (the unique key the conflict resolves against).
        id_row = db.execute(
            "SELECT id FROM tool_chains WHERE chain_name = ?", (name,)
        ).fetchone()
        if id_row is None:
            raise RuntimeError(
                f"add_chain: row for chain_name={name!r} disappeared after INSERT"
            )
        chain_id = id_row["id"]

        chain = ToolChain(
            id=chain_id,
            name=name,
            tools=tools,
            description=description,
            use_count=0,
            is_auto_detected=is_auto_detected,
            embedding=embedding,
            embedding_text=embedding_text,
        )

        # Add to index if it exists
        if self.index:
            # Resize at capacity so add_items doesn't throw on a full index.
            current_count = self.index.get_current_count()
            max_elements = self.index.get_max_elements()
            if current_count >= max_elements - 1:
                new_max = max_elements * 2
                self.index.resize_index(new_max)
                logger.info(f"Resized chain HNSW index to {new_max} elements")

            self._id_to_chain[chain_id] = chain
            # BE-A2-002: ON CONFLICT path re-uses an existing chain_id; HNSW
            # default behavior raises on duplicate labels. Mark the old label
            # deleted and re-add with replace_deleted=True so DB and HNSW
            # stay consistent. allow_replace_deleted=True is enabled at
            # init/load. mark_deleted is wrapped in try because it raises on
            # unknown labels (e.g., HNSW/DB drift) — fall through to fresh
            # add in that case.
            if is_update:
                try:
                    self.index.mark_deleted(chain_id)
                except RuntimeError as mark_err:
                    logger.debug(
                        f"mark_deleted({chain_id}) skipped: {mark_err}"
                    )
                self.index.add_items(
                    embedding.reshape(1, -1).astype(np.float32),
                    [chain_id],
                    replace_deleted=True,
                )
            else:
                self.index.add_items(
                    embedding.reshape(1, -1).astype(np.float32), [chain_id]
                )
            self.index.save_index(str(CHAIN_INDEX_PATH))

        logger.info(f"Added chain: {name} with {len(tools)} tools")
        return chain

    async def record_chain_use(self, chain_name: str):
        """Record that a chain was used (for ranking)."""
        db = self._get_db()
        db.execute(
            """
            UPDATE tool_chains
            SET use_count = use_count + 1, last_used_at = CURRENT_TIMESTAMP
            WHERE chain_name = ?
        """,
            (chain_name,),
        )
        db.commit()

        # Update cache if this chain is in it
        for chain in self._chain_cache:
            if chain.name == chain_name:
                chain.use_count += 1
                break

    async def get_chain(self, chain_name: str) -> Optional[ToolChain]:
        """Get a specific chain by name."""
        # Check cache first
        for chain in self._chain_cache:
            if chain.name == chain_name:
                return chain

        # Check DB
        db = self._get_db()
        row = db.execute(
            """
            SELECT id, chain_name, chain_tools, description, use_count, is_auto_detected, embedding_text
            FROM tool_chains
            WHERE chain_name = ?
        """,
            (chain_name,),
        ).fetchone()

        if row:
            return ToolChain(
                id=row["id"],
                name=row["chain_name"],
                tools=json.loads(row["chain_tools"]),
                description=row["description"] or "",
                use_count=row["use_count"],
                is_auto_detected=bool(row["is_auto_detected"]),
                embedding_text=row["embedding_text"],
            )

        return None

    async def seed_default_chains(self):
        """Add predefined common tool chains."""
        default_chains = [
            {
                "name": "file_modify",
                "tools": ["bridge:read_file", "bridge:write_file"],
                "description": "Read a file, modify its contents, and write it back",
            },
            {
                "name": "git_commit",
                "tools": ["bridge:git_status", "bridge:git_add", "bridge:git_commit"],
                "description": "Check status, stage changes, and commit to git",
            },
            {
                "name": "code_analysis",
                "tools": ["doc:scan_codebase", "doc:generate_report"],
                "description": "Analyze codebase and generate a health report",
            },
            {
                "name": "image_generation",
                "tools": [
                    "comfy:comfy_status",
                    "comfy:comfy_generate",
                    "comfy:comfy_history",
                ],
                "description": "Check ComfyUI status, generate an image, and view history",
            },
            {
                "name": "database_query",
                "tools": [
                    "bridge:db_list_tables",
                    "bridge:db_inspect_table",
                    "bridge:db_execute",
                ],
                "description": "List tables, inspect schema, and run queries",
            },
        ]

        for chain_def in default_chains:
            existing = await self.get_chain(chain_def["name"])
            if not existing:
                await self.add_chain(
                    name=chain_def["name"],
                    tools=chain_def["tools"],
                    description=chain_def["description"],
                    is_auto_detected=False,
                )

        logger.info(f"Seeded {len(default_chains)} default chains")

    def get_cached_chains(self) -> List[ToolChain]:
        """Get the cached top chains."""
        return self._chain_cache

    def compact_index(self) -> Dict:
        """Rebuild the chain vector index from live SQLite without re-embedding.

        F-98218381: harvest vectors from the current store via get_items.
        When tool_chains is empty, clear the in-memory index and drop the
        on-disk file.
        """
        db = self._get_db()
        rows = db.execute(
            "SELECT id, chain_name, chain_tools, description, use_count, "
            "is_auto_detected, embedding_text FROM tool_chains ORDER BY id"
        ).fetchall()

        if not rows:
            self.index = None
            self._id_to_chain = {}
            self._chain_cache = []
            for path in (
                Path(CHAIN_INDEX_PATH),
                _chain_index_dim_path(),
                _chain_index_backend_path(),
            ):
                try:
                    path.unlink(missing_ok=True)
                except OSError as e:
                    logger.debug("compact_index unlink %s: %s", path, e)
            logger.info("compact_index cleared empty chain catalog")
            return {"chains_compacted": 0, "index_path": str(CHAIN_INDEX_PATH)}

        if self.index is None:
            logger.warning(
                "compact_index: no in-memory chain index to harvest vectors from"
            )
            return {
                "chains_compacted": 0,
                "reason": "no_index",
                "index_path": str(CHAIN_INDEX_PATH),
            }

        dim = self._embedding_dim()
        ids: List[int] = []
        vectors: List[np.ndarray] = []
        id_to_chain: Dict[int, ToolChain] = {}
        skipped = 0
        for row in rows:
            chain_id = int(row["id"])
            chain = ToolChain(
                id=chain_id,
                name=row["chain_name"],
                tools=json.loads(row["chain_tools"]),
                description=row["description"] or "",
                use_count=row["use_count"],
                is_auto_detected=bool(row["is_auto_detected"]),
                embedding_text=row["embedding_text"],
            )
            vec = None
            cached = self._id_to_chain.get(chain_id)
            if cached is not None and cached.embedding is not None:
                vec = np.asarray(cached.embedding, dtype=np.float32).reshape(-1)
            if vec is None:
                try:
                    harvested = self.index.get_items([chain_id])
                    vec = np.asarray(harvested, dtype=np.float32).reshape(-1)
                except Exception:
                    vec = None
            if vec is None or vec.shape[-1] != dim:
                skipped += 1
                logger.warning(
                    "compact_index: no vector for chain id=%s name=%s; skip",
                    chain_id,
                    chain.name,
                )
                continue
            chain.embedding = vec
            ids.append(chain_id)
            vectors.append(vec)
            id_to_chain[chain_id] = chain

        if rows and not ids:
            logger.error(
                "compact_index: no harvestable chain vectors; refusing to replace"
            )
            return {
                "chains_compacted": 0,
                "reason": "no_cached_vectors",
                "index_path": str(CHAIN_INDEX_PATH),
            }

        new_index = self._new_vector_store(dim)
        new_index.init_index(
            max_elements=max(len(ids) * 2, 100),
            M=CHAIN_HNSW_M,
            ef_construction=CHAIN_HNSW_EF_CONSTRUCTION,
            allow_replace_deleted=True,
        )
        new_index.set_ef(CHAIN_HNSW_EF_SEARCH)
        if ids:
            new_index.add_items(np.stack(vectors).astype(np.float32), ids)
        tmp_path = Path(str(CHAIN_INDEX_PATH) + ".tmp")
        new_index.save_index(str(tmp_path))
        try:
            os.replace(str(tmp_path), str(CHAIN_INDEX_PATH))
        except OSError:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        self.index = new_index
        self._id_to_chain = id_to_chain
        try:
            _chain_index_dim_path().write_text(str(dim), encoding="utf-8")
        except OSError as e:
            logger.debug("failed to write chain index dim sidecar: %s", e)
        try:
            _chain_index_backend_path().write_text(
                self.vector_backend, encoding="utf-8"
            )
        except OSError as e:
            logger.debug("failed to write chain index backend sidecar: %s", e)
        logger.info(
            "compact_index rebuilt %d chain vectors (skipped %d)",
            len(ids),
            skipped,
        )
        return {
            "chains_compacted": len(ids),
            "skipped": skipped,
            "index_path": str(CHAIN_INDEX_PATH),
        }

    def close(self):
        """Close database connection."""
        if self._db:
            self._db.close()
            self._db = None


# Singleton instance
_chain_indexer_instance: Optional[ChainIndexer] = None


def get_chain_indexer(
    embedder: "Embedder", analytics: Optional["CompassAnalytics"] = None
) -> ChainIndexer:
    """Get or create the chain indexer singleton."""
    global _chain_indexer_instance
    if _chain_indexer_instance is None:
        _chain_indexer_instance = ChainIndexer(embedder, analytics)
    return _chain_indexer_instance
