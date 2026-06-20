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
from unittest.mock import AsyncMock, patch

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
