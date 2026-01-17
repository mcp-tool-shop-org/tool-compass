"""
Tests for Tool Compass gateway MCP tools.

Tests the main MCP interface functions: compass, describe, execute.
Based on FastMCP testing patterns: https://gofastmcp.com/patterns/testing
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCompassTool:
    """Test the compass() search tool."""

    @pytest.mark.asyncio
    async def test_compass_basic_search(self, test_index, test_config):
        """Should return search results for a query."""
        # Import after fixtures set up mocks
        from gateway import compass, get_config, _compass_index
        import gateway

        # Inject test fixtures
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._startup_sync_done = True  # Skip sync

        result = await compass(intent="read a file", top_k=3)

        assert "matches" in result
        assert "total_indexed" in result
        assert "hint" in result
        assert len(result["matches"]) <= 3

    @pytest.mark.asyncio
    async def test_compass_with_filters(self, test_index, test_config):
        """Should apply category and server filters."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._startup_sync_done = True

        from gateway import compass

        result = await compass(
            intent="anything",
            top_k=10,
            category="file",
            server="test",
        )

        # All results should match filters
        for match in result["matches"]:
            assert match["category"] == "file"
            assert match["server"] == "test"

    @pytest.mark.asyncio
    async def test_compass_min_confidence(self, test_index, test_config):
        """Should filter results below min_confidence."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._startup_sync_done = True

        from gateway import compass

        result = await compass(
            intent="file operations",
            top_k=10,
            min_confidence=0.5,
        )

        # All results should be above threshold
        for match in result["matches"]:
            assert match["confidence"] >= 0.5

    @pytest.mark.asyncio
    async def test_compass_tokens_saved(self, test_index, test_config):
        """Should calculate token savings."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._startup_sync_done = True

        from gateway import compass

        result = await compass(intent="anything", top_k=3)

        assert "tokens_saved" in result
        assert result["tokens_saved"] >= 0

    @pytest.mark.asyncio
    async def test_compass_no_results(self, test_index, test_config):
        """Should handle no matching results gracefully."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._startup_sync_done = True

        from gateway import compass

        result = await compass(
            intent="file operations",
            category="nonexistent",
        )

        assert result["matches"] == []
        assert "No tools found" in result["hint"]


class TestDescribeTool:
    """Test the describe() tool schema retrieval."""

    @pytest.mark.asyncio
    async def test_describe_existing_tool(self, test_index, test_config):
        """Should return full schema for existing tool."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._backend_manager = Mock()
        gateway._backend_manager.get_tool_schema = Mock(return_value=None)

        from gateway import describe

        result = await describe(tool_name="test:read_file")

        assert "tool" in result
        assert "description" in result
        assert "parameters" in result
        assert result["tool"] == "test:read_file"

    @pytest.mark.asyncio
    async def test_describe_nonexistent_tool(self, test_index, test_config):
        """Should return error for nonexistent tool."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._backend_manager = Mock()
        gateway._backend_manager.get_tool_schema = Mock(return_value=None)

        from gateway import describe

        result = await describe(tool_name="test:does_not_exist")

        assert "error" in result
        assert "hint" in result


class TestExecuteTool:
    """Test the execute() tool proxy."""

    @pytest.mark.asyncio
    async def test_execute_success(self, test_config):
        """Should proxy tool execution to backend."""
        import gateway

        # Mock backend manager
        mock_manager = Mock()
        mock_manager._backends = {"test": Mock(is_connected=True)}
        mock_manager.connect_backend = AsyncMock(return_value=True)
        mock_manager.execute_tool = AsyncMock(return_value={"success": True, "data": "result"})

        gateway._backend_manager = mock_manager
        gateway._config = test_config
        gateway._analytics = None

        from gateway import execute

        result = await execute(
            tool_name="test:read_file",
            arguments={"filepath": "/tmp/test.txt"},
        )

        assert result["success"] is True
        mock_manager.execute_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_backend_connection_failure(self, test_config):
        """Should handle backend connection failures."""
        import gateway

        mock_manager = Mock()
        mock_manager._backends = {}
        mock_manager.connect_backend = AsyncMock(return_value=False)

        gateway._backend_manager = mock_manager
        gateway._config = test_config
        gateway._analytics = None

        from gateway import execute

        result = await execute(tool_name="test:read_file")

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_with_analytics(self, test_config, test_analytics):
        """Should record tool execution in analytics."""
        import gateway

        mock_manager = Mock()
        mock_manager._backends = {"test": Mock(is_connected=True)}
        mock_manager.execute_tool = AsyncMock(return_value={"success": True})

        gateway._backend_manager = mock_manager
        gateway._config = test_config
        gateway._analytics = test_analytics

        from gateway import execute

        await execute(tool_name="test:tool", arguments={})

        # Analytics should have recorded the call
        summary = await test_analytics.get_analytics_summary("1h")
        assert summary["tool_calls"]["total"] >= 1


class TestCategoriesAndStatus:
    """Test utility tools."""

    @pytest.mark.asyncio
    async def test_compass_categories(self, test_index, test_config):
        """Should return category and server breakdown."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config

        from gateway import compass_categories

        result = await compass_categories()

        assert "categories" in result
        assert "servers" in result
        assert "total_tools" in result
        assert result["total_tools"] > 0

    @pytest.mark.asyncio
    async def test_compass_status(self, test_index, test_config):
        """Should return comprehensive status."""
        import gateway
        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._backend_manager = Mock()
        gateway._backend_manager.get_stats = Mock(return_value={"connected": 0})

        from gateway import compass_status

        result = await compass_status()

        assert "index" in result
        assert "backends" in result
        assert "config" in result


class TestSingletonInitialization:
    """Test async singleton initialization patterns."""

    @pytest.mark.asyncio
    async def test_get_index_creates_once(self, temp_index_path, temp_db_path, mock_embedder, sample_tools):
        """get_index() should only create index once."""
        import gateway

        # Reset global state
        gateway._compass_index = None

        # Create a pre-built index
        from indexer import CompassIndex
        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )
        await index.build_index(sample_tools)

        # Inject the pre-built index
        gateway._compass_index = index

        # Multiple calls should return same instance
        from gateway import get_index
        idx1 = await get_index()
        idx2 = await get_index()

        assert idx1 is idx2

        await index.close()

    @pytest.mark.asyncio
    async def test_concurrent_initialization_safety(self, temp_index_path, temp_db_path, mock_embedder, sample_tools):
        """Concurrent get_index() calls should not create duplicates."""
        import asyncio
        import gateway

        # Build index first
        from indexer import CompassIndex
        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )
        await index.build_index(sample_tools)
        gateway._compass_index = index

        from gateway import get_index

        # Simulate concurrent calls
        results = await asyncio.gather(
            get_index(),
            get_index(),
            get_index(),
        )

        # All should return same instance
        assert all(r is results[0] for r in results)

        await index.close()
