"""
Tests for Tool Compass indexer module.

Tests HNSW index building, searching, and metadata management.
"""

import numpy as np
import pytest

from indexer import CompassIndex, SearchResult
from embedder import EMBEDDING_DIM
from tool_manifest import ToolDefinition


class TestCompassIndex:
    """Test CompassIndex core functionality."""

    @pytest.mark.asyncio
    async def test_build_index(
        self, temp_index_path, temp_db_path, mock_embedder, sample_tools
    ):
        """Should build index from tool definitions."""
        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )

        result = await index.build_index(sample_tools)

        assert result["tools_indexed"] == len(sample_tools)
        assert result["total_time"] > 0
        assert temp_index_path.exists()
        assert temp_db_path.exists()

        await index.close()

    @pytest.mark.asyncio
    async def test_load_index(
        self, test_index, temp_index_path, temp_db_path, mock_embedder
    ):
        """Should load existing index from disk."""
        # test_index fixture already built the index
        # Create new instance and load
        new_index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )

        loaded = new_index.load_index()
        assert loaded is True
        assert new_index.index is not None
        assert len(new_index._id_to_name) > 0

        await new_index.close()

    @pytest.mark.asyncio
    async def test_load_index_missing(self, temp_db_dir, mock_embedder):
        """Should return False when index files don't exist."""
        index = CompassIndex(
            index_path=temp_db_dir / "missing.hnsw",
            db_path=temp_db_dir / "missing.db",
            embedder=mock_embedder,
        )

        loaded = index.load_index()
        assert loaded is False

        await index.close()

    @pytest.mark.asyncio
    async def test_search_basic(self, test_index):
        """Should return relevant results for a query."""
        results = await test_index.search("read a file", top_k=3)

        assert len(results) > 0
        assert len(results) <= 3
        assert all(isinstance(r, SearchResult) for r in results)
        # Scores are cosine similarity - typically in [-1, 1] but embeddings
        # may produce values slightly outside due to numerical precision
        assert all(isinstance(r.score, float) for r in results)

    @pytest.mark.asyncio
    async def test_search_returns_tool_definition(self, test_index):
        """Search results should include full ToolDefinition."""
        results = await test_index.search("file operations", top_k=1)

        assert len(results) == 1
        tool = results[0].tool
        assert isinstance(tool, ToolDefinition)
        assert tool.name
        assert tool.description
        assert tool.category

    @pytest.mark.asyncio
    async def test_search_category_filter(self, test_index):
        """Should filter results by category."""
        results = await test_index.search(
            "operations", top_k=10, category_filter="file"
        )

        assert len(results) > 0
        for r in results:
            assert r.tool.category == "file"

    @pytest.mark.asyncio
    async def test_search_server_filter(self, test_index):
        """Should filter results by server."""
        results = await test_index.search("anything", top_k=10, server_filter="test")

        assert len(results) > 0
        for r in results:
            assert r.tool.server == "test"

    @pytest.mark.asyncio
    async def test_search_combined_filters(self, test_index):
        """Should apply both category and server filters."""
        results = await test_index.search(
            "file operations", top_k=10, category_filter="file", server_filter="test"
        )

        for r in results:
            assert r.tool.category == "file"
            assert r.tool.server == "test"

    @pytest.mark.asyncio
    async def test_search_empty_results(self, test_index):
        """Should return empty list when no matches."""
        results = await test_index.search(
            "file operations", top_k=10, category_filter="nonexistent_category"
        )

        assert results == []


class TestEmbeddingCacheSelfHeal:
    """SC-002 regression: a corrupt/truncated embedding_cache BLOB whose
    `dim` column still equals EMBEDDING_DIM must be treated as a cache MISS
    (and deleted), not crash the rebuild.

    _cache_get guarded reshape() only on the column-dim value, never the
    actual BLOB byte length. A row with dim==EMBEDDING_DIM but a
    truncated/corrupt BLOB made np.frombuffer(...).reshape(dim) raise
    ValueError. Because _cache_get runs inside build_index's BEGIN IMMEDIATE
    transaction, that uncaught ValueError rolled back and re-raised EVERY
    rebuild forever — defeating the documented self-heal. The fix validates
    len(blob) == dim * 4 and, on mismatch, deletes the bad row + reports a
    miss so the next pass re-populates it.
    """

    @pytest.mark.asyncio
    async def test_cache_get_truncated_blob_is_a_miss(
        self, temp_index_path, temp_db_path, mock_embedder, sample_tools
    ):
        """Directly probe _cache_get: a dim-OK but wrong-length BLOB returns
        None (miss) and the bad row is deleted (self-heal).
        """
        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )
        await index.build_index(sample_tools)

        text = sample_tools[0].embedding_text()
        text_hash = index._compute_text_hash(text)

        # Corrupt the stored BLOB to a truncated length while leaving the
        # `dim` column at the valid EMBEDDING_DIM — this is the exact shape
        # the column-dim check fails to catch.
        bad_blob = np.zeros(EMBEDDING_DIM - 5, dtype=np.float32).tobytes()
        with index._db_write_lock:
            index.db.execute(
                "UPDATE embedding_cache SET vector = ? WHERE text_hash = ?",
                (bad_blob, text_hash),
            )
            index.db.commit()

        # Must NOT raise ValueError; must report a miss (None).
        result = index._cache_get(text_hash)
        assert result is None, "corrupt-length BLOB must be treated as a miss"

        # The bad row must have been deleted (self-heal).
        row = index.db.execute(
            "SELECT COUNT(*) AS c FROM embedding_cache WHERE text_hash = ?",
            (text_hash,),
        ).fetchone()
        assert row["c"] == 0, "corrupt cache row should be deleted on miss"

        await index.close()

    @pytest.mark.asyncio
    async def test_rebuild_self_heals_corrupt_cache_row(
        self, temp_index_path, temp_db_path, mock_embedder, sample_tools
    ):
        """End-to-end: a corrupt cache row must not crash build_index — the
        rebuild treats it as a miss, re-embeds, and completes successfully.
        """
        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )
        # First build populates the cache legitimately.
        await index.build_index(sample_tools)

        # Corrupt ONE cache row: keep dim == EMBEDDING_DIM, truncate the BLOB.
        text = sample_tools[1].embedding_text()
        text_hash = index._compute_text_hash(text)
        bad_blob = np.zeros(EMBEDDING_DIM - 3, dtype=np.float32).tobytes()
        with index._db_write_lock:
            index.db.execute(
                "UPDATE embedding_cache SET vector = ? WHERE text_hash = ?",
                (bad_blob, text_hash),
            )
            index.db.commit()

        # On the OLD code, _cache_get's reshape() raised ValueError inside the
        # BEGIN IMMEDIATE txn and this rebuild crashed (and would crash
        # forever). The fix must let the rebuild succeed.
        result = await index.build_index(sample_tools)
        assert result["tools_indexed"] == len(sample_tools)

        # And search still works after the self-heal.
        results = await index.search("read a file", top_k=3)
        assert len(results) > 0

        await index.close()


class TestGetToolByIdMalformedJson:
    """GW-A-002 sibling: a tools-table row with malformed JSON in the
    `parameters`/`examples` columns must be skipped-with-defaults inside
    _get_tool_by_id, not raise JSONDecodeError.

    _get_tool_by_id runs per-result inside search(); without the guard a
    single corrupt row raised and poisoned the ENTIRE result set (every
    result silently degraded to lexical) instead of dropping the one bad
    field. The fix falls back to {}/[] for the corrupt column and keeps the
    rest of the catalog searchable.
    """

    @pytest.mark.asyncio
    async def test_get_tool_by_id_bad_parameters_json_returns_defaults(
        self, temp_index_path, temp_db_path, mock_embedder, sample_tools
    ):
        """A row with invalid JSON in `parameters` returns a ToolDefinition
        with parameters={} (and examples=[] when also corrupt), never a raise.
        """
        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )
        await index.build_index(sample_tools)

        # Corrupt the parameters column for one existing tool while leaving at
        # least one VALID row untouched. Capture its row id for direct probing.
        with index._db_write_lock:
            index.db.execute(
                "UPDATE tools SET parameters = ?, examples = ? WHERE name = ?",
                ("{not json", "[also broken", "test:read_file"),
            )
            index.db.commit()
        row = index.db.execute(
            "SELECT id FROM tools WHERE name = ?", ("test:read_file",)
        ).fetchone()
        bad_id = row["id"]

        # Direct probe: must NOT raise JSONDecodeError; degrades to {} / [].
        tool = index._get_tool_by_id(bad_id)
        assert tool is not None
        assert tool.name == "test:read_file"
        assert tool.parameters == {}, (
            "malformed parameters JSON must fall back to {}"
        )
        assert tool.examples == [], (
            "malformed examples JSON must fall back to []"
        )

        await index.close()

    @pytest.mark.asyncio
    async def test_search_survives_one_corrupt_row(
        self, temp_index_path, temp_db_path, mock_embedder, sample_tools
    ):
        """End-to-end: with one corrupt row present, a search that surfaces a
        DIFFERENT (valid) row still returns normally — the corrupt row does
        not poison the whole search.
        """
        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )
        await index.build_index(sample_tools)

        # Corrupt git_status's parameters; read_file stays valid.
        with index._db_write_lock:
            index.db.execute(
                "UPDATE tools SET parameters = ? WHERE name = ?",
                ("{not json", "test:git_status"),
            )
            index.db.commit()

        # A search must not raise, even if the corrupt row is among candidates.
        results = await index.search("read a file", top_k=5)
        assert len(results) > 0
        # Any surfaced result is a well-formed ToolDefinition (the corrupt row,
        # if surfaced, degrades to {} rather than raising).
        for r in results:
            assert isinstance(r.tool, ToolDefinition)
            assert isinstance(r.tool.parameters, dict)

        await index.close()


class TestIndexStats:
    """Test index statistics and metadata."""

    @pytest.mark.asyncio
    async def test_get_stats(self, test_index, sample_tools):
        """Should return comprehensive statistics."""
        stats = test_index.get_stats()

        assert stats["total_tools"] == len(sample_tools)
        assert "by_category" in stats
        assert "by_server" in stats
        assert stats["by_category"]["file"] == 2  # read_file, write_file
        assert stats["by_category"]["git"] == 1
        assert stats["by_category"]["ai"] == 1

    @pytest.mark.asyncio
    async def test_get_stats_hnsw_info(self, test_index, sample_tools):
        """Should include HNSW index information."""
        stats = test_index.get_stats()

        assert "hnsw" in stats
        assert stats["hnsw"]["current_count"] == len(sample_tools)
        assert stats["hnsw"]["max_elements"] >= len(sample_tools)


class TestDynamicUpdates:
    """Test adding and removing tools without rebuild."""

    @pytest.mark.asyncio
    async def test_add_single_tool(self, test_index):
        """Should add a tool to existing index."""
        initial_count = test_index.get_stats()["total_tools"]

        new_tool = ToolDefinition(
            name="test:new_tool",
            description="A newly added test tool",
            category="test",
            server="test",
            parameters={"param": "str"},
            examples=["new tool example"],
            is_core=False,
        )

        success = await test_index.add_single_tool(new_tool)
        assert success is True

        new_count = test_index.get_stats()["total_tools"]
        assert new_count == initial_count + 1

    @pytest.mark.asyncio
    async def test_remove_tool(self, test_index):
        """Should remove a tool from database."""
        initial_count = test_index.get_stats()["total_tools"]

        success = await test_index.remove_tool("test:read_file")
        assert success is True

        new_count = test_index.get_stats()["total_tools"]
        assert new_count == initial_count - 1

    @pytest.mark.asyncio
    async def test_remove_nonexistent_tool(self, test_index):
        """Should return False for nonexistent tool."""
        success = await test_index.remove_tool("test:does_not_exist")
        assert success is False


class TestToolDefinition:
    """Test ToolDefinition data structure."""

    def test_embedding_text_generation(self, sample_tools):
        """Should generate rich embedding text."""
        tool = sample_tools[0]  # read_file
        text = tool.embedding_text()

        # Should include key information
        assert tool.name in text
        assert tool.description in text
        assert tool.category in text
        # Should include examples
        for example in tool.examples:
            assert example in text

    def test_embedding_text_includes_parameters(self, sample_tools):
        """Embedding text should mention parameters."""
        tool = sample_tools[0]
        text = tool.embedding_text()

        for param in tool.parameters.keys():
            assert param in text
