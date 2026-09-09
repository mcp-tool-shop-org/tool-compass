"""
End-to-end smoke test (TST-B-008).

The "first pytest run is informative" test — exercises the full user path
from empty directory to a successful tool execution, with only the
external Ollama and MCP backends mocked. If this test fails, something
fundamental is wrong — and the failure message (helped by descriptive
assertions below) should tell the operator WHICH step broke.

Kept intentionally tight (under 50 lines of actual test logic).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_client_simple import SimpleBackendManager
from config import CompassConfig, StdioBackend
from indexer import CompassIndex
from tests.golden_set.deterministic_embedder import build_deterministic_embedder
from tool_manifest import ToolDefinition


FAKE_TOOLS = [
    ToolDefinition(
        name="smoke:tool_one",
        description="The first smoke-test tool — reads files",
        category="file",
        server="smoke",
        parameters={"path": "str"},
        examples=["read a file", "open document", "tool one"],
        is_core=True,
    ),
    ToolDefinition(
        name="smoke:tool_two",
        description="The second smoke-test tool — writes files",
        category="file",
        server="smoke",
        parameters={"path": "str", "content": "str"},
        examples=["write a file", "save content", "tool two"],
        is_core=False,
    ),
    ToolDefinition(
        name="smoke:tool_three",
        description="The third smoke-test tool — generates images",
        category="ai",
        server="smoke",
        parameters={"prompt": "str"},
        examples=["generate image", "text to image", "tool three"],
        is_core=False,
    ),
]


class _RecordingConn:
    """Stub backend connection that records the qualified name it was given.

    SimpleBackendManager.execute_tool splits `server:tool` and calls
    ``call_tool(bare_name, arguments)``. Reconstruct the qualified name
    so the smoke path can assert routing, not just a canned success dict.
    """

    def __init__(self, server_name: str = "smoke"):
        self.name = server_name
        self.is_connected = True
        self.qualified_names: list[str] = []

    async def call_tool(self, tool_name, arguments):
        self.qualified_names.append(f"{self.name}:{tool_name}")
        return {"success": True, "result": "smoke-ok", "arguments": arguments}


@pytest.mark.asyncio
async def test_e2e_build_search_describe_execute(tmp_path: Path):
    """Build index → search → describe → execute happy path.

    Any assertion failure here names exactly which step of the user journey
    broke, so a failing smoke test is instantly actionable.
    """
    # 1. Real CompassConfig rooted in tmp_path — no global paths touched.
    config = CompassConfig(
        backends={"smoke": StdioBackend(command="true", args=[], env={})},
        index_dir=str(tmp_path / "db"),
        auto_sync=False,
        analytics_enabled=False,
        chain_indexing_enabled=False,
    )
    assert config.index_dir.startswith(str(tmp_path)), "config must be sandboxed"

    # 2. Build the index with the fake tools + golden deterministic embedder.
    # Concept-basis vectors make "read a file" rank smoke:tool_one first
    # (read+file overlap); the hash()-salted mock_embedder prefixes
    # embed_query with `search_query:` so ranking was coincidental.
    embedder = build_deterministic_embedder()
    index = CompassIndex(
        index_path=tmp_path / "smoke.hnsw",
        db_path=tmp_path / "smoke.db",
        embedder=embedder,
    )
    try:
        build_result = await index.build_index(FAKE_TOOLS)
        assert build_result["tools_indexed"] == len(FAKE_TOOLS), (
            "build step failed — wrong tool count indexed"
        )

        # 3. Search — golden embedder, exact top hit (not "any of FAKE_TOOLS").
        results = await index.search("read a file", top_k=3)
        assert results, "search step failed — no results returned"
        top = results[0]
        assert top.tool.name == "smoke:tool_one", (
            f"search step failed — expected smoke:tool_one on top, got {top.tool.name}"
        )

        # 4. Describe the matched tool (direct DB path, matches gateway.describe).
        described = index._get_tool_by_id(
            next(
                id_ for id_, name in index._id_to_name.items() if name == top.tool.name
            )
        )
        assert described is not None, "describe step failed — tool id → schema lookup"
        assert described.name == "smoke:tool_one"
        assert described.parameters, "describe step returned empty parameters"

        # 5. Execute via SimpleBackendManager against a stub connection that
        # records the qualified name. Assigning AsyncMock.return_value and
        # awaiting that same mock cannot fail.
        conn = _RecordingConn("smoke")
        manager = SimpleBackendManager(config)
        manager._backends["smoke"] = conn
        manager._tool_index[described.name] = "smoke"
        exec_result = await manager.execute_tool(described.name, {})
        assert conn.qualified_names == ["smoke:tool_one"], (
            f"execute step failed — stub saw {conn.qualified_names!r}"
        )
        assert exec_result["success"] is True, (
            "execute step failed — backend returned unsuccessful"
        )
    finally:
        # TST-B-010 — guaranteed close.
        await index.close()
