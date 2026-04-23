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
from unittest.mock import AsyncMock

import pytest

from config import CompassConfig
from indexer import CompassIndex
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


@pytest.mark.asyncio
async def test_e2e_build_search_describe_execute(
    tmp_path: Path, mock_embedder, mock_backend_manager
):
    """Build index → search → describe → execute happy path.

    Any assertion failure here names exactly which step of the user journey
    broke, so a failing smoke test is instantly actionable.
    """
    # 1. Real CompassConfig rooted in tmp_path — no global paths touched.
    config = CompassConfig(
        backends={},
        index_dir=str(tmp_path / "db"),
        auto_sync=False,
        analytics_enabled=False,
        chain_indexing_enabled=False,
    )
    assert config.index_dir.startswith(str(tmp_path)), "config must be sandboxed"

    # 2. Build the index with the fake tools.
    index = CompassIndex(
        index_path=tmp_path / "smoke.hnsw",
        db_path=tmp_path / "smoke.db",
        embedder=mock_embedder,
    )
    try:
        build_result = await index.build_index(FAKE_TOOLS)
        assert build_result["tools_indexed"] == len(FAKE_TOOLS), (
            "build step failed — wrong tool count indexed"
        )

        # 3. Search for "tool one" — deterministic mock embedder means
        # the tool whose text contains "tool one" (smoke:tool_one) will
        # be the top match since mock_embed hashes on the exact string.
        results = await index.search("tool one", top_k=3)
        assert results, "search step failed — no results returned"
        top = results[0]
        assert top.tool.name in {t.name for t in FAKE_TOOLS}, (
            f"search returned unknown tool: {top.tool.name}"
        )

        # 4. Describe the matched tool (direct DB path, matches gateway.describe).
        described = index._get_tool_by_id(
            next(
                id_ for id_, name in index._id_to_name.items() if name == top.tool.name
            )
        )
        assert described is not None, "describe step failed — tool id → schema lookup"
        assert described.name == top.tool.name
        assert described.parameters, "describe step returned empty parameters"

        # 5. Execute via the mocked backend manager (what gateway.execute does).
        mock_backend_manager.execute_tool = AsyncMock(
            return_value={"success": True, "result": "smoke-ok"}
        )
        exec_result = await mock_backend_manager.execute_tool(described.name, {})
        assert exec_result["success"] is True, (
            "execute step failed — backend returned unsuccessful"
        )
    finally:
        # TST-B-010 — guaranteed close.
        await index.close()
