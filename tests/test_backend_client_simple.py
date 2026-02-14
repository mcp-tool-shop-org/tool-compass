"""
Tests for Tool Compass simple backend client module.

Tests JSON-RPC framing, connection management, error handling,
and the public API of SimpleBackendManager.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend_client_simple import (
    SimpleBackendConnection,
    SimpleBackendManager,
    ToolInfo,
    ConnectionStats,
)
from config import CompassConfig, StdioBackend


# =============================================================================
# ToolInfo Tests
# =============================================================================


class TestToolInfo:
    """Test ToolInfo dataclass."""

    def test_basic_construction(self):
        """Should create ToolInfo with all fields."""
        info = ToolInfo("read_file", "bridge:read_file", "Read a file", "bridge", {})
        assert info.name == "read_file"
        assert info.qualified_name == "bridge:read_file"
        assert info.description == "Read a file"
        assert info.server == "bridge"
        assert info.input_schema == {}

    def test_to_dict(self):
        """Should serialize to dict."""
        info = ToolInfo("tool", "srv:tool", "desc", "srv", {"type": "object"})
        d = info.to_dict()
        assert d["name"] == "tool"
        assert d["qualified_name"] == "srv:tool"
        assert d["input_schema"] == {"type": "object"}


# =============================================================================
# ConnectionStats Tests
# =============================================================================


class TestConnectionStats:
    """Test ConnectionStats tracking."""

    def test_record_success(self):
        stats = ConnectionStats()
        stats.record_call(success=True, latency_ms=50.0)
        assert stats.total_calls == 1
        assert stats.failed_calls == 0
        assert stats.avg_latency_ms == 50.0

    def test_record_failure(self):
        stats = ConnectionStats()
        stats.record_call(success=False, latency_ms=100.0)
        assert stats.total_calls == 1
        assert stats.failed_calls == 1

    def test_running_average(self):
        stats = ConnectionStats()
        stats.record_call(True, 100.0)
        stats.record_call(True, 200.0)
        assert stats.total_calls == 2
        # Running average: (100 * 1 + 200) / 2 = 150
        assert stats.avg_latency_ms == 150.0


# =============================================================================
# SimpleBackendManager Tests
# =============================================================================


class TestSimpleBackendManager:
    """Test the public API of SimpleBackendManager."""

    @pytest.fixture
    def config(self):
        return CompassConfig(
            backends={
                "test": StdioBackend(
                    command="python",
                    args=["-m", "test_server"],
                    env={},
                )
            }
        )

    @pytest.fixture
    def manager(self, config):
        return SimpleBackendManager(config)

    def test_is_backend_connected_false_initially(self, manager):
        """Should return False for unknown/unconnected backends."""
        assert manager.is_backend_connected("test") is False
        assert manager.is_backend_connected("nonexistent") is False

    def test_is_backend_connected_true_after_connect(self, manager):
        """Should return True after a mock backend is injected."""
        mock_conn = Mock()
        mock_conn.is_connected = True
        manager._backends["test"] = mock_conn
        assert manager.is_backend_connected("test") is True

    def test_is_backend_connected_false_when_disconnected(self, manager):
        """Should return False if backend exists but is disconnected."""
        mock_conn = Mock()
        mock_conn.is_connected = False
        manager._backends["test"] = mock_conn
        assert manager.is_backend_connected("test") is False

    @pytest.mark.asyncio
    async def test_connect_backend_unknown(self, manager):
        """Should return False for unknown backend names."""
        result = await manager.connect_backend("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_backend_already_connected(self, manager):
        """Should return True immediately if already connected."""
        mock_conn = Mock()
        mock_conn.is_connected = True
        manager._backends["test"] = mock_conn
        result = await manager.connect_backend("test")
        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_connected_delegates(self, manager):
        """ensure_connected should call connect_backend when not connected."""
        manager.connect_backend = AsyncMock(return_value=True)
        result = await manager.ensure_connected("test")
        assert result is True
        manager.connect_backend.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_ensure_connected_skips_when_connected(self, manager):
        """ensure_connected should skip connect when already connected."""
        mock_conn = Mock()
        mock_conn.is_connected = True
        manager._backends["test"] = mock_conn
        manager.connect_backend = AsyncMock()
        result = await manager.ensure_connected("test")
        assert result is True
        manager.connect_backend.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_all(self, manager):
        """Should disconnect all backends and clear state."""
        mock_conn = Mock()
        mock_conn.disconnect = AsyncMock()
        manager._backends["test"] = mock_conn

        await manager.disconnect_all()

        mock_conn.disconnect.assert_called_once()
        assert len(manager._backends) == 0

    def test_get_all_tools_empty(self, manager):
        """Should return empty list with no connected backends."""
        assert manager.get_all_tools() == []

    def test_get_all_tools_aggregates(self, manager):
        """Should collect tools from all connected backends."""
        mock_conn = Mock()
        mock_conn.is_connected = True
        mock_conn.get_tools.return_value = [
            ToolInfo("t1", "test:t1", "Tool 1", "test", {}),
        ]
        manager._backends["test"] = mock_conn

        tools = manager.get_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "t1"

    def test_get_stats_structure(self, manager):
        """Should return well-structured stats dict."""
        stats = manager.get_stats()
        assert "configured_backends" in stats
        assert "connected_backends" in stats
        assert "total_tools" in stats


# =============================================================================
# run_async and SyncEmbedder Loop Safety Tests
# =============================================================================


class TestRunAsyncSafety:
    """Test that run_async / SyncEmbedder work from inside an active loop."""

    def test_run_async_from_sync_context(self):
        """run_async should work when no loop is running."""
        from ui import run_async

        async def simple():
            return 42

        assert run_async(simple()) == 42

    def test_run_async_from_inside_loop(self):
        """run_async should work when called from inside a running loop."""
        from ui import run_async

        async def inner():
            return "hello"

        result = None

        async def outer():
            nonlocal result
            # We're inside a running loop here
            result = run_async(inner())

        asyncio.run(outer())
        assert result == "hello"

    def test_sync_embedder_run_from_inside_loop(self):
        """SyncEmbedder._run should not crash inside an active loop."""
        from embedder import SyncEmbedder

        embedder = SyncEmbedder()

        async def fake_coro():
            return "ok"

        result = None

        async def outer():
            nonlocal result
            result = embedder._run(fake_coro())

        asyncio.run(outer())
        assert result == "ok"


# =============================================================================
# _version.py Tests
# =============================================================================


class TestVersion:
    """Test version resolution."""

    def test_version_is_string(self):
        from _version import __version__

        assert isinstance(__version__, str)

    def test_version_not_zero(self):
        from _version import __version__

        assert __version__ != "0.0.0"

    def test_version_has_dots(self):
        from _version import __version__

        parts = __version__.split(".")
        assert len(parts) >= 2  # at least major.minor

    def test_get_version_function(self):
        from _version import _get_version

        v = _get_version()
        assert isinstance(v, str)
        assert len(v) > 0
