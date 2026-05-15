"""
Tests for the Hystrix Outcome enum + ConnectionStats accounting.

Covers BR-B-004 (Hystrix-style outcome taxonomy) — every record_call(outcome=...)
path. Verifies that ConnectionStats counters increment correctly per outcome
and that failed_calls is only incremented for real backend-failure outcomes
(protocol_error / transport_error / timeout / backend_unavailable) — never
for tool_error or shutdown_cancelled, which the legacy boolean API would have
counted as failures.

Also covers the error envelope builder (BR-B-001 / BR-B-012) and the custom
exception types (BackendShuttingDownError, BackendNotConnectedError,
BackendOverloadedError, BackendProtocolError).
"""

from __future__ import annotations

import logging

import pytest

from backend_client_simple import (
    ConnectionStats,
    OUTCOME_SUCCESS,
    OUTCOME_TOOL_ERROR,
    OUTCOME_PROTOCOL_ERROR,
    OUTCOME_TRANSPORT_ERROR,
    OUTCOME_TIMEOUT,
    OUTCOME_BACKEND_UNAVAILABLE,
    OUTCOME_SHUTDOWN_CANCELLED,
    BackendShuttingDownError,
    BackendNotConnectedError,
    BackendOverloadedError,
    BackendProtocolError,
    make_error_envelope,
)


# =============================================================================
# Outcome enum: every record_call path
# =============================================================================


class TestRecordCallOutcomes:
    """Drive every outcome through ConnectionStats.record_call."""

    def test_success_outcome_increments_total_only(self):
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_SUCCESS, latency_ms=10.0)
        assert stats.total_calls == 1
        assert stats.failed_calls == 0
        assert stats.outcomes[OUTCOME_SUCCESS] == 1
        assert stats.avg_latency_ms == 10.0

    def test_tool_error_does_not_count_as_backend_failure(self):
        """BR-B-004: tool_error is in-band — backend is healthy."""
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_TOOL_ERROR, latency_ms=5.0)
        assert stats.total_calls == 1
        assert stats.failed_calls == 0
        assert stats.outcomes[OUTCOME_TOOL_ERROR] == 1

    def test_protocol_error_increments_failed_calls(self):
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_PROTOCOL_ERROR, latency_ms=5.0)
        assert stats.total_calls == 1
        assert stats.failed_calls == 1
        assert stats.outcomes[OUTCOME_PROTOCOL_ERROR] == 1

    def test_transport_error_increments_failed_calls(self):
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_TRANSPORT_ERROR, latency_ms=5.0)
        assert stats.failed_calls == 1
        assert stats.outcomes[OUTCOME_TRANSPORT_ERROR] == 1

    def test_timeout_increments_failed_calls(self):
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_TIMEOUT, latency_ms=15000.0)
        assert stats.failed_calls == 1
        assert stats.outcomes[OUTCOME_TIMEOUT] == 1

    def test_backend_unavailable_increments_failed_calls(self):
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_BACKEND_UNAVAILABLE, latency_ms=1.0)
        assert stats.failed_calls == 1
        assert stats.outcomes[OUTCOME_BACKEND_UNAVAILABLE] == 1

    def test_shutdown_cancelled_does_not_count_as_backend_failure(self):
        """BR-B-004: shutdown_cancelled is operator action, never a failure."""
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_SHUTDOWN_CANCELLED, latency_ms=1.0)
        assert stats.total_calls == 1
        assert stats.failed_calls == 0
        assert stats.outcomes[OUTCOME_SHUTDOWN_CANCELLED] == 1

    def test_outcome_wins_over_success_flag(self):
        """If both outcome=... and success=True/False, outcome takes precedence."""
        stats = ConnectionStats()
        # success=True would imply OUTCOME_SUCCESS, but outcome= overrides.
        stats.record_call(success=True, outcome=OUTCOME_TIMEOUT, latency_ms=5.0)
        assert stats.failed_calls == 1
        assert stats.outcomes[OUTCOME_TIMEOUT] == 1
        assert OUTCOME_SUCCESS not in stats.outcomes

    def test_legacy_success_false_records_failed_call_but_as_tool_error(self):
        """Legacy API: success=False -> failed_calls++ AND bucketed as tool_error."""
        stats = ConnectionStats()
        stats.record_call(success=False, latency_ms=5.0)
        assert stats.total_calls == 1
        # Legacy callers had no way to tell tool_error from real failure;
        # preserve their failed_calls semantics for backward-compat.
        assert stats.failed_calls == 1
        # But categorise the OUTCOME conservatively so new health gauges
        # are not corrupted.
        assert stats.outcomes[OUTCOME_TOOL_ERROR] == 1

    def test_legacy_no_args_defaults_to_success(self):
        stats = ConnectionStats()
        stats.record_call()
        assert stats.total_calls == 1
        assert stats.failed_calls == 0
        assert stats.outcomes[OUTCOME_SUCCESS] == 1

    def test_unknown_outcome_coerces_to_tool_error_and_warns(self, caplog):
        """Defensive: unknown outcome string is bucketed conservatively."""
        stats = ConnectionStats()
        with caplog.at_level(logging.WARNING):
            stats.record_call(outcome="bogus", latency_ms=1.0)  # type: ignore[arg-type]
        assert stats.outcomes[OUTCOME_TOOL_ERROR] == 1
        # Unknown outcomes must not silently corrupt the health signal.
        assert "unknown outcome" in caplog.text.lower()

    def test_running_average_across_mixed_outcomes(self):
        """Latency average is independent of outcome bucket."""
        stats = ConnectionStats()
        stats.record_call(outcome=OUTCOME_SUCCESS, latency_ms=100.0)
        stats.record_call(outcome=OUTCOME_TOOL_ERROR, latency_ms=200.0)
        stats.record_call(outcome=OUTCOME_TIMEOUT, latency_ms=300.0)
        # (100 + 200 + 300) / 3 = 200
        assert stats.avg_latency_ms == pytest.approx(200.0)
        assert stats.total_calls == 3
        # Only timeout was a real backend failure.
        assert stats.failed_calls == 1

    def test_last_used_advances_on_every_call(self):
        stats = ConnectionStats()
        assert stats.last_used is None
        stats.record_call(outcome=OUTCOME_SUCCESS)
        first = stats.last_used
        assert first is not None
        stats.record_call(outcome=OUTCOME_TOOL_ERROR)
        assert stats.last_used is not None
        assert stats.last_used >= first


# =============================================================================
# make_error_envelope: every optional field
# =============================================================================


class TestErrorEnvelope:
    """BR-B-001 / BR-B-012 stable contract — verify each field."""

    def test_minimal_envelope_has_required_fields(self):
        env = make_error_envelope(
            error_kind=OUTCOME_PROTOCOL_ERROR,
            error="boom",
        )
        assert env["success"] is False
        assert env["error_kind"] == OUTCOME_PROTOCOL_ERROR
        assert env["error"] == "boom"
        assert "backend" not in env
        assert "code" not in env
        assert "data" not in env
        assert "retryable" not in env
        assert "content" not in env

    def test_envelope_with_backend(self):
        env = make_error_envelope(
            error_kind=OUTCOME_TIMEOUT,
            error="too slow",
            backend="bridge",
        )
        assert env["backend"] == "bridge"

    def test_envelope_with_code_and_data(self):
        env = make_error_envelope(
            error_kind=OUTCOME_PROTOCOL_ERROR,
            error="rpc error",
            code=-32601,
            data={"detail": "method not found"},
        )
        assert env["code"] == -32601
        assert env["data"] == {"detail": "method not found"}

    def test_envelope_with_retryable_true(self):
        env = make_error_envelope(
            error_kind=OUTCOME_TOOL_ERROR,
            error="retry me",
            retryable=True,
        )
        assert env["retryable"] is True

    def test_envelope_with_retryable_false(self):
        env = make_error_envelope(
            error_kind=OUTCOME_PROTOCOL_ERROR,
            error="do not retry",
            retryable=False,
        )
        assert env["retryable"] is False

    def test_envelope_with_content_preserves_structure(self):
        """tool_error path preserves the MCP content array intact."""
        content = [
            {"type": "text", "text": "oops"},
            {"type": "image", "data": "..."},
        ]
        env = make_error_envelope(
            error_kind=OUTCOME_TOOL_ERROR,
            error="oops",
            content=content,
            retryable=True,
        )
        assert env["content"] == content
        # Importantly, the structured shape is preserved — not flattened.
        assert env["content"][0]["type"] == "text"


# =============================================================================
# Exception types
# =============================================================================


class TestExceptionTypes:
    """Verify the structured exception fields are preserved through str()."""

    def test_backend_shutting_down_is_runtime_error(self):
        exc = BackendShuttingDownError("shutdown")
        assert isinstance(exc, RuntimeError)
        assert "shutdown" in str(exc)

    def test_backend_not_connected_includes_backend_name(self):
        exc = BackendNotConnectedError("bridge")
        assert exc.backend_name == "bridge"
        assert exc.reason == "connection not established"
        assert "bridge" in str(exc)

    def test_backend_not_connected_with_reason(self):
        exc = BackendNotConnectedError("bridge", "process pipes missing")
        assert exc.reason == "process pipes missing"
        assert "process pipes missing" in str(exc)

    def test_backend_overloaded_has_cap(self):
        exc = BackendOverloadedError("bridge", 64)
        assert exc.backend_name == "bridge"
        assert exc.cap == 64
        assert "64" in str(exc)

    def test_backend_protocol_error_with_code(self):
        exc = BackendProtocolError(-32601, "Method not found", {"foo": "bar"})
        assert exc.code == -32601
        assert exc.message == "Method not found"
        assert exc.data == {"foo": "bar"}
        # str representation includes code marker.
        assert "code=-32601" in str(exc)
        assert "Method not found" in str(exc)

    def test_backend_protocol_error_without_code(self):
        exc = BackendProtocolError(None, "raw failure")
        assert exc.code is None
        assert exc.data is None
        # No "[code=..]" prefix when code is None.
        assert "code=" not in str(exc)
        assert "raw failure" in str(exc)
