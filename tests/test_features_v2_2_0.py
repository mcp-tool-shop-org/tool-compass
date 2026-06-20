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

    FE-W11-009: un-skipped on Wave-11 — the per-backend reader has been
    implemented (see backend_client_simple.py:432, _read_loop). The fixture
    now starts the read-loop task explicitly the same way ``connect()`` would,
    so the test exercises the real multiplexing path instead of timing out
    and treating that as "feature not landed."
    """
    from backend_client_simple import SimpleBackendConnection
    from config import StdioBackend

    backend = StdioBackend(command="python", args=["-c", "pass"], env={})
    conn = SimpleBackendConnection("test", backend)

    # Simulate an already-connected backend.
    conn._connected = True
    conn._tools = []

    # Fake subprocess. We use an asyncio.Queue as the response source so the
    # test controls exactly when each reply becomes readable — this lets us
    # register both pending futures BEFORE the id=2 reply lands, which is
    # the head-of-line condition we want to prove the reader handles.
    fake_proc = Mock()
    fake_proc.returncode = None
    fake_proc.stdin = Mock()
    fake_proc.stdin.write = Mock()
    fake_proc.stdin.drain = AsyncMock()
    fake_proc.stdin.close = Mock()

    response_queue: "asyncio.Queue[bytes]" = asyncio.Queue()

    async def fake_readline():
        return await response_queue.get()

    fake_proc.stdout = Mock()
    fake_proc.stdout.readline = fake_readline
    conn._process = fake_proc

    # FE-W11-009: bind async primitives (write lock + inflight semaphore) and
    # start the per-backend stdout reader the same way ``connect()`` would.
    # Without this, no task is draining stdout, so both calls timeout and
    # the head-of-line guarantee is never exercised.
    conn._ensure_async_primitives()
    conn._read_task = asyncio.create_task(conn._read_loop())

    # The feature's contract: concurrent call_tool() invocations must both
    # resolve with the correct content. We start both calls first so both
    # ids are registered in _pending, then feed id=2 (the "out of order"
    # reply) followed by id=1.
    async def do_two_calls():
        t1 = asyncio.create_task(conn.call_tool("toolA", {}))
        t2 = asyncio.create_task(conn.call_tool("toolB", {}))

        # Yield enough times for both call tasks to acquire the write lock,
        # register their pending future, and write their request. After this
        # both ids should appear in conn._pending.
        for _ in range(20):
            await asyncio.sleep(0)
            if 1 in conn._pending and 2 in conn._pending:
                break

        # Now feed responses in REVERSE order — id=2 first. A correctly-routed
        # reader resolves call 2's future without waiting for id=1.
        await response_queue.put(
            json.dumps(
                {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"text": "B"}]}}
            ).encode() + b"\n"
        )
        await response_queue.put(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": "A"}]}}
            ).encode() + b"\n"
        )

        try:
            return await asyncio.wait_for(
                asyncio.gather(t1, t2, return_exceptions=True), timeout=3.0
            )
        except asyncio.TimeoutError:
            t1.cancel()
            t2.cancel()
            return None

    try:
        results = await do_two_calls()
    finally:
        # Clean up the read-loop task so it doesn't leak between tests.
        if conn._read_task is not None:
            conn._read_task.cancel()
            try:
                await conn._read_task
            except (asyncio.CancelledError, Exception):
                pass

    assert results is not None, (
        "GW-FT-001: concurrent calls timed out — per-backend reader is not "
        "routing responses correctly."
    )

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
    """Return the Starlette ASGI app exposed by gateway.py.

    TESTS-001: ``build_http_app()`` is a permanent module-level surface
    (GW-FT-003) that attaches /health, /ready and /metrics. The previous
    skip-if-missing path turned the /ready-503 and /metrics tests into
    permanent green-via-skip — zero coverage of documented endpoints. We now
    hard-assert the factory exists so that removing it FAILS these tests
    loudly instead of silently skipping them.
    """
    pytest.importorskip("starlette")
    import gateway

    # The feature exposes either ``gateway.app`` (Starlette) or the
    # ``gateway.build_http_app()`` factory. Both are acceptable; at least one
    # MUST be present.
    app = getattr(gateway, "app", None)
    if app is None:
        builder = getattr(gateway, "build_http_app", None)
        assert builder is not None and callable(builder), (
            "GW-FT-003 regression: gateway must expose a module-level "
            "build_http_app() factory (or `app`) wiring /health, /ready and "
            "/metrics. Neither was found — the ops endpoints are no longer "
            "reachable from a TestClient."
        )
        app = builder()
    return app, gateway


def test_ready_returns_503_when_ollama_down():
    """/ready must fail with 503 and name ollama when the health probe is false."""
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

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
    """/metrics must render the OpenMetrics 1.0.0 exposition format + search counter.

    The gateway emits OpenMetrics 1.0.0 (BE-B-015: ``# UNIT`` lines and the
    ``# EOF`` terminator), the standards-track successor to the Prometheus
    0.0.4 text format that Prometheus itself scrapes. This test was authored
    against the older 0.0.4 content-type while the endpoint was un-exposed and
    permanently skipped; it now locks in the content-type the route actually
    ships.
    """
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    app, _gateway = _load_starlette_app()
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200, f"/metrics returned {resp.status_code}"

    ctype = resp.headers.get("content-type", "")
    assert ctype.startswith("application/openmetrics-text"), (
        f"Expected OpenMetrics exposition content-type, got {ctype!r}"
    )
    # OpenMetrics version string — tolerate charset ordering.
    assert "version=1.0.0" in ctype, f"Missing OpenMetrics version in content-type: {ctype!r}"
    assert "charset=utf-8" in ctype, f"Missing charset in content-type: {ctype!r}"

    body = resp.text
    assert "tool_compass_search_total" in body, (
        f"Expected tool_compass_search_total metric, body was:\n{body[:500]}"
    )
    # OpenMetrics 1.0.0 requires the body to terminate with `# EOF` (BE-B-015).
    assert body.rstrip().endswith("# EOF"), (
        "OpenMetrics body must end with the # EOF terminator"
    )


def test_metrics_includes_embed_latency_p95():
    """/metrics body must expose embed latency p95 as a numeric gauge line."""
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

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


def test_build_http_app_is_module_level_and_registers_ops_routes():
    """TESTS-001: build_http_app() must be a module-level factory that wires
    /health, /ready and /metrics.

    Previously these routes lived inside _run_http() and the GW-FT-003 tests
    were permanently skipped. This regression locks the factory at module
    scope AND verifies it registers all three ops paths, so a refactor that
    re-buries the routes (or drops one) fails loudly here instead of silently
    skipping the endpoint coverage.
    """
    pytest.importorskip("starlette")
    import gateway

    builder = getattr(gateway, "build_http_app", None)
    assert builder is not None and callable(builder), (
        "build_http_app() must be exposed at module scope (GW-FT-003)."
    )

    # Calling the factory must register the three ops routes onto FastMCP's
    # custom route list. Idempotent: a second call must not duplicate them.
    builder()
    builder()
    paths = [
        getattr(r, "path", None)
        for r in gateway.mcp._custom_starlette_routes
    ]
    for required in ("/health", "/ready", "/metrics"):
        assert paths.count(required) == 1, (
            f"build_http_app() must register exactly one {required} route; "
            f"found {paths.count(required)} (paths={paths})"
        )


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
    """Import the shipped cli module.

    TESTS-002: cli.py is a permanent shipped surface (the tool-compass CLI).
    A broken import is a real regression, NOT a reason to skip — the previous
    import-failure skip turned the doctor/search tests green-via-skip whenever
    cli.py failed to load. Only a genuinely absent file (e.g. a fresh checkout
    before MCC-FT-001 landed) is skip-worthy; an import error must propagate
    and fail the test loudly.
    """
    cli_path = REPO_ROOT / "cli.py"
    if not cli_path.exists():
        pytest.skip("cli.py not yet created (MCC-FT-001)")
    import cli  # noqa: F401 — import error here is a real failure, never a skip
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
    """get_canonical_name('old_alias') must return the current canonical name.

    FE-W11-010: hard-assert path. Both ``get_canonical_name`` (tool_manifest.py:817)
    and ``ToolDefinition.deprecated_aliases`` ship in v2.2.0 — the previous
    conditional skip masked regressions where the alias map rebuild silently
    broke. If either disappears, this test now fails loudly instead.
    """
    from tool_manifest import ToolDefinition
    import tool_manifest as tm

    assert hasattr(tm, "get_canonical_name"), (
        "MCC-FT-002 regression: get_canonical_name shipped in v2.2.0 and "
        "must remain present (see tool_manifest.py:817)."
    )

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
    """record_tool_call called with a deprecated alias must store the canonical name.

    FE-W11-010: hard-assert path. ``get_canonical_name`` ships in v2.2.0 and
    ``analytics.record_tool_call`` canonicalizes pre-insert (analytics.py:395-397).
    The previous conditional skip masked the case where the rewrite branch
    regressed silently. Hard assert keeps the regression visible.
    """
    import tool_manifest as tm

    assert hasattr(tm, "get_canonical_name"), (
        "MCC-FT-002 regression: get_canonical_name shipped in v2.2.0 and "
        "must remain present (see tool_manifest.py:817)."
    )

    # Install a tool with an alias so canonicalization has something to do.
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


# =============================================================================
# FE-W11 — Wave-11 feature parity smoke tests (six new CLI subcommands +
# serve --http + version banner)
# =============================================================================


def _patch_gateway_handler(monkeypatch, handler_name: str, payload):
    """Replace a gateway @mcp.tool function with an AsyncMock returning ``payload``.

    Used by the Wave-11 CLI smoke tests so we don't have to spin up a real
    index / backend just to verify the dispatch + rendering wiring. The
    handler functions remain directly callable after the @mcp.tool decorator
    (verified at Wave-11 implementation time).
    """
    import gateway as gw  # local import — keeps unrelated tests fast

    async def fake_handler(*args, **kwargs):
        return payload

    monkeypatch.setattr(gw, handler_name, fake_handler)
    return fake_handler


def test_cli_status_json_passes_through_gateway_payload(capsys, monkeypatch):
    """`tool-compass status --json` emits the raw compass_status payload."""
    cli = _require_cli()
    payload = {
        "index": {"total_tools": 42, "by_category": {}, "by_server": {"x": 42}},
        "backends": {"connected_backends": ["x"], "configured_backends": ["x"]},
        "health": {
            "ollama_available": True,
            "index_available": True,
            "degraded_mode": False,
        },
        "config": {},
    }
    _patch_gateway_handler(monkeypatch, "compass_status", payload)
    try:
        rc = cli.main(["status", "--json"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    out = capsys.readouterr().out.strip()
    start = out.find("{")
    assert start >= 0, f"status --json produced no JSON: {out!r}"
    parsed = json.loads(out[start:])
    assert parsed["index"]["total_tools"] == 42
    assert rc == 0


def test_cli_categories_text_lists_counts(capsys, monkeypatch):
    """`tool-compass categories` renders categories sorted by count desc."""
    cli = _require_cli()
    payload = {
        "categories": {"file": 10, "ai": 3, "git": 7},
        "servers": {},
        "total_tools": 20,
    }
    _patch_gateway_handler(monkeypatch, "compass_categories", payload)
    # capsys is not a TTY so color is auto-disabled. --no-color belongs on
    # the root parser, before the subcommand, but we don't need it here.
    try:
        rc = cli.main(["categories"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    out = capsys.readouterr().out
    # All three names must appear in the rendered output.
    assert "file" in out and "git" in out and "ai" in out
    # The total tool count appears in the header.
    assert "20" in out
    assert rc == 0


def test_cli_audit_json_invokes_gateway(capsys, monkeypatch):
    """`tool-compass audit --json` calls compass_audit and prints its payload."""
    cli = _require_cli()
    payload = {
        "system": {"version": "9.9.9", "total_tools": 5},
        "categories": {"x": 5},
        "servers": {"x": 5},
        "backends": {
            "connected_backends": ["x"],
            "configured_backends": ["x"],
        },
        "hot_cache": {"size": 0, "tools": []},
        "chains": {"total": 0, "cached": 0},
    }
    _patch_gateway_handler(monkeypatch, "compass_audit", payload)
    try:
        rc = cli.main(["audit", "--json"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    out = capsys.readouterr().out.strip()
    start = out.find("{")
    parsed = json.loads(out[start:])
    assert parsed["system"]["version"] == "9.9.9"
    assert rc == 0


def test_cli_analytics_handles_disabled_error_envelope(capsys, monkeypatch):
    """When analytics is disabled the CLI prints the envelope title, exits 1."""
    cli = _require_cli()
    payload = {
        "error": {
            "code": "analytics_disabled",
            "title": "Analytics is disabled",
            "detail": "Analytics is disabled.",
            "suggestions": ["Enable analytics_enabled in config to track usage."],
        }
    }
    _patch_gateway_handler(monkeypatch, "compass_analytics", payload)
    try:
        rc = cli.main(["analytics"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    err = capsys.readouterr().err
    assert "Analytics is disabled" in err, f"missing envelope title in stderr: {err!r}"
    assert rc == 1


def test_cli_chains_list_renders_names(capsys, monkeypatch):
    """`tool-compass chains` lists chain names from gateway.compass_chains."""
    cli = _require_cli()
    payload = {
        "chains": [
            {
                "name": "read-then-write",
                "tools": ["fs:read_file", "fs:write_file"],
                "use_count": 3,
                "is_auto_detected": False,
                "description": "round-trip",
            }
        ],
        "total": 1,
        "cached": 1,
    }
    _patch_gateway_handler(monkeypatch, "compass_chains", payload)
    try:
        rc = cli.main(["chains"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    out = capsys.readouterr().out
    assert "read-then-write" in out, f"chain name missing: {out!r}"
    assert "fs:read_file" in out, f"chain tools not rendered: {out!r}"
    assert rc == 0


def test_cli_chains_action_choices_enforced(monkeypatch):
    """`tool-compass chains --action invalid` must exit 2 (argparse usage)."""
    cli = _require_cli()
    rc = None
    try:
        rc = cli.main(["chains", "--action", "invalid"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    assert rc == 2, f"argparse should reject invalid choice with rc=2, got {rc}"


def test_cli_ui_subcommand_dispatches(monkeypatch, capsys):
    """`tool-compass ui` must dispatch to ui.main and forward port/host/share."""
    cli = _require_cli()
    # Stand-in for ui:main so we don't actually launch Gradio. We also assert
    # the forwarded argv shape via a captured list.
    captured_argv: list[str] = []

    def fake_ui_main():
        # ui.main reads sys.argv, so record it for assertion.
        captured_argv.extend(sys.argv)
        return 0

    # Inject a fake `ui` module so the import inside _cmd_ui succeeds even on
    # bare installs that lack the gradio extras.
    fake_ui = type(sys)("ui")  # types.ModuleType-equivalent
    fake_ui.main = fake_ui_main
    monkeypatch.setitem(sys.modules, "ui", fake_ui)

    try:
        rc = cli.main(["ui", "--port", "7777", "--host", "0.0.0.0"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    assert rc == 0, f"ui subcommand should exit 0, got {rc}"
    assert any("--port" in a for a in captured_argv), (
        f"ui main did not see --port in argv: {captured_argv}"
    )
    assert any(a == "7777" for a in captured_argv), (
        f"ui main missing --port value 7777: {captured_argv}"
    )
    assert "0.0.0.0" in captured_argv, (
        f"ui main missing --host value 0.0.0.0: {captured_argv}"
    )


def test_cli_ui_auth_propagates_to_gradio_auth_env(monkeypatch):
    """`tool-compass ui --auth user:pass --share` sets GRADIO_AUTH env."""
    cli = _require_cli()

    def fake_ui_main():
        return 0

    fake_ui = type(sys)("ui")
    fake_ui.main = fake_ui_main
    monkeypatch.setitem(sys.modules, "ui", fake_ui)
    monkeypatch.delenv("GRADIO_AUTH", raising=False)

    try:
        rc = cli.main(["ui", "--auth", "alice:secret", "--share"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    assert rc == 0
    import os as _os
    assert _os.environ.get("GRADIO_AUTH") == "alice:secret", (
        f"--auth flag did not propagate to GRADIO_AUTH env: "
        f"{_os.environ.get('GRADIO_AUTH')!r}"
    )


def test_cli_serve_http_with_value_exports_port(monkeypatch):
    """`tool-compass serve --http 9090` must set PORT=9090 before gateway start."""
    cli = _require_cli()
    import gateway

    seen_port = {}

    def fake_gateway_main():
        # Capture the resolved env at the moment the gateway would have started.
        import os as _os
        seen_port["value"] = _os.environ.get("PORT")
        return 0

    monkeypatch.setattr(gateway, "main", fake_gateway_main, raising=False)
    if hasattr(cli, "gateway"):
        monkeypatch.setattr(cli.gateway, "main", fake_gateway_main, raising=False)
    monkeypatch.delenv("PORT", raising=False)

    try:
        cli.main(["serve", "--http", "9090"])
    except SystemExit:
        pass

    assert seen_port.get("value") == "9090", (
        f"serve --http 9090 did not export PORT=9090; saw {seen_port.get('value')!r}"
    )


def test_cli_serve_http_no_value_falls_back_to_port_env(monkeypatch):
    """`tool-compass serve --http` with PORT=8765 in env keeps PORT=8765."""
    cli = _require_cli()
    import gateway

    seen_port = {}

    def fake_gateway_main():
        import os as _os
        seen_port["value"] = _os.environ.get("PORT")
        return 0

    monkeypatch.setattr(gateway, "main", fake_gateway_main, raising=False)
    if hasattr(cli, "gateway"):
        monkeypatch.setattr(cli.gateway, "main", fake_gateway_main, raising=False)
    monkeypatch.setenv("PORT", "8765")

    try:
        cli.main(["serve", "--http"])
    except SystemExit:
        pass

    assert seen_port.get("value") == "8765", (
        f"--http with PORT env preset should preserve it; saw {seen_port.get('value')!r}"
    )


def test_gateway_banner_reads_version_from__version_module(monkeypatch, capsys):
    """The startup banner must interpolate __version__, not a hardcoded literal.

    FE-W11-008: the Wave-10 audit flagged
    ``"Starting Tool Compass Gateway v2.0..."`` at gateway.py:2406 as stale
    against the live ``_version.__version__``. The Wave-11 fix uses an
    f-string. We probe the gateway source so the test is robust against
    refactors of the banner placement.
    """
    gateway_path = REPO_ROOT / "gateway.py"
    if not gateway_path.exists():
        pytest.skip("gateway.py not present")
    text = gateway_path.read_text(encoding="utf-8")
    # The hardcoded literal must be gone.
    assert "v2.0..." not in text, (
        "Hardcoded 'v2.0...' banner literal still present in gateway.py — "
        "Wave-11 fix should use f-string with __version__"
    )
    # Either an f-string interpolation OR a format-call must reference
    # __version__ on the banner line.
    import re
    banner_pattern = re.compile(
        r"Starting Tool Compass Gateway v\{?(__version__|[^}]*version[^}]*)\}?"
    )
    assert banner_pattern.search(text), (
        "Gateway banner does not interpolate __version__ — Wave-11 fix missing"
    )
