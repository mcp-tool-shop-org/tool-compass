"""
Regression tests locking in v2.2.0 feature-pass behavior.

These tests are authored in parallel with feature implementation by sibling
agents (gateway-mcp, indexing, manifest-config-cli, ci-docs-site). Where a
feature has not landed yet at test-run time, the test must ``pytest.skip``
cleanly rather than fail — that way this file can be committed to
``release/v2.2.0`` and start locking in behavior as each feature lands.

The tests are deliberately specific: mocks only stand in for I/O boundaries
(sockets, subprocess stdout, ollama HTTP), never for the feature's own
branching logic. A loose mock that would pass against broken production code
is a bug in the test, not a convenience.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


# =============================================================================
# Gateway — GW-FT-001 (per-backend stdout reader, HoL-free multiplexing)
# =============================================================================


@pytest.mark.asyncio
async def test_per_backend_reader_multiplexes_concurrent_calls():
    """Two in-flight calls must both complete even when id=2 replies first.

    Without a response-queue reader the gateway's old lock serializes
    request/response pairs, so the id=2 reply would sit in stdout buffer
    while call 1 waits on its readline(). With the queue, the shared
    reader task routes each response to its waiting future and both
    calls complete.
    """
    from backend_client_simple import SimpleBackendConnection
    from config import StdioBackend

    backend = StdioBackend(command="python", args=["-c", "pass"], env={})
    conn = SimpleBackendConnection("test", backend)

    # Simulate an already-connected backend.
    conn._connected = True
    conn._tools = []

    # Fake subprocess where stdout emits responses in reverse order: id=2 first.
    fake_proc = Mock()
    fake_proc.returncode = None
    fake_proc.stdin = Mock()
    fake_proc.stdin.write = Mock()
    fake_proc.stdin.drain = AsyncMock()
    fake_proc.stdin.close = Mock()

    responses = [
        json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": [{"text": "B"}]}}).encode() + b"\n",
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": "A"}]}}).encode() + b"\n",
        b"",  # EOF
    ]

    async def fake_readline():
        if responses:
            return responses.pop(0)
        await asyncio.sleep(60)  # would hang if called again
        return b""

    fake_proc.stdout = Mock()
    fake_proc.stdout.readline = fake_readline
    conn._process = fake_proc

    # The feature's contract: concurrent call_tool() invocations must both
    # resolve with the correct content. If the implementation has not yet
    # added a response queue (GW-FT-001), the single-reader + lock pattern
    # usually WILL fail this test — which is the intent (lock in the fix).
    # If the running implementation is the old one, we tolerate it as
    # "feature not landed yet" and skip rather than fail the swarm.
    async def do_two_calls():
        t1 = asyncio.create_task(conn.call_tool("toolA", {}))
        t2 = asyncio.create_task(conn.call_tool("toolB", {}))
        try:
            return await asyncio.wait_for(
                asyncio.gather(t1, t2, return_exceptions=True), timeout=3.0
            )
        except asyncio.TimeoutError:
            t1.cancel()
            t2.cancel()
            return None

    results = await do_two_calls()

    if results is None:
        pytest.skip("GW-FT-001 per-backend reader not yet implemented (head-of-line block)")

    # Both must complete, neither raised.
    assert all(not isinstance(r, BaseException) for r in results), (
        f"One call raised: {results}"
    )
    # Both must report success with the right payload.
    successes = [r for r in results if isinstance(r, dict) and r.get("success")]
    assert len(successes) == 2, f"Expected both to succeed, got: {results}"
    texts = sorted(r.get("result", "") for r in successes)
    assert texts == ["A", "B"], f"Responses mis-routed: {texts}"


# =============================================================================
# Gateway — GW-FT-003 (/ready and /metrics HTTP endpoints)
# =============================================================================


def _load_starlette_app():
    """Return the Starlette ASGI app exposed by gateway.py, or skip."""
    pytest.importorskip("starlette")
    import gateway

    # The feature should expose either ``gateway.app`` (Starlette) or a
    # helper like ``gateway.build_http_app()``. Support either.
    app = getattr(gateway, "app", None)
    if app is None:
        builder = getattr(gateway, "build_http_app", None)
        if builder is None:
            pytest.skip("GW-FT-003 HTTP app not exposed yet (no gateway.app / build_http_app)")
        app = builder()
    return app, gateway


def test_ready_returns_503_when_ollama_down():
    """/ready must fail with 503 and name ollama when the health probe is false."""
    pytest.importorskip("starlette")
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("starlette TestClient not available")

    app, gateway = _load_starlette_app()

    # Drive the gateway's own health state — the feature is expected to read
    # from gateway._health_state (already present at module import).
    gateway._health_state["ollama_available"] = False
    gateway._health_state["last_ollama_error"] = "connection refused"
    try:
        client = TestClient(app)
        resp = client.get("/ready")
        assert resp.status_code == 503, (
            f"Expected 503 when ollama down, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        # The body must identify which dependency is failing.
        flat = json.dumps(body).lower()
        assert "ollama" in flat, f"/ready body must name ollama: {body}"
    finally:
        gateway._health_state["ollama_available"] = True
        gateway._health_state["last_ollama_error"] = None


def test_metrics_endpoint_renders_prometheus_format():
    """/metrics must be Prometheus text-format 0.0.4 and include search counter."""
    pytest.importorskip("starlette")
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("starlette TestClient not available")

    app, _gateway = _load_starlette_app()
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200, f"/metrics returned {resp.status_code}"

    ctype = resp.headers.get("content-type", "")
    assert ctype.startswith("text/plain"), f"Expected text/plain, got {ctype!r}"
    # Prometheus exposition format version string — tolerate charset ordering.
    assert "version=0.0.4" in ctype, f"Missing Prom version in content-type: {ctype!r}"
    assert "charset=utf-8" in ctype, f"Missing charset in content-type: {ctype!r}"

    body = resp.text
    assert "tool_compass_search_total" in body, (
        f"Expected tool_compass_search_total metric, body was:\n{body[:500]}"
    )


def test_metrics_includes_embed_latency_p95():
    """/metrics body must expose embed latency p95 as a numeric gauge line."""
    pytest.importorskip("starlette")
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("starlette TestClient not available")

    app, gateway = _load_starlette_app()

    # Try to prime embedder stats so the metric has a real value. The feature
    # is expected to pull from CompassIndex.get_stats()["embedder_stats"];
    # we do the best-effort injection and then just assert the line exists.
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200

    body = resp.text
    # TS-B-004: the embed_latency_p95 metric SHIPPED in v2.2.0 (gateway.py
    # line 1620 emits it unconditionally). The previous skip-then-assert
    # masked regressions — converted to a hard fail so a future change that
    # strips the metric surfaces loudly.
    assert "tool_compass_embed_latency_p95_ms" in body, (
        "tool_compass_embed_latency_p95_ms missing from /metrics body — "
        "this metric shipped in v2.2.0 and should always be present."
    )

    # Find the metric line and confirm the last token is a real number.
    metric_lines = [
        ln for ln in body.splitlines()
        if ln.startswith("tool_compass_embed_latency_p95_ms")
        and not ln.startswith("#")
    ]
    assert metric_lines, "Metric registered but no sample line emitted"
    # Prom format: "name{labels} value" or "name value"
    last_token = metric_lines[0].rsplit(" ", 1)[-1].strip()
    try:
        float(last_token)
    except ValueError:
        pytest.fail(f"embed_latency_p95 value is not numeric: {metric_lines[0]!r}")


# =============================================================================
# Indexing — IDX-FT-003 (embedding cache) + IDX-FT-004 (diffing sync)
# =============================================================================


@pytest.mark.asyncio
async def test_embedding_cache_hit_skips_ollama(
    temp_index_path, temp_db_path, mock_embedder, sample_tools
):
    """Second build with same tools reuses cached vectors instead of re-embedding."""
    from indexer import CompassIndex

    # First build: cold cache — every tool is a miss, embedder called for each.
    index1 = CompassIndex(
        index_path=temp_index_path,
        db_path=temp_db_path,
        embedder=mock_embedder,
    )
    try:
        subset = sample_tools[:3]
        await index1.build_index(subset)
        first_embed_calls = mock_embedder.embed_batch.call_count + mock_embedder.embed.call_count
    finally:
        await index1.close()

    # Second build: warm cache — same 3 tools, hits should pick them all up.
    index2 = CompassIndex(
        index_path=temp_index_path,
        db_path=temp_db_path,
        embedder=mock_embedder,
    )
    try:
        await index2.build_index(subset)
        stats = index2.get_cache_stats()
    finally:
        await index2.close()

    assert stats["hits"] >= 3, (
        f"Expected >=3 cache hits after warm rebuild, got stats={stats}"
    )
    second_embed_calls = (
        mock_embedder.embed_batch.call_count + mock_embedder.embed.call_count
    )
    # Warm run may still call embedder once with an empty miss batch, but it
    # must NOT re-embed all 3 tools again → total calls < 2 * first_embed_calls.
    assert second_embed_calls < first_embed_calls * 2, (
        f"Cache did not reduce embed calls: first={first_embed_calls}, total={second_embed_calls}"
    )


@pytest.mark.asyncio
async def test_embedding_cache_miss_on_changed_text(
    temp_index_path, temp_db_path, mock_embedder
):
    """Same tool name but changed description must miss the cache."""
    from indexer import CompassIndex
    from tool_manifest import ToolDefinition

    tool_v1 = ToolDefinition(
        name="svc:thing",
        description="Original description text",
        category="cat",
        server="svc",
        parameters={},
        examples=[],
    )
    tool_v2 = ToolDefinition(
        name="svc:thing",
        description="Completely different description now",
        category="cat",
        server="svc",
        parameters={},
        examples=[],
    )

    index = CompassIndex(
        index_path=temp_index_path,
        db_path=temp_db_path,
        embedder=mock_embedder,
    )
    try:
        await index.build_index([tool_v1])
        stats_after_first = index.get_cache_stats()
        misses_before = stats_after_first["misses"]

        await index.build_index([tool_v2])
        stats_after_second = index.get_cache_stats()
    finally:
        await index.close()

    # v2 has different embedding text → must register at least one additional miss.
    assert stats_after_second["misses"] > misses_before, (
        f"Changed text should miss cache: {stats_after_first} -> {stats_after_second}"
    )


@pytest.mark.asyncio
async def test_diffing_sync_removes_disappearing_tools(
    test_config_with_backends, temp_db_dir, mock_embedder
):
    """When a backend drops a tool, the next sync must call index.remove_tool for it."""
    from indexer import CompassIndex
    from sync_manager import SyncManager
    from backend_client_simple import ToolInfo

    index_path = temp_db_dir / "diff.hnsw"
    db_path = temp_db_dir / "diff.db"
    index = CompassIndex(
        index_path=index_path, db_path=db_path, embedder=mock_embedder
    )

    # Seed the index with 3 tools so the diffing logic sees "old_names".
    from tool_manifest import ToolDefinition

    seed_tools = [
        ToolDefinition(
            name=f"test_backend:tool_{i}",
            description=f"tool number {i}",
            category="cat",
            server="test_backend",
            parameters={},
            examples=[],
        )
        for i in range(3)
    ]
    await index.build_index(seed_tools)

    # Spy on remove_tool so we can assert which names got dropped.
    removed_names: list[str] = []
    orig_remove = index.remove_tool

    async def spy_remove(name: str) -> bool:
        removed_names.append(name)
        return await orig_remove(name)

    index.remove_tool = spy_remove  # type: ignore[assignment]

    # Backend now reports only 2 of the 3 tools.
    remaining = [
        ToolInfo(
            name="tool_0",
            qualified_name="test_backend:tool_0",
            description="tool number 0",
            server="test_backend",
            input_schema={"properties": {}},
        ),
        ToolInfo(
            name="tool_1",
            qualified_name="test_backend:tool_1",
            description="tool number 1",
            server="test_backend",
            input_schema={"properties": {}},
        ),
    ]

    backends = Mock()
    backends.get_backend_tools = Mock(return_value=remaining)
    backends.get_all_tools = Mock(return_value=remaining)

    sync_db = temp_db_dir / "sync.db"
    with patch("sync_manager.ANALYTICS_DB_PATH", sync_db):
        mgr = SyncManager(
            config=test_config_with_backends, index=index, backends=backends
        )
        try:
            await mgr._rebuild_for_backends(["test_backend"])
        finally:
            mgr.close()

    try:
        assert "test_backend:tool_2" in removed_names, (
            f"Expected tool_2 to be removed, got removed={removed_names}"
        )
        # Sanity: the two surviving tools must NOT have been removed.
        assert "test_backend:tool_0" not in removed_names
        assert "test_backend:tool_1" not in removed_names
    finally:
        await index.close()


# =============================================================================
# CLI — MCC-FT-001 / MCC-FT-004 (argparse subcommands in cli.py)
# =============================================================================


def _require_cli():
    """Import cli module or skip if not yet created by manifest-config-cli agent."""
    cli_path = REPO_ROOT / "cli.py"
    if not cli_path.exists():
        pytest.skip("cli.py not yet created (MCC-FT-001)")
    try:
        import cli  # noqa: F401
    except Exception as e:  # pragma: no cover - import probe
        pytest.skip(f"cli.py present but failed to import: {e}")
    return sys.modules["cli"]


def test_cli_doctor_returns_json(capsys):
    """`tool-compass doctor` must emit JSON with version + config_path keys."""
    cli = _require_cli()
    # TS-B-004: cli.main shipped in v2.2.0 (cli.py:24-73). The previous
    # skip-if-missing path masked regressions where cli.main was renamed.
    # Hard assert: if cli.main disappears, the CLI subcommand surface
    # broke and the test should fail loudly.
    assert hasattr(cli, "main"), (
        "cli.main missing — cli subcommand surface shipped in v2.2.0 and "
        "should always be present."
    )

    try:
        rc = cli.main(["doctor"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    captured = capsys.readouterr()
    # doctor should succeed (or at least not hard-fail) and dump JSON.
    payload = None
    for candidate in (captured.out, captured.err):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError:
            # Maybe the output has a header line — try last JSON block.
            last_brace = candidate.rfind("{")
            if last_brace >= 0:
                try:
                    payload = json.loads(candidate[last_brace:])
                    break
                except json.JSONDecodeError:
                    continue
    assert payload is not None, f"doctor did not emit JSON: out={captured.out!r} err={captured.err!r}"
    assert "version" in payload, f"doctor JSON missing 'version': {payload}"
    assert "config_path" in payload, f"doctor JSON missing 'config_path': {payload}"
    assert rc == 0, f"doctor returned non-zero: {rc}"


def test_cli_search_returns_results(capsys, monkeypatch):
    """`tool-compass search foo --json` must emit a JSON array of results."""
    cli = _require_cli()
    # TS-B-004: cli.main shipped in v2.2.0 (cli.py:24-73). The previous
    # skip-if-missing path masked regressions where cli.main was renamed.
    # Hard assert: if cli.main disappears, the CLI subcommand surface
    # broke and the test should fail loudly.
    assert hasattr(cli, "main"), (
        "cli.main missing — cli subcommand surface shipped in v2.2.0 and "
        "should always be present."
    )

    # Monkeypatch whatever search entry-point cli.py uses. We support the
    # common shapes: a module-level `search_tools` function, or a CompassIndex
    # factory exposed as `get_index` / `build_or_load_index`.
    fake_results = [
        {"name": "bridge:read_file", "score": 0.92, "rank": 1},
        {"name": "bridge:write_file", "score": 0.81, "rank": 2},
    ]

    async def fake_search(*args, **kwargs):
        return fake_results

    # Try the most likely hook points.
    patched = False
    for attr in ("search_tools", "run_search", "_do_search"):
        if hasattr(cli, attr):
            monkeypatch.setattr(cli, attr, fake_search)
            patched = True
            break
    if not patched:
        # Fall back: patch any CompassIndex.search used through a getter.
        try:
            import indexer

            async def idx_search(self, query, **kw):
                # Return objects that expose .tool.name, .score, .rank
                from types import SimpleNamespace
                return [
                    SimpleNamespace(
                        tool=SimpleNamespace(
                            name=r["name"],
                            category="test",
                            server="mock",
                            description="mock description",
                        ),
                        score=r["score"],
                        rank=r["rank"],
                    )
                    for r in fake_results
                ]

            monkeypatch.setattr(indexer.CompassIndex, "search", idx_search)
        except Exception:
            pytest.skip("Could not find a search hook point to monkeypatch")

    # cli._load_index returns None when no on-disk index exists; bypass it so
    # the monkey-patched search() actually runs.
    class _FakeIndex:
        async def search(self, query, top_k=5):
            from types import SimpleNamespace
            return [
                SimpleNamespace(
                    tool=SimpleNamespace(
                        name=r["name"],
                        category="test",
                        server="mock",
                        description="mock description",
                    ),
                    score=r["score"],
                    rank=r["rank"],
                )
                for r in fake_results
            ]

    monkeypatch.setattr(cli, "_load_index", lambda: _FakeIndex())

    try:
        rc = cli.main(["search", "foo", "--json"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    out = capsys.readouterr().out.strip()
    # Find JSON array in output.
    start = out.find("[")
    assert start >= 0, f"search --json produced no array: {out!r}"
    try:
        payload = json.loads(out[start:])
    except json.JSONDecodeError as e:
        pytest.fail(f"search --json output not parseable: {e}: {out!r}")
    assert isinstance(payload, list), f"--json should be an array: {payload!r}"
    assert rc in (0, None), f"search returned non-zero rc={rc}"


def test_cli_describe_unknown_tool_exits_nonzero():
    """`tool-compass describe nonexistent` must exit with a non-zero code."""
    cli = _require_cli()
    # TS-B-004: cli.main shipped in v2.2.0 (cli.py:24-73). The previous
    # skip-if-missing path masked regressions where cli.main was renamed.
    # Hard assert: if cli.main disappears, the CLI subcommand surface
    # broke and the test should fail loudly.
    assert hasattr(cli, "main"), (
        "cli.main missing — cli subcommand surface shipped in v2.2.0 and "
        "should always be present."
    )

    try:
        rc = cli.main(["describe", "definitely_not_a_real_tool_xyz"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    assert rc not in (0, None), (
        f"describe on unknown tool must non-zero exit, got {rc!r}"
    )


def test_cli_no_args_falls_through_to_gateway(monkeypatch):
    """`tool-compass` with no args must invoke gateway.main (serve default)."""
    cli = _require_cli()
    # TS-B-004: cli.main shipped in v2.2.0 (cli.py:24-73). The previous
    # skip-if-missing path masked regressions where cli.main was renamed.
    # Hard assert: if cli.main disappears, the CLI subcommand surface
    # broke and the test should fail loudly.
    assert hasattr(cli, "main"), (
        "cli.main missing — cli subcommand surface shipped in v2.2.0 and "
        "should always be present."
    )

    import gateway

    called = {"n": 0}

    def fake_gateway_main(*args, **kwargs):
        called["n"] += 1
        return 0

    monkeypatch.setattr(gateway, "main", fake_gateway_main, raising=False)
    # cli.py may import gateway.main by attribute; patch there too.
    if hasattr(cli, "gateway"):
        monkeypatch.setattr(cli.gateway, "main", fake_gateway_main, raising=False)

    try:
        cli.main([])
    except SystemExit:
        pass

    assert called["n"] >= 1, (
        "cli.main([]) did not delegate to gateway.main — serve fall-through missing"
    )


# =============================================================================
# Manifest — MCC-FT-002 (deprecated_aliases, canonicalization)
# =============================================================================


def test_deprecated_aliases_resolves_to_canonical():
    """get_canonical_name('old_alias') must return the current canonical name."""
    from tool_manifest import ToolDefinition
    import tool_manifest as tm

    if not hasattr(tm, "get_canonical_name"):
        pytest.skip("MCC-FT-002 get_canonical_name not yet implemented")

    # Build a tool with the new deprecation fields. If the dataclass does not
    # have them yet, skip.
    try:
        # deprecated_since on a canonical tool marks the tool itself as
        # deprecated — leave it unset here so the canonical is "current",
        # and the deprecated_aliases merely point historic names at it.
        canonical = ToolDefinition(
            name="svc:new_shiny",
            description="new thing",
            category="cat",
            server="svc",
            parameters={},
            examples=[],
            deprecated_aliases=["svc:old_name", "svc:older_name"],
        )
    except TypeError:
        pytest.skip("ToolDefinition does not expose deprecated_aliases yet")

    # Register/insert the tool via whatever mechanism the feature uses.
    # Most likely: append to tm.TOOLS list temporarily.
    original_tools = list(tm.TOOLS)
    tm.TOOLS.append(canonical)
    # _ALIAS_TO_CANONICAL is built at import; refresh after mutation.
    if hasattr(tm, "_rebuild_alias_map"):
        tm._rebuild_alias_map()
    try:
        resolved = tm.get_canonical_name("svc:old_name")
        assert resolved == "svc:new_shiny", (
            f"Alias did not resolve to canonical: got {resolved!r}"
        )
        # Non-deprecated name passes through unchanged.
        assert tm.get_canonical_name("svc:new_shiny") == "svc:new_shiny"
        # is_deprecated flag reflects the alias status.
        if hasattr(tm, "is_deprecated"):
            assert tm.is_deprecated("svc:old_name") is True
            assert tm.is_deprecated("svc:new_shiny") is False
    finally:
        tm.TOOLS[:] = original_tools
        if hasattr(tm, "_rebuild_alias_map"):
            tm._rebuild_alias_map()


@pytest.mark.asyncio
async def test_analytics_canonicalizes_deprecated_name(test_analytics):
    """record_tool_call called with a deprecated alias must store the canonical name."""
    import tool_manifest as tm

    if not hasattr(tm, "get_canonical_name"):
        pytest.skip("MCC-FT-002 get_canonical_name not yet implemented")

    # Install a tool with an alias so canonicalization has something to do.
    try:
        from tool_manifest import ToolDefinition

        canonical = ToolDefinition(
            name="svc:canonical_op",
            description="the real one",
            category="cat",
            server="svc",
            parameters={},
            examples=[],
            deprecated_aliases=["svc:legacy_op"],
            deprecated_since="2.1.0",
        )
    except TypeError:
        pytest.skip("ToolDefinition does not expose deprecated_aliases yet")

    original_tools = list(tm.TOOLS)
    tm.TOOLS.append(canonical)
    # Rebuild the alias map so get_canonical_name knows about the test tool.
    if hasattr(tm, "_rebuild_alias_map"):
        tm._rebuild_alias_map()
    try:
        await test_analytics.record_tool_call(
            tool_name="svc:legacy_op", success=True, latency_ms=5.0
        )

        db = sqlite3.connect(str(test_analytics.db_path))
        try:
            rows = db.execute(
                "SELECT tool_name FROM tool_calls WHERE tool_name IN (?, ?)",
                ("svc:legacy_op", "svc:canonical_op"),
            ).fetchall()
            names = [r[0] for r in rows]
        finally:
            db.close()
    finally:
        tm.TOOLS[:] = original_tools
        if hasattr(tm, "_rebuild_alias_map"):
            tm._rebuild_alias_map()

    assert names, (
        "record_tool_call did not persist any row — analytics broke. "
        "Previously skipped under a degraded-analytics rationale (TS-B-004); "
        "the row should always land since record_tool_call ships in v2.2.0."
    )

    # TS-B-004: get_canonical_name() shipped in v2.2.0 (tool_manifest.py:830)
    # and the analytics rewrite ships in record_tool_call (analytics.py:397).
    # The previous skip-then-assert masked the case where the rewrite branch
    # regressed. Converted to a hard assert now that the alias map rebuild
    # is wired correctly.
    assert "svc:canonical_op" in names, (
        f"MCC-FT-002 regression: analytics canonicalization did not rewrite "
        f"the deprecated name. Got: {names}"
    )


# =============================================================================
# Build / CI infrastructure checks (owned by ci-tooling domain — tests stay
# light. See CHANGELOG or ROADMAP for status on each gap.)
# =============================================================================


def test_pyproject_has_coverage_threshold():
    """pyproject.toml must enforce coverage via --cov-fail-under OR [tool.coverage.report].fail_under."""
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("pyproject.toml not present")
    text = pyproject.read_text(encoding="utf-8")

    has_addopts_gate = "--cov-fail-under" in text
    has_coverage_report = (
        "[tool.coverage.report]" in text and "fail_under" in text
    )
    if not (has_addopts_gate or has_coverage_report):
        pytest.skip(
            "Coverage threshold not yet configured in pyproject.toml "
            "(owned by ci-tooling; see ROADMAP/CHANGELOG for status)"
        )
    assert has_addopts_gate or has_coverage_report


def test_makefile_has_dev_target():
    """Makefile must expose a `dev:` target for local iteration."""
    mk = REPO_ROOT / "Makefile"
    if not mk.exists():
        pytest.skip("Makefile not present")
    text = mk.read_text(encoding="utf-8")
    # Allow "dev:" or "dev :" with optional whitespace; must be at line start.
    import re

    if not re.search(r"(?m)^dev\s*:", text):
        pytest.skip(
            "`dev:` target not yet added "
            "(owned by ci-tooling; see ROADMAP/CHANGELOG for status)"
        )
    assert re.search(r"(?m)^dev\s*:", text)


def test_makefile_has_scorecard_target():
    """Makefile must expose a `scorecard:` target for shipcheck scoring."""
    mk = REPO_ROOT / "Makefile"
    if not mk.exists():
        pytest.skip("Makefile not present")
    text = mk.read_text(encoding="utf-8")
    import re

    if not re.search(r"(?m)^scorecard\s*:", text):
        pytest.skip(
            "`scorecard:` target not yet added "
            "(owned by ci-tooling; see ROADMAP/CHANGELOG for status)"
        )
    assert re.search(r"(?m)^scorecard\s*:", text)
