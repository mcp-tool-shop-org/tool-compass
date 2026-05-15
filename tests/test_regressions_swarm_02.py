"""Stage A regression tests — wave 2 (BE-A-* and FE-A-* swarm fixes).

This file complements ``test_regressions_swarm_01.py``. The first file
locks in GW-A-* / IDX-A-* / MCC-A-* Stage A fixes; this one locks in the
BE-A-* (Backend agent) and FE-A-* / FE-A2-* (Frontend agent) Stage A fixes
that the swarm shipped without dedicated regression coverage.

Findings covered:

  BE-A-001/002 /ready and /metrics call circuit_breaker_state() as a
              METHOD (not an attribute lookup that would return a bound
              method object stringified into the body).
  BE-A-003   sqlite3 connection in CompassIndex opens with
              check_same_thread=False so the search_sync() thread-pool
              path doesn't ProgrammingError on cross-thread access.
  BE-A-004   gateway.compass()'s lexical fallback filters by the user's
              min_confidence — without this, a caller passing 0.9 still
              gets 0.3-tier matches when Ollama is down.
  BE-A-005   chain_indexer.add_chain re-SELECTs the canonical chain_id
              after ON CONFLICT, because cursor.lastrowid is unreliable
              on the conflict path. Without it, _id_to_chain and HNSW
              labels drift apart silently.
  BE-A2-001/002 hnswlib UPDATE path on CompassIndex.add_single_tool and
              ChainIndexer.add_chain uses replace_deleted=True so re-adds
              of an existing label don't raise RuntimeError.
  FE-A-001   ui.get_chain_indexer_instance is safe under concurrent cold
              start — the partial-init guard at ui.py:131-142 means two
              threads racing into chain-init don't both call the loader.
  FE-A2-001..002 ui.format_error html.escape's the caller-supplied
              context and exception string. Inserting ``<script>`` into
              either does NOT produce raw HTML.
  FE-A2-003..005 partial-init recovery — when the loader inside
              get_index / get_chain_indexer_instance / get_analytics_instance
              raises, the module global stays at None so the next call
              retries cleanly instead of returning a half-initialized
              singleton.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import threading
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest


# =============================================================================
# BE-A-001/002: /ready and /metrics call circuit_breaker_state() as a method
# =============================================================================


class TestBEA001CircuitBreakerStateCalledAsMethod:
    """Lock in BE-A-001/002 — both endpoints invoke circuit_breaker_state()
    as a method. Source assertion: grep gateway.py for the two call sites
    and require parentheses. A regression that drops them would silently
    embed a `<bound method ...>` repr in the response."""

    def test_gateway_ready_uses_method_call(self):
        src = Path(__file__).resolve().parent.parent / "gateway.py"
        text = src.read_text(encoding="utf-8")
        # The two call sites both look like `embedder.circuit_breaker_state()`
        # (with the parens). A regression that drops them would still parse
        # but bind a bound-method object — the regex pins parentheses.
        method_calls = re.findall(r"circuit_breaker_state\s*\(\s*\)", text)
        assert len(method_calls) >= 2, (
            "Expected at least 2 method invocations of "
            "circuit_breaker_state() (in /ready + /metrics), "
            f"found {len(method_calls)}"
        )
        # And no attribute-only lookups of the same name.
        bad = re.findall(r"\.circuit_breaker_state(?!\s*\()", text)
        assert not bad, (
            f"circuit_breaker_state referenced as attribute (no parens) at: {bad}"
        )


# =============================================================================
# BE-A-003: sqlite3 check_same_thread=False on CompassIndex DB
# =============================================================================


class TestBEA003CheckSameThreadFalse:
    """Lock in BE-A-003 — search_sync dispatches search() to a worker thread
    via ThreadPoolExecutor when called inside a running loop, so the sqlite3
    connection MUST be opened with check_same_thread=False. Otherwise sqlite3
    raises ProgrammingError on the cross-thread access. A regression that
    drops the flag will fail this test loudly."""

    @pytest.mark.asyncio
    async def test_indexer_db_allows_cross_thread_access(
        self, test_index
    ):
        # If check_same_thread=False is set, executing a SELECT from a non-
        # owning thread succeeds. If the flag regressed to default True,
        # sqlite3 raises ProgrammingError.
        result_holder: dict = {}

        def worker():
            try:
                cur = test_index.db.execute(
                    "SELECT COUNT(*) AS c FROM tools"
                )
                result_holder["count"] = cur.fetchone()["c"]
            except sqlite3.ProgrammingError as e:
                result_holder["error"] = e

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "worker thread did not finish within 5s"
        assert "error" not in result_holder, (
            f"sqlite3 raised cross-thread: {result_holder.get('error')}. "
            "BE-A-003 regression — check_same_thread=False was dropped."
        )
        assert "count" in result_holder
        assert isinstance(result_holder["count"], int)

    def test_indexer_source_pins_check_same_thread_false(self):
        """Belt + suspenders — verify the literal pattern in the source so
        a future refactor that drops the flag fails even before the runtime
        test gets a chance to run."""
        src = Path(__file__).resolve().parent.parent / "indexer.py"
        text = src.read_text(encoding="utf-8")
        assert "check_same_thread=False" in text, (
            "BE-A-003 regression: indexer.py no longer passes "
            "check_same_thread=False to sqlite3.connect"
        )


# =============================================================================
# BE-A-004: lexical fallback honours min_confidence
# =============================================================================


class TestBEA004LexicalFallbackHonoursMinConfidence:
    """Lock in BE-A-004 — when Ollama is down, gateway.compass() falls back
    to lexical LIKE matching. That path assigns coarse heuristic confidences
    (0.6, 0.4, 0.3). The user-supplied min_confidence MUST filter the
    fallback matches too, otherwise a caller passing 0.9 still receives
    0.3-tier results. The fix at gateway.py:494-496 filters the list."""

    @pytest.mark.asyncio
    async def test_fallback_filters_by_min_confidence(
        self, test_index, test_config, sample_tools
    ):
        import gateway

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

        # Break the embedder so semantic search raises and we go through the
        # lexical-fallback branch.
        test_index.embedder.embed_query = AsyncMock(
            side_effect=RuntimeError("ollama down")
        )

        from gateway import compass

        # min_confidence=0.9 — only 0.6+ fallback matches should pass; a
        # regression that drops the filter would also return 0.3/0.4 hits.
        result = await compass(intent="read a file", min_confidence=0.9)

        # The response wraps matches in 'matches'. Every match must clear
        # the floor.
        matches = result.get("matches") or []
        for m in matches:
            assert m["confidence"] >= 0.9, (
                f"BE-A-004 regression: lexical fallback returned a "
                f"confidence-{m['confidence']} match while min_confidence=0.9. "
                f"match={m}"
            )


# =============================================================================
# BE-A-005: chain_indexer.add_chain re-SELECTs canonical chain_id
# =============================================================================


class TestBEA005AddChainResolvesCanonicalId:
    """Lock in BE-A-005 — INSERT ... ON CONFLICT DO UPDATE returns
    cursor.lastrowid=0 on the conflict path in older sqlite3. A regression
    that uses cursor.lastrowid directly will silently corrupt _id_to_chain.
    The fix re-SELECTs by chain_name."""

    @pytest.mark.asyncio
    async def test_add_chain_uses_canonical_id_on_conflict(
        self, test_chain_indexer
    ):
        # First add — fresh row.
        c1 = await test_chain_indexer.add_chain(
            name="test:flow",
            tools=["a", "b"],
            description="orig",
            is_auto_detected=False,
        )
        id1 = c1.id
        assert id1 > 0

        # Second add — same name, triggers ON CONFLICT.
        c2 = await test_chain_indexer.add_chain(
            name="test:flow",
            tools=["a", "b", "c"],
            description="updated",
            is_auto_detected=False,
        )
        # The canonical id must match the original row id, NOT a bogus 0.
        assert c2.id == id1, (
            f"BE-A-005 regression: on-conflict id={c2.id}, expected {id1}. "
            "cursor.lastrowid was probably used directly."
        )

        # And the returned ToolChain reflects the updated state, not the
        # stale orig row.
        assert c2.tools == ["a", "b", "c"]
        assert c2.description == "updated"

    def test_chain_indexer_source_pins_canonical_reselect(self):
        src = Path(__file__).resolve().parent.parent / "chain_indexer.py"
        text = src.read_text(encoding="utf-8")
        assert "SELECT id FROM tool_chains WHERE chain_name" in text, (
            "BE-A-005 regression: chain_indexer.add_chain no longer re-SELECTs "
            "the canonical id after ON CONFLICT."
        )


# =============================================================================
# BE-A2-001/002: hnswlib allow_replace_deleted + replace_deleted on UPDATE
# =============================================================================


class TestBEA2001ReplaceDeletedOnUpdate:
    """Lock in BE-A2-001/002 — when a tool is updated, hnswlib add_items
    with replace_deleted=True is the only way to re-use a label. Without
    allow_replace_deleted=True at init, this raises. Without
    replace_deleted=True on the add, duplicate-label is fatal."""

    @pytest.mark.asyncio
    async def test_add_single_tool_update_path_does_not_raise(
        self, test_index, sample_tools
    ):
        # sample_tools[0] is already in the index from the fixture build.
        # Re-add it via add_single_tool to exercise the UPDATE path.
        updated = sample_tools[0]
        updated.description = updated.description + " (revised)"
        ok = await test_index.add_single_tool(updated)
        assert ok is True, (
            "BE-A2-001 regression: add_single_tool UPDATE path failed — "
            "likely missing replace_deleted=True or allow_replace_deleted."
        )

    @pytest.mark.asyncio
    async def test_chain_indexer_conflict_path_does_not_raise(
        self, test_chain_indexer
    ):
        # Add and re-add — the second call hits the ON CONFLICT branch in
        # SQLite AND the duplicate-label branch in HNSW.
        await test_chain_indexer.add_chain(
            name="test:hnsw_replace",
            tools=["t1", "t2"],
            description="orig",
            is_auto_detected=True,
        )
        c2 = await test_chain_indexer.add_chain(
            name="test:hnsw_replace",
            tools=["t1", "t2", "t3"],
            description="updated",
            is_auto_detected=True,
        )
        assert c2 is not None, (
            "BE-A2-002 regression: chain ON-CONFLICT path raised — "
            "likely missing replace_deleted=True on HNSW add_items."
        )

    def test_indexer_init_uses_allow_replace_deleted(self):
        src = Path(__file__).resolve().parent.parent / "indexer.py"
        text = src.read_text(encoding="utf-8")
        assert "allow_replace_deleted=True" in text, (
            "BE-A2-001 regression: indexer no longer initializes HNSW with "
            "allow_replace_deleted=True. UPDATE path will start raising."
        )
        assert "replace_deleted=True" in text, (
            "BE-A2-001 regression: indexer.add_single_tool no longer passes "
            "replace_deleted=True on the UPDATE path."
        )

    def test_chain_indexer_uses_replace_deleted(self):
        src = Path(__file__).resolve().parent.parent / "chain_indexer.py"
        text = src.read_text(encoding="utf-8")
        assert "replace_deleted=True" in text, (
            "BE-A2-002 regression: chain_indexer no longer passes "
            "replace_deleted=True on the HNSW add_items conflict path."
        )


# =============================================================================
# FE-A2-001/002: ui.format_error HTML-escapes context + exception string
# =============================================================================


class TestFEA2001FormatErrorEscapesXSS:
    """Lock in FE-A2-001/002 — caller-supplied context and exception
    payloads in ui.format_error are html.escape'd. Inserting a <script>
    tag into either must surface as &lt;script&gt; in the output, never
    as the live tag."""

    def test_format_error_escapes_context_payload(self):
        from ui import format_error

        # Generic Exception flows through the 'else' branch where both
        # context and str(error) are interpolated into the HTML body.
        out = format_error(
            Exception("benign error"),
            context="<script>alert('xss')</script>",
        )
        assert "<script>alert" not in out, (
            "FE-A2-001 regression: format_error embedded a raw <script> tag "
            "from context. ui.format_error should html.escape its arguments."
        )
        assert "&lt;script&gt;" in out, (
            "FE-A2-001 regression: escaped <script> not present in output — "
            "context may not have been escaped at all."
        )

    def test_format_error_escapes_exception_payload(self):
        from ui import format_error

        err = Exception("<img src=x onerror=alert(1)>")
        out = format_error(err, context="upload")
        assert "<img src=x" not in out, (
            "FE-A2-002 regression: format_error embedded a raw <img> tag "
            "from str(exception). The exception payload must be escaped."
        )
        # html.escape with quote=True turns `=` and `<` into entities.
        assert "&lt;img" in out, (
            "FE-A2-002 regression: escaped <img> not present in output — "
            "exception str() may not have been escaped at all."
        )


# =============================================================================
# FE-A2-001/002 (search result path): search HTML escapes the query
# =============================================================================


class TestFEA2001SearchPathEscapesQuery:
    """Lock in the search-error path's escape — when index loading fails,
    format_error is called with a query-bearing context that must be
    escaped before interpolation."""

    def test_ui_source_pins_escape_on_search_error_path(self):
        """The function search_tools calls
        ``format_error(e, f"Search failed for: {html.escape(query, quote=True)}")``
        when the run_async(do_search()) raises. Pin the literal pattern."""
        src = Path(__file__).resolve().parent.parent / "ui.py"
        text = src.read_text(encoding="utf-8")
        assert "html.escape(query" in text, (
            "FE-A2-001 regression: ui.py no longer escapes the query in the "
            "search error branch."
        )

    def test_ui_get_chains_view_uses_escape(self):
        """Lock in the chains view escape too — chain names/tools/desc all
        flow through html.escape before HTML interpolation."""
        src = Path(__file__).resolve().parent.parent / "ui.py"
        text = src.read_text(encoding="utf-8")
        # The function exists.
        assert "def get_chains_view" in text
        # And it html.escape's at least the chain name + tool flow + desc.
        # We require a minimum of 4 escape calls inside the function — a
        # regression that drops them entirely will lose all of them.
        chains_block_start = text.find("def get_chains_view")
        next_def = text.find("\ndef ", chains_block_start + 1)
        chains_body = text[chains_block_start:next_def]
        escape_count = chains_body.count("html.escape(")
        assert escape_count >= 4, (
            f"FE-A2-002 regression: get_chains_view has only {escape_count} "
            "html.escape calls (expected >= 4 for chain name/flow/desc)."
        )

    def test_ui_get_system_status_uses_escape(self):
        """Lock in get_system_status — all exception strings interpolated
        into the status HTML are escaped via html.escape(truncate_text(str(e)))."""
        src = Path(__file__).resolve().parent.parent / "ui.py"
        text = src.read_text(encoding="utf-8")
        sys_start = text.find("def get_system_status")
        next_def = text.find("\ndef ", sys_start + 1)
        sys_body = text[sys_start:next_def]
        # Every str(e) in this function must be escaped. Look for the
        # pattern html.escape(truncate_text(str(e)... within the body.
        assert "html.escape(truncate_text" in sys_body, (
            "FE-A-* regression: get_system_status no longer escapes "
            "truncated exception strings before interpolation."
        )


# =============================================================================
# FE-A2-003/004/005: partial-init recovery — failing build leaves global None
# =============================================================================
#
# Pattern under test (ui.py:79-142):
#   global _x
#   if _x is not None: return _x
#   with _init_lock:
#       if _x is not None: return _x
#       local = build()           # may raise
#       if not local.load(): raise
#       _x = local                # publish only on success
#   return _x
#
# Property: when `build()` or `load()` raises, the module global stays at
# `None`. A subsequent call with a healthy build_fn must succeed. This is
# the bug-pin for "half-initialized singleton stuck forever."


class TestFEA2003PartialInitDoesNotPublishOnFailure:
    """Lock in FE-A2-003/004/005 — partial-init recovery for ui's three
    cold-start singletons (index, analytics, chain indexer)."""

    def test_get_index_first_call_raises_does_not_publish(self):
        """If CompassIndex.load_index returns False on the first call,
        ui._index must remain None so the next caller can retry."""
        import ui

        ui._index = None  # ensure cold start

        with patch("ui.CompassIndex") as MockIdx:
            broken = Mock()
            broken.load_index = Mock(return_value=False)
            MockIdx.return_value = broken

            with pytest.raises(RuntimeError, match="Failed to load index"):
                ui.get_index()

            assert ui._index is None, (
                "FE-A2-003 regression: failed init published a broken index. "
                "ui._index must remain None so the next call retries."
            )

    def test_get_index_second_call_succeeds_after_first_failure(self):
        """The partial-init recovery contract: after a failing build, the
        next call with a working build_fn succeeds."""
        import ui

        ui._index = None  # cold start

        # First call fails.
        with patch("ui.CompassIndex") as MockIdx:
            broken = Mock()
            broken.load_index = Mock(return_value=False)
            MockIdx.return_value = broken
            with pytest.raises(RuntimeError):
                ui.get_index()

        assert ui._index is None

        # Second call succeeds — different MockIdx so load_index returns True.
        with patch("ui.CompassIndex") as MockIdx:
            healthy = Mock()
            healthy.load_index = Mock(return_value=True)
            MockIdx.return_value = healthy

            result = ui.get_index()
            assert result is healthy, (
                "FE-A2-003 regression: second-attempt init did not produce "
                "a fresh CompassIndex after the first attempt failed."
            )

        # Reset for next test.
        ui._index = None

    def test_get_chain_indexer_instance_locking_is_safe(self):
        """Lock in FE-A-001 — concurrent cold-start callers don't deadlock
        or both call the loader. ``threading.Barrier(N)`` per the Python
        Free-Threading Guide maximizes the race window."""
        import ui

        ui._chain_indexer = None
        ui._config = None
        ui._index = None  # disable the chain indexer init by leaving config off

        # Make _config such that chain_indexing_enabled is False — the
        # function then short-circuits without trying to actually init the
        # chain indexer. We only want to test the locking primitive doesn't
        # deadlock under contention.
        fake_cfg = Mock()
        fake_cfg.chain_indexing_enabled = False

        barrier = threading.Barrier(4)
        results: list = []
        errors: list = []

        def worker():
            try:
                with patch("ui.load_config", return_value=fake_cfg):
                    barrier.wait(timeout=5)
                    out = ui.get_chain_indexer_instance()
                    results.append(out)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        for t in threads:
            assert not t.is_alive(), (
                "FE-A-001 regression: get_chain_indexer_instance deadlocked "
                "under concurrent cold-start contention."
            )
        assert not errors, (
            f"FE-A-001 regression: get_chain_indexer_instance raised under "
            f"concurrent cold start: {errors}"
        )
        # All four callers must see the same value (None in this case
        # because chain indexing is disabled).
        assert all(r is None for r in results)
