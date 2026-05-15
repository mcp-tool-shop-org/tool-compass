"""
Tests for Tool Compass analytics module.

Tests usage tracking, hot cache, and chain detection.
"""

import pytest

from analytics import HotToolEntry


class TestAnalyticsRecording:
    """Test analytics event recording."""

    @pytest.mark.asyncio
    async def test_record_search(self, test_analytics):
        """Should record search queries."""

        # Create mock results
        class MockResult:
            class MockTool:
                name = "test:read_file"

            tool = MockTool()

        results = [MockResult()]

        await test_analytics.record_search(
            query="read a file",
            results=results,
            latency_ms=15.5,
            category_filter=None,
            server_filter=None,
        )

        # Verify it was recorded
        summary = await test_analytics.get_analytics_summary("1h")
        assert summary["searches"]["total"] >= 1

    @pytest.mark.asyncio
    async def test_record_tool_call_success(self, test_analytics):
        """Should record successful tool calls."""
        await test_analytics.record_tool_call(
            tool_name="test:read_file",
            success=True,
            latency_ms=50.0,
        )

        summary = await test_analytics.get_analytics_summary("1h")
        assert summary["tool_calls"]["total"] >= 1

    @pytest.mark.asyncio
    async def test_record_tool_call_failure(self, test_analytics):
        """Should record failed tool calls with error message."""
        await test_analytics.record_tool_call(
            tool_name="test:failing_tool",
            success=False,
            latency_ms=100.0,
            error_message="Connection refused",
        )

        summary = await test_analytics.get_analytics_summary("1h")
        # Verify the failure was actually recorded — `len(...) >= 0` is
        # always true, so the earlier assert never validated anything.
        failures = summary["failures"]
        assert isinstance(failures, list)
        # Tool-level failure count is available through tool_calls totals.
        assert summary["tool_calls"]["total"] >= 1
        # The failing call must be reflected in success_rate being < 1.0
        # when this is the only call recorded. Success rate is a ratio of
        # successes / total; our single call was a failure.
        if summary["tool_calls"]["total"] == 1:
            assert summary["tool_calls"]["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_record_tool_call_with_arguments(self, test_analytics):
        """Should hash argument payload and persist it on the call row."""
        # TS-A-003: previously this test asserted nothing beyond "did not raise."
        # Verify the args_hash is computed, deterministic for the same input,
        # and actually written to tool_calls.arguments_hash.
        arguments = {"filepath": "/tmp/test.txt", "encoding": "utf-8"}

        await test_analytics.record_tool_call(
            tool_name="test:read_file",
            success=True,
            latency_ms=25.0,
            arguments=arguments,
        )

        # Re-record with the same args — the hashes must match (determinism).
        await test_analytics.record_tool_call(
            tool_name="test:read_file",
            success=True,
            latency_ms=25.0,
            arguments=arguments,
        )

        # Re-record with different args — the hash must differ.
        await test_analytics.record_tool_call(
            tool_name="test:read_file",
            success=True,
            latency_ms=25.0,
            arguments={"filepath": "/tmp/other.txt", "encoding": "utf-8"},
        )

        # Read directly from the DB to verify hashes were persisted.
        db = test_analytics._get_db()
        rows = db.execute(
            "SELECT arguments_hash FROM tool_calls "
            "WHERE tool_name = 'test:read_file' "
            "ORDER BY id ASC"
        ).fetchall()
        hashes = [row["arguments_hash"] for row in rows]

        assert len(hashes) == 3, f"expected 3 rows recorded, got {len(hashes)}"
        # All hashes are non-null — args were supplied.
        assert all(h is not None for h in hashes), hashes
        # Same input -> same hash (determinism).
        assert hashes[0] == hashes[1], (hashes[0], hashes[1])
        # Different input -> different hash (no key-only collision).
        assert hashes[0] != hashes[2], (hashes[0], hashes[2])


class TestHotCache:
    """Test hot tool caching."""

    @pytest.mark.asyncio
    async def test_refresh_hot_cache(self, test_analytics):
        """Should populate hot cache from usage data."""
        # Record some tool calls
        for i in range(5):
            await test_analytics.record_tool_call(
                tool_name="test:popular_tool",
                success=True,
                latency_ms=10.0,
            )

        for i in range(3):
            await test_analytics.record_tool_call(
                tool_name="test:less_popular",
                success=True,
                latency_ms=15.0,
            )

        # Refresh cache
        hot_tools = await test_analytics.refresh_hot_cache()

        assert len(hot_tools) > 0
        assert "test:popular_tool" in hot_tools

    @pytest.mark.asyncio
    async def test_get_hot_tool(self, test_analytics):
        """Should return cached tool data."""
        # Record calls to populate stats
        for i in range(10):
            await test_analytics.record_tool_call(
                tool_name="test:hot_tool",
                success=True,
                latency_ms=5.0,
            )

        await test_analytics.refresh_hot_cache()

        entry = test_analytics.get_hot_tool("test:hot_tool")
        if entry:  # May not be in cache if other tools have more calls
            assert isinstance(entry, HotToolEntry)
            assert entry.call_count >= 10

    @pytest.mark.asyncio
    async def test_is_hot(self, test_analytics):
        """Should check if tool is in hot cache."""
        # Initially empty
        assert test_analytics.is_hot("test:any_tool") is False

        # After recording and refreshing
        for i in range(5):
            await test_analytics.record_tool_call(
                tool_name="test:becoming_hot",
                success=True,
                latency_ms=10.0,
            )
        await test_analytics.refresh_hot_cache()

        # TS-A-004: the fixture wires hot_cache_size=5 (conftest.py:298) and
        # only one tool was recorded. There is no eviction pressure, so the
        # tool MUST be hot — earlier "may or may not" wording left this
        # branch unverified.
        assert test_analytics.is_hot("test:becoming_hot") is True
        # Negative case: a tool never recorded is not hot.
        assert test_analytics.is_hot("test:never_recorded") is False


class TestChainDetection:
    """Test automatic chain/workflow detection."""

    @pytest.mark.asyncio
    async def test_chain_pattern_recording(self, test_analytics):
        """Should record tool sequences for pattern detection."""
        # Simulate a workflow: read -> modify -> write
        await test_analytics.record_tool_call(
            "test:read_file", success=True, latency_ms=10
        )
        await test_analytics.record_tool_call(
            "test:process", success=True, latency_ms=20
        )
        await test_analytics.record_tool_call(
            "test:write_file", success=True, latency_ms=15
        )

        # TS-A-001: the three calls must show up in the in-memory session
        # sequence (the deque feeding chain detection). The deque stores
        # tool_name strings — assert the trailing three match what we sent
        # in order. Earlier revisions of this test asserted nothing and so
        # could not detect a regression where record_tool_call silently
        # stopped appending to the chain-detection buffer.
        recent = list(test_analytics._session_tool_sequence)[-3:]
        assert recent == ["test:read_file", "test:process", "test:write_file"], recent

        # The 3-tool subsequence should also be persisted to chain_patterns
        # (record_tool_call calls _save_chain_pattern on every append).
        db = test_analytics._get_db()
        pattern_count = db.execute(
            "SELECT COUNT(*) AS n FROM chain_patterns"
        ).fetchone()["n"]
        assert pattern_count > 0, "chain_patterns should contain at least one row"

    @pytest.mark.asyncio
    async def test_detect_chains(self, test_analytics):
        """Should detect frequently occurring tool sequences."""
        # Create a pattern that occurs multiple times
        for _ in range(5):  # More than chain_min_occurrences
            await test_analytics.record_tool_call(
                "test:step_a", success=True, latency_ms=10
            )
            await test_analytics.record_tool_call(
                "test:step_b", success=True, latency_ms=10
            )

        # Force pattern save
        await test_analytics._save_chain_pattern()

        # Detect chains
        detected = await test_analytics.detect_chains()

        # TS-A-002: detection should have promoted the recurring [step_a,
        # step_b] subsequence into tool_chains. The fixture sets
        # chain_min_occurrences=2 (conftest.py:299), so 5 occurrences
        # clears the bar. Earlier revisions left the assertion off and
        # could not detect a regression where detect_chains() silently
        # found nothing.
        chains = await test_analytics.get_chains(limit=50)
        chain_tool_sets = [tuple(c["tools"]) for c in chains]
        assert ("test:step_a", "test:step_b") in chain_tool_sets, chain_tool_sets

        # detect_chains() returns NEW chains it promoted on this call.
        # On the first run it should be non-empty for this pattern.
        detected_tool_sets = [tuple(c["tools"]) for c in detected]
        assert ("test:step_a", "test:step_b") in detected_tool_sets, detected_tool_sets

    @pytest.mark.asyncio
    async def test_get_chains(self, test_analytics):
        """Should retrieve stored chains."""
        chains = await test_analytics.get_chains(limit=10)
        assert isinstance(chains, list)


class TestAnalyticsSummary:
    """Test analytics summary generation."""

    @pytest.mark.asyncio
    async def test_get_analytics_summary_structure(self, test_analytics):
        """Summary should have expected structure."""
        summary = await test_analytics.get_analytics_summary("24h")

        assert "timeframe" in summary
        assert "searches" in summary
        assert "tool_calls" in summary
        assert "failures" in summary
        assert "chains" in summary
        assert "hot_cache" in summary

    @pytest.mark.asyncio
    async def test_get_analytics_summary_timeframes(self, test_analytics):
        """Should support different timeframes."""
        for tf in ["1h", "24h", "7d", "30d"]:
            summary = await test_analytics.get_analytics_summary(tf)
            assert summary["timeframe"] == tf

    @pytest.mark.asyncio
    async def test_analytics_summary_calculations(self, test_analytics):
        """Should calculate metrics correctly."""
        # Record known data
        await test_analytics.record_tool_call("test:tool", success=True, latency_ms=100)
        await test_analytics.record_tool_call("test:tool", success=True, latency_ms=200)
        await test_analytics.record_tool_call("test:tool", success=False, latency_ms=50)

        summary = await test_analytics.get_analytics_summary("1h")

        assert summary["tool_calls"]["total"] >= 3
        # Success rate should reflect 2/3 successes (approximately 66.7%)


class TestPersistence:
    """Test analytics data persistence."""

    @pytest.mark.asyncio
    async def test_load_hot_cache_from_db(self, test_analytics):
        """Should restore hot cache from database."""
        # Record some data and refresh cache
        for i in range(5):
            await test_analytics.record_tool_call(
                tool_name="test:persistent_tool",
                success=True,
                latency_ms=10.0,
            )
        await test_analytics.refresh_hot_cache()

        # Clear in-memory cache
        test_analytics._hot_cache.clear()
        assert len(test_analytics._hot_cache) == 0

        # Reload from DB
        await test_analytics.load_hot_cache_from_db()

        # TS-A-005: the fixture wires hot_cache_size=5 and only this one
        # tool was recorded, so the persisted hot_tools row MUST be
        # rehydrated. Earlier revisions left the assertion off, so a
        # regression where load_hot_cache_from_db silently produced an
        # empty cache would still pass.
        assert "test:persistent_tool" in test_analytics._hot_cache
        entry = test_analytics._hot_cache["test:persistent_tool"]
        assert entry.tool_name == "test:persistent_tool"
        assert entry.call_count == 5

    def test_close(self, test_analytics):
        """Should close database connection cleanly."""
        test_analytics.close()
        assert test_analytics.db is None
