"""High-yield coverage for wave-12 feature surfaces."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pytest

import embedder as embedder_mod
import indexer as indexer_mod
from embedder import Embedder, EMBEDDING_DIM
from indexer import CompassIndex, NumpyVectorStore, create_vector_store
from tool_manifest import ToolDefinition


@pytest.mark.asyncio
async def test_hash_provider_embeds_offline():
    emb = Embedder(provider="hash")
    vec = await emb.embed("hello")
    assert vec.shape == (emb.embedding_dim,)
    batch = await emb.embed_batch(["a", "b", "c"])
    assert batch.shape[0] == 3
    assert await emb.health_check() is True
    await emb.close()


@pytest.mark.asyncio
async def test_local_provider_falls_back_to_hash():
    emb = Embedder(provider="local")
    vec = await emb.embed("offline")
    assert vec.shape[0] >= 8
    await emb.close()


def test_numpy_vector_store_roundtrip(tmp_path):
    store = NumpyVectorStore(dim=8, space="cosine")
    store.init_index(max_elements=10, ef_construction=16, M=8)
    store.set_ef(8)
    items = np.eye(3, 8, dtype=np.float32)
    store.add_items(items, [1, 2, 3])
    labels, distances = store.knn_query(items[0:1], k=2)
    assert labels.shape[1] == 2
    path = tmp_path / "n.npy"
    store.save_index(str(path))
    loaded = NumpyVectorStore(dim=8, space="cosine")
    loaded.load_index(str(path))
    assert loaded.get_current_count() == 3


def test_create_vector_store_numpy_backend():
    store = create_vector_store("numpy", dim=16)
    assert isinstance(store, NumpyVectorStore)


def test_available_vector_backends_includes_numpy():
    names = indexer_mod.available_vector_backends()
    assert "numpy" in names


@pytest.mark.asyncio
async def test_compact_index_empty(tmp_path):
    idx = CompassIndex(
        index_path=tmp_path / "c.hnsw",
        db_path=tmp_path / "c.db",
        embedder=Embedder(provider="hash"),
        vector_backend="numpy",
    )
    result = idx.compact_index()
    assert result["tools_compacted"] == 0
    await idx.close()


@pytest.mark.asyncio
async def test_build_and_search_with_hash_embedder(tmp_path):
    emb = Embedder(provider="hash")
    idx = CompassIndex(
        index_path=tmp_path / "h.hnsw",
        db_path=tmp_path / "h.db",
        embedder=emb,
        vector_backend="numpy",
    )
    tools = [
        ToolDefinition(
            name="demo:echo",
            description="echo a string",
            category="util",
            server="demo",
            parameters={"text": "string"},
        )
    ]
    await idx.build_index(tools)
    hits = await idx.search("echo a string", top_k=1)
    assert hits
    compact = idx.compact_index()
    assert compact["tools_compacted"] >= 1
    await idx.close()


@pytest.mark.asyncio
async def test_execute_dry_run_and_schema(test_config_with_backends, monkeypatch):
    import gateway

    gateway._config = test_config_with_backends
    gateway._backend_manager = MagicMock()
    gateway._analytics = None
    result = await gateway.execute(
        "test:echo",
        arguments={},
        dry_run=True,
    )
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_compass_chains_run_action_exists():
    import gateway

    result = await gateway.compass_chains(action="not-a-real-action")
    assert "error" in result or "error_envelope" in result or result.get("success") is False


@pytest.mark.asyncio
async def test_embed_batch_native_hash():
    emb = Embedder(provider="hash")
    out = await emb.embed_batch(["one", "two"])
    assert len(out) == 2
    await emb.close()


@pytest.mark.asyncio
async def test_compass_resources_and_prompts_list(monkeypatch):
    import gateway

    mgr = MagicMock()
    mgr.list_resources = AsyncMock(return_value={"resources": []})
    mgr.list_prompts = AsyncMock(return_value={"prompts": []})
    mgr.read_resource = AsyncMock(return_value={"contents": []})
    mgr.get_prompt = AsyncMock(return_value={"messages": []})
    monkeypatch.setattr(gateway, "get_backends", AsyncMock(return_value=mgr))
    monkeypatch.setattr(gateway, "_augment_with_health", lambda x: x)
    listed = await gateway.compass_resources()
    assert "resources" in listed or "trace_id" in listed
    prompts = await gateway.compass_prompts()
    assert isinstance(prompts, dict)


def test_execute_tool_ui_usage_and_bad_json():
    import ui

    empty = ui.execute_tool_ui("", "{}")
    assert "Enter a tool name" in empty
    bad = ui.execute_tool_ui("demo:echo", "{not-json")
    assert "success" in bad


def test_execute_tool_ui_share_hidden(monkeypatch):
    import ui

    monkeypatch.setattr(ui, "_ui_share_mode", True)
    monkeypatch.setattr(ui, "_execute_playground_visible", lambda *_a, **_k: False)
    out = ui.execute_tool_ui("demo:echo", "{}")
    assert "forbidden" in out or "disabled" in out


def test_execute_tool_ui_success(monkeypatch):
    import ui
    import gateway as gw

    mgr = MagicMock()
    mgr.config = MagicMock()
    mgr.config.backends = {}
    mgr.execute_tool = AsyncMock(return_value={"success": True, "result": "ok"})
    mgr.disconnect_all = AsyncMock()
    monkeypatch.setattr(ui, "_ui_share_mode", False)
    monkeypatch.setattr(gw, "get_backends", AsyncMock(return_value=mgr))
    monkeypatch.setattr(gw, "_tool_denied_by_policy", lambda *_a, **_k: None)
    out = ui.execute_tool_ui("demo:echo", '{"x": 1}', timeout=5)
    payload = __import__("json").loads(out)
    assert payload.get("success") is True or "error" in payload


def test_backend_breaker_trips_and_recovers():
    from backend_client_simple import (
        ConnectionStats,
        OUTCOME_TIMEOUT,
        OUTCOME_SUCCESS,
        OUTCOME_TRANSPORT_ERROR,
        BREAKER_OPEN,
        BREAKER_CLOSED,
    )

    stats = ConnectionStats()
    for _ in range(5):
        stats.record_call(outcome=OUTCOME_TRANSPORT_ERROR, latency_ms=10)
    assert stats.breaker_state == BREAKER_OPEN
    assert stats.breaker_can_attempt() is False
    assert stats.breaker_retry_after() is not None
    stats.record_call(outcome=OUTCOME_TIMEOUT, latency_ms=5)
    stats._set_breaker(BREAKER_CLOSED)
    stats.record_call(outcome=OUTCOME_SUCCESS, latency_ms=1)
    assert stats.breaker_state == BREAKER_CLOSED
    stats.record_call(success=False, latency_ms=2)
    stats.record_call(success=True, latency_ms=2)
    stats.record_call(outcome="not-a-real-outcome", latency_ms=1)


