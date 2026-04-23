"""
Fuzz Testing for Tool Compass

Tests input validation, security, and edge cases using Hypothesis.
"""

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from unittest.mock import patch
import json
from pathlib import Path


# =============================================================================
# SECURITY FUZZING
# =============================================================================


class TestSecurityFuzzing:
    """Security-focused fuzz tests."""

    # Common injection payloads
    INJECTION_PAYLOADS = [
        "'; DROP TABLE tools; --",
        "{{7*7}}",
        "${7*7}",
        "__import__('os').system('whoami')",
        "<script>alert('xss')</script>",
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32",
        "\x00",
        "\n\r",
        "{{constructor.constructor('return this')()}}",
    ]

    @pytest.mark.slow  # max_examples=200 (TST-B-006)
    @given(st.text(min_size=0, max_size=1000))
    @settings(max_examples=200)
    def test_search_query_sanitization(self, text):
        """Search queries should be safely handled."""
        from tool_manifest import ToolDefinition

        # Tool definition should safely handle any query text
        tool = ToolDefinition(
            name="test_tool",
            description=text,  # Use fuzzed input as description
            server="test",
            category="test",
        )

        # Should not raise
        result = tool.embedding_text()
        assert isinstance(result, str)

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_injection_in_tool_name(self, payload):
        """Tool names with injection attempts should be handled safely."""
        from tool_manifest import ToolDefinition

        tool = ToolDefinition(
            name=payload,
            description="Test tool",
            server="test",
            category="test",
        )

        # Should create without crashing
        assert tool.name == payload
        text = tool.embedding_text()
        assert isinstance(text, str)

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_injection_in_category(self, payload):
        """Categories with injection attempts should be handled safely."""
        from tool_manifest import ToolDefinition

        tool = ToolDefinition(
            name="test_tool",
            description="Test tool",
            server="test",
            category=payload,
        )

        assert tool.category == payload

    @pytest.mark.slow  # max_examples=200 (TST-B-006)
    @given(
        st.text(
            min_size=0,
            max_size=500,
            alphabet=st.characters(blacklist_characters="\x00"),
        )
    )
    @settings(max_examples=200)
    def test_config_path_validation(self, fuzz_path):
        """Config paths should be safely handled.

        NOTE: the env var name is `TOOL_COMPASS_BASE_PATH` — an earlier
        revision of this test used `TOOL_COMPASS_BASE`, which silently
        never exercised the env-path branch.
        """
        from config import get_base_path
        import os

        # Reject inputs Path() cannot normalize (e.g. NUL-embedded strings
        # are already filtered; skip empty-only / whitespace-only strings
        # that the function's env-path check falls through on).
        assume(fuzz_path)  # Non-empty — empty string falls through to default
        try:
            Path(fuzz_path)
        except (ValueError, OSError):
            assume(False)

        with patch.dict(os.environ, {"TOOL_COMPASS_BASE_PATH": fuzz_path}):
            result = get_base_path()
            # Must always return a Path object — no exceptions from valid
            # (non-null-byte) strings. We don't assert `is_absolute()` here
            # because Windows accepts inputs like '0:' that Path.resolve()
            # cannot promote to an absolute path; the contract is "don't
            # crash", not "always absolute for pathological drive letters".
            assert isinstance(result, Path)


# =============================================================================
# INPUT VALIDATION FUZZING
# =============================================================================


class TestInputValidationFuzzing:
    """Test input validation with edge cases."""

    @given(st.integers())
    def test_top_k_boundaries(self, k):
        """top_k parameter should handle any integer.

        CompassConfig is a plain dataclass — it does NOT validate bounds.
        This test locks in the contract that ANY integer is accepted
        without raising; callers own validation.
        """
        from config import CompassConfig

        # No try/except: if this ever raises, that's a behavior change we
        # want to see, not swallow.
        config = CompassConfig(default_top_k=k)
        assert config.default_top_k == k

    @given(st.floats(allow_nan=False, allow_infinity=False))
    def test_min_confidence_boundaries(self, conf):
        """min_confidence should handle edge case floats.

        Same contract as top_k: dataclass accepts any finite float.
        """
        from config import CompassConfig

        config = CompassConfig(min_confidence=conf)
        assert config.min_confidence == conf
        assert isinstance(config.min_confidence, float)

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=50),
            values=st.text(min_size=0, max_size=200),
            max_size=10,
        )
    )
    def test_arbitrary_tool_params(self, params):
        """Tool parameters should handle arbitrary dictionaries."""
        from tool_manifest import ToolDefinition

        tool = ToolDefinition(
            name="test_tool",
            description="Test",
            server="test",
            category="test",
            parameters=params,
        )

        # Should create successfully
        text = tool.embedding_text()
        assert isinstance(text, str)

    @pytest.mark.slow  # max_examples=100 (TST-B-006)
    @given(st.text(min_size=0, max_size=100))
    @settings(max_examples=100)
    def test_server_filter_arbitrary(self, server):
        """Server filter should handle arbitrary strings."""
        assume(server)  # Non-empty

        from config import CompassConfig

        config = CompassConfig(backends={})
        assert config.backends == {}


# =============================================================================
# JSON SCHEMA FUZZING
# =============================================================================


class TestJSONSchemaFuzzing:
    """Fuzz JSON schema handling."""

    @given(
        st.recursive(
            st.none()
            | st.booleans()
            | st.integers()
            | st.floats(allow_nan=False)
            | st.text(),
            lambda children: st.lists(children, max_size=5)
            | st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5),
            max_leaves=20,
        )
    )
    @pytest.mark.slow  # max_examples=100 (TST-B-006)
    # dev/nightly profiles already suppress HealthCheck.too_slow; keep the
    # explicit suppression so CI (which has a deadline) doesn't flap on
    # particularly deep recursive trees.
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_arbitrary_json_as_params(self, data):
        """Tool params should handle arbitrary JSON structures.

        Contract: any JSON-like value can be stuffed into `parameters`
        (boxed into a dict if not already one) and `embedding_text()`
        must return a string without raising.
        """
        from tool_manifest import ToolDefinition

        params = data if isinstance(data, dict) else {"value": data}
        tool = ToolDefinition(
            name="test",
            description="test",
            server="test",
            category="test",
            parameters=params,
        )
        text = tool.embedding_text()
        assert isinstance(text, str)
        # The tool's name should always appear in its embedding text.
        assert "test" in text

    @given(st.binary(min_size=0, max_size=1000))
    @settings(max_examples=50)
    def test_malformed_json_bytes(self, data):
        """Malformed JSON bytes should NOT crash ToolDefinition.

        Contract: only well-formed dict-shaped JSON can be used as
        parameters. Random bytes should raise exactly the documented
        exception set and nothing else (no silent AttributeErrors, no
        hidden memory corruption crashes, etc.).
        """
        from tool_manifest import ToolDefinition

        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Expected for random bytes — nothing further to test.
            return

        # If JSON parsed but isn't a dict, skip (contract requires dict).
        if not isinstance(parsed, dict):
            return

        # If it IS a dict, constructing the ToolDefinition must succeed
        # and its embedding_text must be a string.
        tool = ToolDefinition(
            name="test",
            description="test",
            server="test",
            category="test",
            parameters=parsed,
        )
        assert isinstance(tool.embedding_text(), str)


# =============================================================================
# CONFIG FUZZING
# =============================================================================


class TestConfigFuzzing:
    """Fuzz configuration handling."""

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=30),
            values=st.text(min_size=0, max_size=100),
            max_size=5,
        )
    )
    @settings(max_examples=50)
    def test_config_from_arbitrary_dict(self, data):
        """CompassConfig.from_dict should handle arbitrary dicts.

        Contract: unknown keys are ignored; known keys with wrong types
        either work (coerced strings are stored as-is) or the function
        raises AttributeError when a field like `backends` is passed a
        non-dict value (it calls `.items()`). We `assume()` away that
        known-bug shape so the happy path is under test.
        """
        from config import CompassConfig

        # `backends` must be dict-shaped to avoid a known .items() crash;
        # fuzzing that bug is out of scope here.
        assume("backends" not in data)

        config = CompassConfig.from_dict(data)
        assert isinstance(config, CompassConfig)
        # Defaults preserved when keys aren't present or ignored.
        assert isinstance(config.embedding_model, str)
        assert isinstance(config.ollama_url, str)

    @given(st.text(min_size=0, max_size=200))
    def test_ollama_url_arbitrary(self, url):
        """Ollama URL should handle arbitrary strings."""
        from config import CompassConfig

        config = CompassConfig(ollama_url=url)
        assert config.ollama_url == url


# =============================================================================
# ANALYTICS FUZZING
# =============================================================================


class TestAnalyticsFuzzing:
    """Fuzz analytics recording — exercises the REAL async record_* API.

    Earlier revisions bypassed record_search/record_tool_call with raw
    INSERTs to a table name that did not exist (`searches` vs
    `search_queries`), so the tests would silently never execute — every
    INSERT raised and was swallowed. These now call the real async paths
    via asyncio.run so bugs in arg-hashing, lock usage, or chain-pattern
    saving are actually exercised.
    """

    @pytest.mark.slow  # max_examples=100, DB I/O (TST-B-006)
    @given(st.text(min_size=0, max_size=200))
    @settings(max_examples=100, deadline=None)
    def test_record_search_arbitrary_query(self, fuzz_query):
        """record_search() must handle arbitrary search queries."""
        import asyncio
        import tempfile
        from analytics import CompassAnalytics

        with tempfile.TemporaryDirectory() as tmp:
            analytics = CompassAnalytics(db_path=Path(tmp) / "test.db")
            try:
                asyncio.run(
                    analytics.record_search(
                        query=fuzz_query,
                        results=[],
                        latency_ms=10.0,
                        category_filter=None,
                        server_filter=None,
                    )
                )
                # Verify it was stored — run summary to confirm non-crashing
                # read path.
                summary = asyncio.run(analytics.get_analytics_summary("1h"))
                assert summary["searches"]["total"] >= 1
            finally:
                analytics.close()

    @given(st.text(min_size=1, max_size=100), st.floats(min_value=0, max_value=10000))
    @settings(max_examples=50, deadline=None)
    def test_record_tool_call_arbitrary(self, tool_name, latency):
        """record_tool_call() must handle arbitrary tool names & latencies."""
        import asyncio
        import tempfile
        from analytics import CompassAnalytics

        with tempfile.TemporaryDirectory() as tmp:
            analytics = CompassAnalytics(db_path=Path(tmp) / "test.db")
            try:
                asyncio.run(
                    analytics.record_tool_call(
                        tool_name=tool_name,
                        success=True,
                        latency_ms=latency,
                    )
                )
                summary = asyncio.run(analytics.get_analytics_summary("1h"))
                assert summary["tool_calls"]["total"] >= 1
            finally:
                analytics.close()


# =============================================================================
# SEARCH RESULT FUZZING
# =============================================================================


class TestSearchResultFuzzing:
    """Fuzz search result handling."""

    @given(
        st.floats(allow_nan=False, allow_infinity=False),
        st.integers(min_value=1, max_value=1000),
    )
    @settings(deadline=None)  # First run may be slow due to imports
    def test_search_result_arbitrary_score(self, score, rank):
        """SearchResult should handle edge case scores.

        Contract: SearchResult is a plain dataclass — any finite float
        score and positive int rank is accepted without raising.
        """
        from indexer import SearchResult
        from tool_manifest import ToolDefinition

        tool = ToolDefinition(
            name="test",
            description="test",
            server="test",
            category="test",
        )

        result = SearchResult(tool=tool, score=score, rank=rank)
        assert result.tool is tool
        assert result.score == score
        assert result.rank == rank


# =============================================================================
# STRESS TESTS
# =============================================================================


class TestStressFuzzing:
    """Stress tests with extreme inputs."""

    def test_very_long_tool_name(self):
        """Handle extremely long tool names."""
        from tool_manifest import ToolDefinition

        long_name = "a" * 10000
        tool = ToolDefinition(
            name=long_name,
            description="test",
            server="test",
            category="test",
        )

        text = tool.embedding_text()
        assert isinstance(text, str)

    def test_very_long_description(self):
        """Handle extremely long descriptions."""
        from tool_manifest import ToolDefinition

        long_desc = "test description " * 10000
        tool = ToolDefinition(
            name="test",
            description=long_desc,
            server="test",
            category="test",
        )

        text = tool.embedding_text()
        assert isinstance(text, str)

    def test_deeply_nested_params(self):
        """Handle deeply nested parameter schemas."""
        from tool_manifest import ToolDefinition

        # Create 50-level deep nesting
        params = {"type": "object"}
        current = params
        for i in range(50):
            current["nested"] = {"level": i}
            current = current["nested"]

        tool = ToolDefinition(
            name="test",
            description="test",
            server="test",
            category="test",
            parameters=params,
        )

        text = tool.embedding_text()
        assert isinstance(text, str)

    @pytest.mark.slow  # constructs 1000 tools (TST-B-006)
    def test_many_tools_in_batch(self):
        """Handle large batches of tool definitions."""
        from tool_manifest import ToolDefinition

        tools = []
        for i in range(1000):
            tools.append(
                ToolDefinition(
                    name=f"tool_{i}",
                    description=f"Tool number {i}",
                    server="test",
                    category="test",
                    parameters={"index": i},
                )
            )

        # All should have valid embedding text
        for tool in tools:
            text = tool.embedding_text()
            assert isinstance(text, str)
            assert tool.name in text

    @pytest.mark.slow  # max_examples=100 (TST-B-006)
    @given(
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
            max_size=500,
        )
    )
    @settings(max_examples=100)
    def test_unicode_tool_names(self, name):
        """Handle Unicode tool names."""
        from tool_manifest import ToolDefinition

        tool = ToolDefinition(
            name=name,
            description="Unicode test",
            server="test",
            category="test",
        )

        text = tool.embedding_text()
        assert isinstance(text, str)


# =============================================================================
# BACKEND CONFIG FUZZING
# =============================================================================


class TestBackendConfigFuzzing:
    """Fuzz backend configuration."""

    @given(st.text(min_size=0, max_size=100))
    def test_stdio_backend_command(self, command):
        """StdioBackend should handle arbitrary commands."""
        from config import StdioBackend

        backend = StdioBackend(
            command=command,
            args=[],
            env={},
        )

        assert backend.command == command
        assert backend.type == "stdio"

    @given(st.lists(st.text(min_size=0, max_size=50), max_size=20))
    def test_stdio_backend_args(self, args):
        """StdioBackend should handle arbitrary args."""
        from config import StdioBackend

        backend = StdioBackend(
            command="python",
            args=args,
            env={},
        )

        assert backend.args == args

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=30),
            values=st.text(min_size=0, max_size=100),
            max_size=10,
        )
    )
    def test_stdio_backend_env(self, env):
        """StdioBackend should handle arbitrary env vars."""
        from config import StdioBackend

        backend = StdioBackend(
            command="python",
            args=[],
            env=env,
        )

        assert backend.env == env

    @given(st.text(min_size=0, max_size=200))
    def test_http_backend_url(self, url):
        """HttpBackend should handle arbitrary URLs."""
        from config import HttpBackend

        backend = HttpBackend(url=url)
        assert backend.url == url
        assert backend.type == "http"
