"""
Gateway HTTP-handler coverage suite — drives /health, /ready, /metrics inside
_run_http() WITHOUT binding a real socket. We patch ``mcp.run`` to no-op so
_run_http() registers the three Starlette routes onto
``mcp._custom_starlette_routes`` and returns, then we extract the registered
handlers and exercise them directly against a Mock request.

This covers gateway.py lines 1927-2354 (the entire _run_http body) which
were the single biggest gap in coverage.
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import Mock, AsyncMock, patch

import pytest


# =============================================================================
# Helpers to extract closures registered inside _run_http()
# =============================================================================


def _extract_http_routes(port: int = 0):
    """Run gateway._run_http with mcp.run mocked, then return {name: handler}.

    The three handlers are async closures registered onto
    mcp._custom_starlette_routes. We patch the registry to a fresh list so
    repeated invocations don't leak.
    """
    import gateway

    fresh_routes = []
    # Patch the custom_starlette_routes list to a private one for this call.
    with patch.object(
        gateway.mcp,
        "_custom_starlette_routes",
        new=fresh_routes,
    ):
        # Patch mcp.run so _run_http doesn't actually start serving.
        with patch.object(gateway.mcp, "run", new=Mock()):
            # Use an inert TransportSecuritySettings so nothing else binds.
            gateway._run_http(port=port)

    return {r.path: r.endpoint for r in fresh_routes}


async def _read_starlette_response_body(response):
    """Pull bytes out of a Starlette Response in a portable way."""
    # JSONResponse.body and PlainTextResponse.body are already bytes.
    return response.body


# =============================================================================
# /health handler
# =============================================================================


class TestHttpHealth:
    """The /health handler always returns 200."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        routes = _extract_http_routes()
        health_handler = routes["/health"]

        request = Mock()
        response = await health_handler(request)

        # Status 200 + JSON shape.
        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["status"] == "ok"
        assert body["server"] == "tool-compass-gateway"
        assert "version" in body


# =============================================================================
# /ready handler — happy path, failure paths, cache TTLs
# =============================================================================


class TestHttpReady:
    """The /ready handler is the deep readiness probe (GW-FT-003)."""

    @pytest.mark.asyncio
    async def test_ready_all_checks_pass(
        self, test_index, test_config_with_backends
    ):
        """200 when index loaded, Ollama up, at least one backend connected."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True

        # Wire embedder.circuit_breaker_state so ready picks up 'closed'.
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.is_backend_connected = Mock(return_value=True)
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        ready_handler = routes["/ready"]

        request = Mock()
        response = await ready_handler(request)
        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["status"] == "ready"
        assert body["checks"]["index"]["ok"] is True
        assert body["checks"]["ollama"]["ok"] is True
        assert body["checks"]["backends"]["ok"] is True

    @pytest.mark.asyncio
    async def test_ready_index_not_loaded(self, test_config):
        """503 when index is None."""
        import gateway

        gateway._compass_index = None
        gateway._backend_manager = None
        gateway._config = test_config
        gateway._health_state["ollama_available"] = False

        routes = _extract_http_routes()
        response = await routes["/ready"](Mock())

        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["status"] == "not_ready"
        assert body["checks"]["index"]["ok"] is False

    @pytest.mark.asyncio
    async def test_ready_ollama_down(
        self, test_index, test_config_with_backends
    ):
        """503 when Ollama is unreachable (breaker not closed)."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = False
        # Force breaker state != closed.
        test_index.embedder.circuit_breaker_state = Mock(return_value="open")

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.is_backend_connected = Mock(return_value=True)
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/ready"](Mock())

        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["checks"]["ollama"]["ok"] is False
        assert body["checks"]["ollama"]["breaker"] == "open"

    @pytest.mark.asyncio
    async def test_ready_breaker_state_raises_handled(
        self, test_index, test_config_with_backends
    ):
        """When embedder.circuit_breaker_state raises, the check still runs."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True

        test_index.embedder.circuit_breaker_state = Mock(
            side_effect=RuntimeError("breaker exploded")
        )

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.is_backend_connected = Mock(return_value=True)
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/ready"](Mock())

        # Falls back to _health_state["ollama_available"] which is True.
        body = json.loads(response.body)
        assert body["checks"]["ollama"]["ok"] is True

    @pytest.mark.asyncio
    async def test_ready_no_backends_connected(
        self, test_index, test_config_with_backends
    ):
        """503 when configured backends exist but none connected."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True

        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")

        mgr = Mock()
        mgr.config = test_config_with_backends  # has 1 backend configured
        mgr.is_backend_connected = Mock(return_value=False)
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/ready"](Mock())

        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["checks"]["backends"]["ok"] is False
        assert "no backends connected" in body["checks"]["backends"].get("reason", "")

    @pytest.mark.asyncio
    async def test_ready_backends_block_raises_handled(
        self, test_index, test_config_with_backends
    ):
        """If backend access raises, the check is reported as not ok."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")

        mgr = Mock()
        # Accessing config raises.
        type(mgr).config = property(lambda self: (_ for _ in ()).throw(RuntimeError("nope")))
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/ready"](Mock())

        # 503 because backend check raised -> ok=False.
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["checks"]["backends"]["ok"] is False

    @pytest.mark.asyncio
    async def test_ready_cache_hit_returns_same_body(
        self, test_index, test_config_with_backends
    ):
        """The /ready response caches within its TTL."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True

        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.is_backend_connected = Mock(return_value=True)
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        ready_handler = routes["/ready"]

        # Two back-to-back calls -> second should hit the cache.
        r1 = await ready_handler(Mock())
        r2 = await ready_handler(Mock())

        assert r1.status_code == 200
        assert r2.status_code == 200
        # Both bodies are identical.
        assert json.loads(r1.body) == json.loads(r2.body)

    @pytest.mark.asyncio
    async def test_ready_no_configured_backends_passes(
        self, test_index, test_config
    ):
        """When no backends are configured, backend_ok is True (degenerate)."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config  # backends={} on test_config
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")

        mgr = Mock()
        mgr.config = test_config  # no backends configured
        mgr.is_backend_connected = Mock(return_value=False)
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/ready"](Mock())

        body = json.loads(response.body)
        # Empty configured backends -> ok=True (operator may run without
        # backends for index-only inspection).
        assert body["checks"]["backends"]["ok"] is True

    @pytest.mark.asyncio
    async def test_ready_index_check_exception_handled(
        self, test_config_with_backends
    ):
        """If the index check itself raises, ready handler still produces a
        body with index.ok=False."""
        import gateway

        # Use a Mock that raises when getattr(db) is accessed AND provides a
        # working embedder so the second probe (Ollama breaker) doesn't blow
        # up serialization.
        bad_index = Mock()
        type(bad_index).db = property(lambda self: (_ for _ in ()).throw(RuntimeError("bad")))
        # embedder.circuit_breaker_state returns a real string so the JSON
        # serializer doesn't fail on a Mock value.
        bad_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        gateway._compass_index = bad_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.is_backend_connected = Mock(return_value=True)
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/ready"](Mock())

        body = json.loads(response.body)
        assert body["checks"]["index"]["ok"] is False


# =============================================================================
# /metrics handler — every gauge + counter emission path
# =============================================================================


class TestHttpMetrics:
    """The /metrics handler emits OpenMetrics text."""

    @pytest.mark.asyncio
    async def test_metrics_basic_emission(
        self, test_index, test_config_with_backends
    ):
        """Even with no data, /metrics emits all required gauges and the EOF
        terminator."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        gateway._analytics = None
        gateway._backend_manager = None

        # Wire embedder.circuit_breaker_state + get_stats so the metric body
        # populates real numbers.
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={
            "p95_latency_ms": 12.5,
            "total_failures": 0,
            "inflight": 1,
            "consecutive_failures": 0,
            "time_since_last_success_ms": 5000,
            "queue_wait_ms_p95": 10.0,
        })

        routes = _extract_http_routes()
        metrics_handler = routes["/metrics"]

        response = await metrics_handler(Mock())
        body = response.body.decode("utf-8")

        # All the # HELP lines are present.
        assert "tool_compass_search_total" in body
        assert "tool_compass_ollama_available 1" in body
        assert "tool_compass_embed_latency_p95_ms" in body
        assert "tool_compass_embed_failures_total" in body
        assert "tool_compass_embedder_inflight" in body
        assert "tool_compass_embedder_queue_wait_seconds" in body
        assert "tool_compass_embed_consecutive_failures" in body
        assert "tool_compass_embed_time_since_last_success_seconds" in body
        assert "tool_compass_circuit_breaker_transitions_total" in body
        assert "tool_compass_lexical_fallback_total" in body
        assert "tool_compass_fallback_invocations_total" in body
        assert "tool_compass_degraded_responses_total" in body
        assert "tool_compass_hnsw_search_duration_seconds" in body
        assert "tool_compass_index_age_seconds" in body
        assert "tool_compass_orphaned_vectors" in body
        # OpenMetrics terminator.
        assert body.endswith("# EOF\n")
        # Media type.
        assert "openmetrics-text" in response.media_type

    @pytest.mark.asyncio
    async def test_metrics_with_analytics(
        self, test_index, test_config_with_backends
    ):
        """/metrics consults analytics for total search count."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        analytics = Mock()
        # Common-shape return — has 'total_searches' on root.
        analytics.get_analytics_summary = AsyncMock(return_value={
            "total_searches": 42,
        })
        gateway._analytics = analytics

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        # Search total should be 42 now (any of the matched keys works).
        assert "tool_compass_search_total 42" in body

    @pytest.mark.asyncio
    async def test_metrics_with_analytics_nested_search_stats(
        self, test_index, test_config_with_backends
    ):
        """/metrics tolerates the search_stats.total nesting too."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        analytics = Mock()
        analytics.get_analytics_summary = AsyncMock(return_value={
            "search_stats": {"total": 17},
        })
        gateway._analytics = analytics

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert "tool_compass_search_total 17" in body

    @pytest.mark.asyncio
    async def test_metrics_with_analytics_raise_tolerated(
        self, test_index, test_config_with_backends
    ):
        """Analytics raising during /metrics doesn't blow up the response."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        analytics = Mock()
        analytics.get_analytics_summary = AsyncMock(
            side_effect=RuntimeError("analytics down")
        )
        gateway._analytics = analytics

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        # Falls back to 0; emission must still terminate cleanly.
        assert "tool_compass_search_total 0" in body
        assert body.endswith("# EOF\n")

    @pytest.mark.asyncio
    async def test_metrics_with_backend_manager(
        self, test_index, test_config_with_backends
    ):
        """/metrics emits per-backend gauges + call counters."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.get_stats = Mock(return_value={
            "configured_backends": ["test_backend"],
            "connected_backends": ["test_backend"],
            "stats": {"test_backend": {"total_calls": 10, "failed_calls": 2}},
        })
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_backend_up{name="test_backend"} 1' in body
        # 10 total - 2 failed = 8 success.
        assert 'tool_compass_backend_call_total{name="test_backend",status="success"} 8' in body
        assert 'tool_compass_backend_call_total{name="test_backend",status="error"} 2' in body

    @pytest.mark.asyncio
    async def test_metrics_backend_disconnected(
        self, test_index, test_config_with_backends
    ):
        """A configured backend that isn't connected reports up=0."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.get_stats = Mock(return_value={
            "configured_backends": ["test_backend"],
            "connected_backends": [],
            "stats": {"test_backend": {"total_calls": 0, "failed_calls": 0}},
        })
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_backend_up{name="test_backend"} 0' in body

    @pytest.mark.asyncio
    async def test_metrics_backend_stats_raises_tolerated(
        self, test_index, test_config_with_backends
    ):
        """If backend manager.get_stats() raises, /metrics still emits."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        mgr = Mock()
        mgr.config = test_config_with_backends
        mgr.get_stats = Mock(side_effect=RuntimeError("stats died"))
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        # Must still terminate.
        assert body.endswith("# EOF\n")

    @pytest.mark.asyncio
    async def test_metrics_with_circuit_breaker_transitions(
        self, test_index, test_config_with_backends
    ):
        """/metrics emits per-transition counter lines when transitions seen."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        # Inject some transitions.
        gateway._metric_counters["circuit_breaker_transitions_total"]["closed->open"] = 3
        gateway._metric_counters["circuit_breaker_transitions_total"]["open->half_open"] = 1

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_circuit_breaker_transitions_total{from="closed",to="open",breaker="ollama"} 3' in body
        assert 'tool_compass_circuit_breaker_transitions_total{from="open",to="half_open",breaker="ollama"} 1' in body

        # Cleanup.
        gateway._metric_counters["circuit_breaker_transitions_total"].clear()

    @pytest.mark.asyncio
    async def test_metrics_with_fallback_invocations(
        self, test_index, test_config_with_backends
    ):
        """/metrics emits per-type fallback counter lines."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        gateway._metric_counters["fallback_invocations_total"]["lexical"] = 5
        gateway._metric_counters["fallback_invocations_total"]["chain"] = 2

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_fallback_invocations_total{type="lexical"} 5' in body
        assert 'tool_compass_fallback_invocations_total{type="chain"} 2' in body

        gateway._metric_counters["fallback_invocations_total"].clear()

    @pytest.mark.asyncio
    async def test_metrics_with_degraded_responses(
        self, test_index, test_config_with_backends
    ):
        """/metrics emits per-reason degraded counter lines."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        gateway._metric_counters["degraded_responses_total"]["ollama_unavailable"] = 7

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_degraded_responses_total{reason="ollama_unavailable"} 7' in body

        gateway._metric_counters["degraded_responses_total"].clear()

    @pytest.mark.asyncio
    async def test_metrics_index_stats_consulted(
        self, test_index, test_config_with_backends
    ):
        """/metrics uses index.get_stats() for index_age + orphan + hnsw p95."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        # Patch get_stats to surface the relevant gauges.
        original_get_stats = test_index.get_stats
        test_index.get_stats = Mock(return_value={
            "total_tools": 100,
            "by_category": {},
            "by_server": {},
            "index_age_seconds": 3600,
            "orphaned_vector_count": 5,
            "hnsw_search_latency_ms_p95": 12.0,
            "hnsw": {"ef_search": 80},
        })

        try:
            routes = _extract_http_routes()
            response = await routes["/metrics"](Mock())
            body = response.body.decode("utf-8")
        finally:
            test_index.get_stats = original_get_stats

        # ef_search label is rendered into the hnsw histogram line.
        assert 'tool_compass_hnsw_search_duration_seconds{ef_search="80"}' in body
        # And the index_age + orphan gauges populated.
        assert "tool_compass_index_age_seconds 3600" in body
        assert "tool_compass_orphaned_vectors 5" in body

    @pytest.mark.asyncio
    async def test_metrics_embedder_stats_raises_tolerated(
        self, test_index, test_config_with_backends
    ):
        """If embedder.get_stats() raises, /metrics still emits with zeros."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(
            side_effect=RuntimeError("embedder stats died")
        )

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert "tool_compass_embed_latency_p95_ms 0" in body
        assert body.endswith("# EOF\n")

    @pytest.mark.asyncio
    async def test_metrics_index_stats_raises_tolerated(
        self, test_index, test_config_with_backends
    ):
        """If index.get_stats() raises, /metrics still emits."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        original_get_stats = test_index.get_stats
        test_index.get_stats = Mock(side_effect=RuntimeError("stats died"))

        try:
            routes = _extract_http_routes()
            response = await routes["/metrics"](Mock())
            body = response.body.decode("utf-8")
        finally:
            test_index.get_stats = original_get_stats

        assert "tool_compass_index_age_seconds" in body
        assert body.endswith("# EOF\n")

    @pytest.mark.asyncio
    async def test_metrics_ollama_state_raise_tolerated(
        self, test_index, test_config_with_backends
    ):
        """If embedder.circuit_breaker_state raises, fall back to health_state."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(
            side_effect=RuntimeError("breaker dead")
        )
        test_index.embedder.get_stats = Mock(return_value={})

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        # Falls back to _health_state value -> ollama_available=True, so 1.
        assert "tool_compass_ollama_available 1" in body

    @pytest.mark.asyncio
    async def test_metrics_escapes_labels(
        self, test_index, test_config_with_backends
    ):
        """Backend names with special chars are escaped in label values."""
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        mgr = Mock()
        mgr.config = test_config_with_backends
        # Name with a backslash + quote -> needs escaping.
        mgr.get_stats = Mock(return_value={
            "configured_backends": ['back\\quoted"name'],
            "connected_backends": [],
            "stats": {},
        })
        gateway._backend_manager = mgr

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        # Backslash escaped, quote escaped.
        assert 'back\\\\quoted\\"name' in body


# =============================================================================
# /metrics — empty-state defaults (counters that emit zero-line placeholders)
# =============================================================================


class TestHttpMetricsEmptyDefaults:
    """Counters with no data still emit a zero-valued line (dashboards
    require the metric to exist)."""

    @pytest.mark.asyncio
    async def test_metrics_zero_transitions_emits_placeholder(
        self, test_index, test_config_with_backends
    ):
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        # Clear transitions so the placeholder branch fires.
        gateway._metric_counters["circuit_breaker_transitions_total"].clear()

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_circuit_breaker_transitions_total{from="closed",to="closed",breaker="ollama"} 0' in body

    @pytest.mark.asyncio
    async def test_metrics_zero_fallback_emits_placeholder(
        self, test_index, test_config_with_backends
    ):
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        gateway._metric_counters["fallback_invocations_total"].clear()

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_fallback_invocations_total{type="lexical"} 0' in body

    @pytest.mark.asyncio
    async def test_metrics_zero_degraded_emits_placeholder(
        self, test_index, test_config_with_backends
    ):
        import gateway

        gateway._compass_index = test_index
        gateway._config = test_config_with_backends
        gateway._health_state["ollama_available"] = True
        test_index.embedder.circuit_breaker_state = Mock(return_value="closed")
        test_index.embedder.get_stats = Mock(return_value={})

        gateway._metric_counters["degraded_responses_total"].clear()

        routes = _extract_http_routes()
        response = await routes["/metrics"](Mock())
        body = response.body.decode("utf-8")

        assert 'tool_compass_degraded_responses_total{reason="ollama_unavailable"} 0' in body


# =============================================================================
# HOST env var warning path
# =============================================================================


class TestRunHttpHostEnvVarWarning:
    """_run_http logs a warning when HOST is non-loopback."""

    @pytest.mark.asyncio
    async def test_run_http_warns_when_non_loopback_host(self, caplog):
        """A HOST set to a public IP should log a warning."""
        import gateway

        old_host = os.environ.get("HOST")
        os.environ["HOST"] = "0.0.0.0"

        try:
            with caplog.at_level("WARNING"):
                # _extract_http_routes invokes _run_http with mcp.run mocked,
                # so the warning fires during route registration.
                _extract_http_routes()
            # WARNING about non-loopback was emitted.
            assert any(
                "non-loopback" in r.message or "non-loopback" in str(r) or "0.0.0.0" in r.message
                for r in caplog.records
            )
        finally:
            if old_host is None:
                os.environ.pop("HOST", None)
            else:
                os.environ["HOST"] = old_host

    @pytest.mark.asyncio
    async def test_run_http_no_warning_for_loopback_host(self, caplog):
        """A HOST=127.0.0.1 should NOT warn."""
        import gateway

        old_host = os.environ.get("HOST")
        os.environ["HOST"] = "127.0.0.1"

        try:
            with caplog.at_level("WARNING"):
                _extract_http_routes()
            # No 'non-loopback' warning.
            assert not any(
                "non-loopback" in (r.message or "")
                for r in caplog.records
            )
        finally:
            if old_host is None:
                os.environ.pop("HOST", None)
            else:
                os.environ["HOST"] = old_host
