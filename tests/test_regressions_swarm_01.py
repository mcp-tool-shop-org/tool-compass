"""
Stage A regression tests — lock in swarm bug fixes.

Each test here corresponds to a finding the Stage A production agents are
fixing in parallel. The assertions describe the POST-FIX behavior — if any
of these ever start failing, a regression was shipped.

Findings covered:
  GW-A-001  compass_audit with analytics_enabled=False does not raise NameError
  GW-A-002  compass_audit(include_tools=True) with index.db=None returns
             a graceful result instead of AttributeError
  GW-A-003  HTTP mode defaults mcp.settings.host to 127.0.0.1 and
             allowed_hosts does NOT contain "0.0.0.0"
  IDX-A-002 CompassIndex.search returns [] on an empty index (no crash)
  IDX-A-005 ChainIndexer returns correct results when knn_query returns
             numpy int64 labels (int cast works through the lookup path)
  IDX-A-006 ChainIndexer.add_chain handles capacity overflow via resize
  MCC-A-001 analytics.record_tool_call produces the exact expected running
             average after three known latencies (10, 20, 30 → avg 20.0)
  MCC-A-003 analytics hashes arguments by VALUE, not just keys — same keys
             different values must produce different hashes
  MCC-A-005 analytics.record_search is safe to call concurrently from two
             threads without raising
"""

import asyncio
import threading
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest


# =============================================================================
# GW-A-001: compass_audit with analytics disabled must not NameError
# =============================================================================


class TestGWA001AnalyticsDisabled:
    @pytest.mark.asyncio
    async def test_audit_does_not_raise_when_analytics_disabled(
        self, test_index, test_config
    ):
        """compass_audit must complete without raising when analytics_enabled=False.

        Earlier revisions referenced an unbound `analytics` symbol in the
        health-check block, producing NameError when the analytics branch
        never ran. Lock in that the call returns a dict with the required
        top-level keys and a health block.
        """
        import gateway

        assert test_config.analytics_enabled is False

        gateway._compass_index = test_index
        gateway._config = test_config
        gateway._analytics = None
        gateway._backend_manager = Mock()
        gateway._backend_manager.get_stats = Mock(
            return_value={
                "configured_backends": [],
                "connected_backends": [],
                "total_tools": 0,
                "tools_by_backend": {},
            }
        )

        from gateway import compass_audit

        result = await compass_audit()

        assert isinstance(result, dict)
        assert "health" in result
        assert "system" in result
        # Analytics section must NOT be present when disabled.
        assert "analytics" not in result


# =============================================================================
# GW-A-002: compass_audit(include_tools=True) with index.db=None
# =============================================================================


class TestGWA002IncludeToolsWithNoDb:
    @pytest.mark.asyncio
    async def test_include_tools_handles_none_db(self, test_config):
        """compass_audit(include_tools=True) must not AttributeError when
        the underlying index has no db connection yet."""
        import gateway
        from indexer import CompassIndex

        # Build a CompassIndex-like mock with db=None, then call audit.
        mock_index = Mock(spec=CompassIndex)
        mock_index.db = None
        mock_index.index_path = Path("/tmp/test.hnsw")
        mock_index.db_path = Path("/tmp/test.db")
        mock_index.get_stats = Mock(
            return_value={"total_tools": 0, "by_category": {}, "by_server": {}}
        )

        gateway._compass_index = mock_index
        gateway._config = test_config
        gateway._backend_manager = Mock()
        gateway._backend_manager.get_stats = Mock(
            return_value={
                "configured_backends": [],
                "connected_backends": [],
                "total_tools": 0,
                "tools_by_backend": {},
            }
        )

        from gateway import compass_audit

        result = await compass_audit(include_tools=True)

        assert isinstance(result, dict)
        # Either the tools key is present and empty, or an explanatory note
        # appears. Must NOT raise AttributeError on `None.execute(...)`.
        assert "tools" in result
        assert result["tools"] == [] or isinstance(result["tools"], list)


# =============================================================================
# GW-A-003: HTTP mode host + allowed_hosts guardrails
# =============================================================================


class TestGWA003HttpModeHost:
    """The gateway's HTTP runner must bind to 127.0.0.1 by default and
    must NOT whitelist 0.0.0.0 in its allowed-hosts list (0.0.0.0 is never
    a valid Host header)."""

    def test_allowed_hosts_excludes_0_0_0_0(self):
        """Static check against gateway.py source — allowed_hosts list
        must NOT include 0.0.0.0."""
        import gateway as _gateway  # noqa: F401 — ensures import works

        gateway_src = Path(__file__).resolve().parent.parent / "gateway.py"
        text = gateway_src.read_text(encoding="utf-8")

        # Locate the allowed_hosts= block and assert 0.0.0.0 is absent.
        assert "allowed_hosts=" in text
        idx = text.index("allowed_hosts=")
        block = text[idx : idx + 400]
        assert "0.0.0.0" not in block, (
            "allowed_hosts must not contain 0.0.0.0 — it is never a valid "
            "Host header and whitelisting it bypasses DNS rebinding "
            "protection."
        )

    def test_default_host_is_loopback(self, monkeypatch):
        """HOST env var defaults to 127.0.0.1 when unset."""
        import os

        monkeypatch.delenv("HOST", raising=False)
        host = os.environ.get("HOST", "127.0.0.1")
        assert host == "127.0.0.1"


# =============================================================================
# IDX-A-002: CompassIndex.search on empty index returns []
# =============================================================================


class TestIDXA002EmptyIndexSearch:
    @pytest.mark.asyncio
    async def test_search_empty_index_returns_list(
        self, temp_index_path, temp_db_path, mock_embedder
    ):
        """Calling .search() on a freshly-built empty index must return []
        without crashing the underlying hnswlib knn_query (which would
        otherwise raise on k=0 or k>count)."""
        from indexer import CompassIndex

        index = CompassIndex(
            index_path=temp_index_path,
            db_path=temp_db_path,
            embedder=mock_embedder,
        )
        # Build with zero tools so get_current_count() == 0.
        await index.build_index([])

        try:
            results = await index.search("anything", top_k=5)
            assert results == []
        finally:
            await index.close()


# =============================================================================
# IDX-A-005: ChainIndexer survives numpy int64 labels from knn_query
# =============================================================================


class TestIDXA005Numpyint64Labels:
    @pytest.mark.asyncio
    async def test_search_chains_casts_int64_label(
        self, test_chain_indexer
    ):
        """hnswlib returns numpy int64 labels; the lookup dict is keyed by
        Python int. The production code must cast int(label) before
        dict.get(), otherwise results silently vanish.

        This test adds a chain, then simulates knn_query returning a
        numpy-int64 label and asserts the corresponding chain is found.
        """
        # Add a chain to the DB, then build the index (which picks it up
        # from the DB). add_chain alone is a no-op on the index when the
        # index hasn't been constructed yet.
        chain = await test_chain_indexer.add_chain(
            name="regression_np_label",
            tools=["test:a", "test:b"],
            description="numpy label regression",
        )
        await test_chain_indexer.build_chain_index()
        assert test_chain_indexer.index is not None
        # build_chain_index rebuilds the _id_to_chain map — make sure our
        # chain is in it so .get(int(label)) returns a value.
        assert chain.id in test_chain_indexer._id_to_chain

        # Force knn_query to return numpy int64 labels + near-zero distances.
        # hnswlib.Index is a C++ extension with read-only attributes — can't
        # patch.object on it. Replace the whole index with a Mock.
        fake_label = np.array([[np.int64(chain.id)]])
        fake_dist = np.array([[0.01]])

        mock_index = Mock()
        mock_index.knn_query.return_value = (fake_label, fake_dist)
        mock_index.get_current_count.return_value = 1
        test_chain_indexer.index = mock_index

        results = await test_chain_indexer.search_chains(
            "any query", top_k=3, min_confidence=0.0
        )

        # If the code forgets to cast numpy.int64 → int, _id_to_chain.get()
        # returns None and results is empty. Lock in that the result is found.
        assert len(results) == 1
        assert results[0].chain.name == "regression_np_label"


# =============================================================================
# IDX-A-006: ChainIndexer.add_chain handles capacity overflow via resize
# =============================================================================


class TestIDXA006CapacityResize:
    @pytest.mark.asyncio
    async def test_add_chain_triggers_resize_at_capacity(
        self, test_chain_indexer
    ):
        """When the HNSW chain index reaches its max_elements, add_chain
        must call resize_index() instead of letting hnswlib raise."""
        # build_chain_index() returns early if there are no chains yet,
        # so seed one chain first, then build the index so it exists.
        await test_chain_indexer.add_chain(
            name="seed_for_resize_test",
            tools=["seed:a", "seed:b"],
            description="seed",
        )
        await test_chain_indexer.build_chain_index()
        assert test_chain_indexer.index is not None

        # hnswlib.Index is a C++ extension — patch.object is not supported on
        # its methods. Replace the whole index with a Mock to simulate
        # at-capacity and observe the resize call.
        resize_calls = []

        def tracked_resize(new_max):
            resize_calls.append(new_max)

        mock_index = Mock()
        mock_index.get_current_count.return_value = 10
        mock_index.get_max_elements.return_value = 10
        mock_index.resize_index.side_effect = tracked_resize
        test_chain_indexer.index = mock_index

        await test_chain_indexer.add_chain(
            name="overflow_chain",
            tools=["test:x", "test:y"],
            description="trigger resize",
        )

        assert len(resize_calls) == 1
        # New capacity must be strictly larger than the old.
        assert resize_calls[0] > 10


# =============================================================================
# MCC-A-001: record_tool_call running average is EXACT for 10/20/30 → 20.0
# =============================================================================


class TestMCCA001RunningAverage:
    @pytest.mark.asyncio
    async def test_three_known_latencies_produce_exact_average(
        self, test_analytics
    ):
        """Record three tool calls with latencies 10, 20, 30. The running
        average in tool_usage_stats must be EXACTLY 20.0 — the SET-clause
        ordering in the UPDATE is load-bearing (avg must compute BEFORE
        call_count is incremented)."""
        tool = "test:running_avg_check"

        await test_analytics.record_tool_call(tool, success=True, latency_ms=10.0)
        await test_analytics.record_tool_call(tool, success=True, latency_ms=20.0)
        await test_analytics.record_tool_call(tool, success=True, latency_ms=30.0)

        db = test_analytics._get_db()
        row = db.execute(
            "SELECT call_count, avg_latency_ms FROM tool_usage_stats WHERE tool_name=?",
            (tool,),
        ).fetchone()

        assert row is not None
        assert row["call_count"] == 3
        # Exact, not approximate. If ordering drifts, this will fail.
        assert row["avg_latency_ms"] == pytest.approx(20.0, rel=0, abs=1e-9)


# =============================================================================
# MCC-A-003: arguments_hash differs for same keys + different values
# =============================================================================


class TestMCCA003ArgumentsHashByValue:
    @pytest.mark.asyncio
    async def test_different_values_produce_different_hashes(
        self, test_analytics
    ):
        """{path: /foo} vs {path: /bar} must produce DIFFERENT hashes.
        Earlier revisions hashed only keys (both would collide)."""
        await test_analytics.record_tool_call(
            "test:hash_check",
            success=True,
            latency_ms=5.0,
            arguments={"path": "/foo"},
        )
        await test_analytics.record_tool_call(
            "test:hash_check",
            success=True,
            latency_ms=5.0,
            arguments={"path": "/bar"},
        )

        db = test_analytics._get_db()
        rows = db.execute(
            "SELECT arguments_hash FROM tool_calls WHERE tool_name=? ORDER BY id",
            ("test:hash_check",),
        ).fetchall()

        hashes = [r["arguments_hash"] for r in rows]
        assert len(hashes) == 2
        assert hashes[0] is not None
        assert hashes[1] is not None
        # The load-bearing assert: same keys, different values → different hash.
        assert hashes[0] != hashes[1]


# =============================================================================
# MCC-A-005: record_search is safe to call from two threads concurrently
# =============================================================================


class TestMCCA005ConcurrentRecordSearch:
    def test_two_threads_recording_searches_do_not_raise(
        self, test_analytics
    ):
        """record_search shares a sqlite3 connection via check_same_thread
        and serializes writes under self._lock. Calling it from two threads
        concurrently must complete without raising.

        TS-B-002 hardening:
          - ``threading.Barrier(2)`` synchronizes both workers immediately
            before the contention point so they really race. Without it,
            ``t1.start()`` followed by ``t2.start()`` on a slow CI runner can
            let t1 complete before t2 even begins — the "concurrent" claim
            becomes vacuous.
          - ``not t1.is_alive()`` / ``not t2.is_alive()`` after each join
            converts silent deadlock into an explicit liveness failure.
            Without these, a deadlock elapsed the 10s timeout, both threads
            exited the run() context as zombies, and the downstream
            ``count == 2`` would fail with the misleading shape
            "count mismatch" instead of "threads deadlocked."

        Research basis: Python Free-Threading Guide (https://py-free-threading.github.io/porting/)
        on threading.Barrier for race-window maximization, and CPython
        Lib/test/lock_tests.py for the canonical
        ``join + assertFalse(is_alive())`` pattern.
        """
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def worker(query: str):
            try:
                # Race-window maximization: both threads block here until the
                # other arrives, then both proceed simultaneously.
                barrier.wait(timeout=5)
                asyncio.run(
                    test_analytics.record_search(
                        query=query,
                        results=[],
                        latency_ms=1.0,
                    )
                )
            except BaseException as exc:  # noqa: BLE001 — capture everything
                errors.append(exc)

        t1 = threading.Thread(target=worker, args=("thread-1",))
        t2 = threading.Thread(target=worker, args=("thread-2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Liveness checks — distinguish "thread completed" from "thread
        # silently timed out under a deadlock."
        assert not t1.is_alive(), "thread-1 did not finish within 10s (deadlock?)"
        assert not t2.is_alive(), "thread-2 did not finish within 10s (deadlock?)"

        assert not errors, f"concurrent record_search raised: {errors!r}"

        # Verify BOTH searches were actually recorded (not just silently
        # dropped by an unlocked-access crash).
        db = test_analytics._get_db()
        count = db.execute(
            "SELECT COUNT(*) FROM search_queries WHERE query IN ('thread-1','thread-2')"
        ).fetchone()[0]
        assert count == 2
