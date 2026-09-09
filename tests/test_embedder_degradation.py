"""
Embedder degradation coverage (TST-B-003).

Parametrized over the three httpx failure modes the embedder sees in the
wild: ConnectError (Ollama down), ReadTimeout (Ollama slow), and the
parent TimeoutException. These tests lock in the Stage C production
contract:

- Transient errors retry (3 attempts, backoffs 0.5/1.0/2.0s).
- After _BREAKER_FAILURE_THRESHOLD consecutive failures the breaker
  opens and subsequent calls fast-fail WITHOUT hitting httpx.post.
- Once _BREAKER_OPEN_SECONDS have passed, the breaker half-opens and one
  success resets it.
- Every failure increments `total_failures` in get_stats().

We monkey-patch `time.time` (no freezegun dep) and short-circuit
asyncio.sleep so the test runs in milliseconds instead of the
0.5+1.0+2.0s real backoff.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import httpx
import numpy as np
import pytest

import embedder as embedder_module
from embedder import EMBEDDING_DIM, Embedder


# httpx failure shapes we care about. ConnectError = Ollama not listening,
# ReadTimeout = Ollama hung mid-response, TimeoutException is the parent
# class of both read/connect timeouts.
TRANSIENT_EXCS = [
    pytest.param(
        lambda: httpx.ConnectError("Connection refused"), id="ConnectError"
    ),
    pytest.param(
        lambda: httpx.ReadTimeout("Read timed out"), id="ReadTimeout"
    ),
    pytest.param(
        lambda: httpx.TimeoutException("Generic timeout"),
        id="TimeoutException",
    ),
]


def _ok_response() -> AsyncMock:
    """Build a 200-OK httpx-like response returning a valid embedding."""
    from unittest.mock import Mock

    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {
        "embeddings": [np.random.randn(EMBEDDING_DIM).tolist()]
    }
    return resp


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Don't actually wait the 0.5/1.0/2.0s backoffs in tests."""

    async def _fake_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)


@pytest.mark.parametrize("exc_factory", TRANSIENT_EXCS)
@pytest.mark.asyncio
async def test_embedder_handles_transient_errors(exc_factory):
    """Embedder retries on transient errors and eventually succeeds.

    Mocks httpx.post to fail 2x then succeed — embed() must return a
    normalized vector and the call count must be exactly 3.
    """
    emb = Embedder()

    call_count = {"n": 0}

    async def flaky_post(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise exc_factory()
        return _ok_response()

    mock_client = AsyncMock()
    mock_client.post = flaky_post

    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            result = await emb.embed("hello")
        assert isinstance(result, np.ndarray)
        assert result.shape == (EMBEDDING_DIM,)
        assert call_count["n"] == 3, "expected exactly 3 attempts (2 fail + 1 succeed)"
    finally:
        await emb.close()


@pytest.mark.parametrize("exc_factory", TRANSIENT_EXCS)
@pytest.mark.asyncio
async def test_embedder_circuit_breaker_opens_after_3_failures(exc_factory):
    """After _BREAKER_FAILURE_THRESHOLD consecutive failures the breaker
    opens and the next call raises immediately without hitting httpx.post.
    """
    emb = Embedder()

    post_calls = {"n": 0}

    async def always_fail(*_args, **_kwargs):
        post_calls["n"] += 1
        raise exc_factory()

    mock_client = AsyncMock()
    mock_client.post = always_fail

    # TESTS-004: narrow from (httpx.HTTPError, Exception) — which caught
    # literally anything — to the EXACT type the embedder surfaces on
    # exhaustion. For these transient transport errors _post_embed_with_retry
    # re-raises the original httpx exception on the final attempt, so the
    # surfaced type is precisely exc_factory()'s class. If the embedder ever
    # surfaced a different class (e.g. a bare RuntimeError), this now fails
    # instead of passing vacuously.
    expected_exc = type(exc_factory())

    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            # First call exhausts retries (3 attempts) and opens the breaker
            # — one call surfaces _BREAKER_FAILURE_THRESHOLD failures inside
            # _post_embed_with_retry.
            with pytest.raises(expected_exc):
                await emb.embed("one")

        assert emb.circuit_breaker_state() == "open", (
            "breaker must open after threshold consecutive failures"
        )
        calls_before_breaker = post_calls["n"]

        # Next call must fast-fail WITHOUT touching httpx.post.
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(RuntimeError, match="circuit breaker"):
                await emb.embed("two")
        assert post_calls["n"] == calls_before_breaker, (
            "breaker-open path must not make HTTP calls"
        )
    finally:
        await emb.close()


@pytest.mark.parametrize("exc_factory", TRANSIENT_EXCS)
@pytest.mark.asyncio
async def test_embedder_circuit_breaker_closes_on_success(exc_factory, monkeypatch):
    """Advance time past the breaker cooldown, then one success resets
    the breaker to closed.
    """
    emb = Embedder()

    # Directly drive the breaker into the open state rather than burning
    # 3 failed attempts — we're testing cool-down + recovery, not the
    # open-transition (that's the previous test).
    emb._ollama_breaker["state"] = "open"
    emb._ollama_breaker["failure_count"] = embedder_module._BREAKER_FAILURE_THRESHOLD
    emb._ollama_breaker["opened_at"] = 1000.0

    # Monkey-patch time so we jump past the 30s cooldown window.
    monkeypatch.setattr(
        embedder_module.time,
        "time",
        lambda: 1000.0 + embedder_module._BREAKER_OPEN_SECONDS + 1.0,
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_ok_response())

    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            # Breaker should half-open and this probe should succeed,
            # resetting state.
            result = await emb.embed("probe")
        assert isinstance(result, np.ndarray)
        assert emb.circuit_breaker_state() == "closed"
        assert emb._ollama_breaker["failure_count"] == 0
    finally:
        await emb.close()


@pytest.mark.parametrize("exc_factory", TRANSIENT_EXCS)
@pytest.mark.asyncio
async def test_embedder_metrics_track_failures(exc_factory):
    """get_stats()['total_failures'] increments on each transient failure.

    One embed() call that retries 3 times and eventually exhausts should
    bump total_failures by 3 (each retry counts).
    """
    emb = Embedder()

    async def always_fail(*_args, **_kwargs):
        raise exc_factory()

    mock_client = AsyncMock()
    mock_client.post = always_fail

    # TESTS-004: narrow to the EXACT surfaced type (see the comment in
    # test_embedder_circuit_breaker_opens_after_3_failures). On exhaustion of
    # these transient transport errors the embedder re-raises the original
    # httpx exception, so the surfaced type is precisely exc_factory()'s
    # class — not "anything that is an Exception".
    expected_exc = type(exc_factory())

    try:
        stats_before = emb.get_stats()
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(expected_exc):
                await emb.embed("x")
        stats_after = emb.get_stats()

        assert (
            stats_after["total_failures"] > stats_before["total_failures"]
        ), "every transient error must bump total_failures"
        # All 3 retry attempts failed before the breaker tripped.
        assert stats_after["total_failures"] - stats_before["total_failures"] == 3
    finally:
        await emb.close()


# =============================================================================
# HTTP 429 / 503 / malformed-200 (F-290fa26c)
# TRANSIENT_EXCS above only covers ConnectError / ReadTimeout / TimeoutException.
# Product OPEN F-f0f53e3b (429 is 4xx so not retried) and F-2b22af82 (HTTP 200
# with bad JSON still closes the breaker) have no test that can fail without
# these fixtures. Both Ollama /api/embed and OpenAI /v1/embeddings parse paths.
# =============================================================================


def _http_status_error(status: int, body: str = "rate limited") -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://x/embed")
    resp = httpx.Response(status, text=body, request=req)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


def _status_response(status: int, payload=None, text: str = "", headers=None):
    resp = Mock()
    resp.status_code = status
    resp.text = text if text else ("" if payload is None else str(payload))
    resp.json.return_value = payload if payload is not None else {}
    resp.headers = headers or {}
    resp.content = b"{}" if payload is None else b"x"
    return resp


def _ollama_ok():
    return _status_response(
        200, {"embeddings": [np.random.randn(EMBEDDING_DIM).tolist()]}
    )


def _openai_ok():
    return _status_response(
        200, {"data": [{"embedding": np.random.randn(EMBEDDING_DIM).tolist()}]}
    )


@pytest.fixture(params=["ollama", "openai"])
def embed_provider(request):
    return request.param


def _make_embedder(provider: str) -> Embedder:
    if provider == "openai":
        return Embedder(
            provider="openai",
            base_url="http://lmstudio:1234",
            model="text-embedding-3-small",
            api_key="sk-test",
        )
    return Embedder()


@pytest.mark.asyncio
async def test_http_429_is_classified_rate_limited_not_retried(embed_provider):
    """429 is 4xx: not retried. Message must say rate-limited, not a generic dump."""
    emb = _make_embedder(embed_provider)
    calls = {"n": 0}

    async def post_429(*_a, **_k):
        calls["n"] += 1
        return _status_response(
            429,
            {"error": "too many requests"},
            text="too many requests",
            headers={"Retry-After": "7"},
        )

    mock_client = AsyncMock()
    mock_client.post = post_429
    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(RuntimeError) as raised:
                await emb.embed("hello")
        msg = str(raised.value).lower()
        assert "429" in msg
        assert "rate limited" in msg, f"429 must be classified, got: {raised.value!r}"
        assert "retry-after=7" in msg
        assert calls["n"] == 1, "4xx 429 must not be retried"
        assert emb.circuit_breaker_state() == "closed"
    finally:
        await emb.close()


@pytest.mark.asyncio
async def test_httpstatuserror_429_is_not_a_generic_4xx_dump():
    """If httpx raises HTTPStatusError(429), classify or propagate — not silent."""
    emb = Embedder(provider="openai", base_url="http://x:1")
    calls = {"n": 0}

    async def raise_429(*_a, **_k):
        calls["n"] += 1
        raise _http_status_error(429, "quota")

    mock_client = AsyncMock()
    mock_client.post = raise_429
    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises((httpx.HTTPStatusError, RuntimeError)) as raised:
                await emb.embed("hello")
        blob = str(raised.value).lower()
        assert "429" in blob or "rate" in blob or "quota" in blob
        # HTTPStatusError is not TransportError, so the retry loop does not
        # swallow it as a generic 5xx retry storm.
        assert calls["n"] == 1
    finally:
        await emb.close()


@pytest.mark.asyncio
async def test_http_503_is_retried(embed_provider):
    emb = _make_embedder(embed_provider)
    calls = {"n": 0}
    ok = _openai_ok() if embed_provider == "openai" else _ollama_ok()

    async def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 3:
            return _status_response(503, text="unavailable")
        return ok

    mock_client = AsyncMock()
    mock_client.post = flaky
    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            result = await emb.embed("hello")
        assert isinstance(result, np.ndarray)
        assert result.shape == (EMBEDDING_DIM,)
        assert calls["n"] == 3
    finally:
        await emb.close()


def _malformed_raise_cases():
    """Payloads whose parse_vector / dim check must raise (not NaN, which parses)."""
    cases = []
    mapping = {
        "ollama": [
            ({}, "ollama-missing-embeddings"),
            ({"embeddings": []}, "ollama-empty-embeddings"),
            ({"embeddings": [[0.1, 0.2]]}, "ollama-wrong-dim"),
        ],
        "openai": [
            ({"data": []}, "openai-missing-data0"),
            ({}, "openai-missing-data-key"),
            ({"data": [{"embedding": [0.1, 0.2]}]}, "openai-wrong-dim"),
        ],
    }
    for provider, rows in mapping.items():
        for payload, case_id in rows:
            cases.append(pytest.param(provider, payload, id=case_id))
    return cases


@pytest.mark.parametrize("provider,payload", _malformed_raise_cases())
@pytest.mark.asyncio
async def test_malformed_200_missing_or_wrong_dim_raises(provider, payload):
    """HTTP 200 whose json() is missing embeddings / wrong length must not
    return a vector. (NaN parses today — see test_malformed_200_nan_has_dim.)
    """
    emb = _make_embedder(provider)
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_status_response(200, payload))
    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(
                (RuntimeError, KeyError, TypeError, IndexError, ValueError)
            ):
                await emb.embed("hello")
    finally:
        await emb.close()


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.asyncio
async def test_malformed_200_nan_has_configured_dim(provider):
    """NaN embeddings currently parse; pin dim so a truncated dump fails.

    Rejecting NaN / not _record_success is OPEN F-2b22af82 — a later product
    fix that raises here still satisfies this test's raise-or-shape contract.
    """
    emb = _make_embedder(provider)
    if provider == "openai":
        payload = {"data": [{"embedding": [float("nan")] * EMBEDDING_DIM}]}
    else:
        payload = {"embeddings": [[float("nan")] * EMBEDDING_DIM]}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_status_response(200, payload))
    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            try:
                result = await emb.embed("hello")
            except (RuntimeError, ValueError, TypeError):
                return
            assert isinstance(result, np.ndarray)
            assert result.shape == (EMBEDDING_DIM,)
    finally:
        await emb.close()


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.asyncio
async def test_malformed_200_does_not_count_as_embed_success_metric(provider):
    """A 200 that fails parse must not look like a successful logical embed
    to callers — the exception is the lock. Breaker close-on-200 is OPEN
    F-2b22af82 and is not asserted here.
    """
    emb = _make_embedder(provider)
    payload = {} if provider == "ollama" else {"data": []}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_status_response(200, payload))
    try:
        before = emb.get_stats()
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(
                (RuntimeError, KeyError, TypeError, IndexError, ValueError)
            ):
                await emb.embed("hello")
        after = emb.get_stats()
        # Logical call is counted; a silent swallow would leave total_calls
        # unchanged AND return a vector (the raise above already failed that).
        assert after["total_calls"] == before["total_calls"] + 1
    finally:
        await emb.close()


@pytest.mark.asyncio
async def test_httpstatuserror_503_is_retryable_shape():
    """HTTPStatusError 503: if raised from post(), it is not a 4xx dump."""
    emb = Embedder()
    calls = {"n": 0}

    async def raise_503(*_a, **_k):
        calls["n"] += 1
        raise _http_status_error(503, "unavailable")

    mock_client = AsyncMock()
    mock_client.post = raise_503
    try:
        with patch.object(emb, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises((httpx.HTTPStatusError, RuntimeError)):
                await emb.embed("hello")
        # Raised HTTPStatusError is not caught as TransportError, so one shot.
        # A 503 *response* (status_code=503) is retried in the sibling test.
        assert calls["n"] >= 1
    finally:
        await emb.close()

