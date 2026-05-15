"""
Tool Compass - Embedder Module
Handles embedding generation via Ollama's nomic-embed-text model.
"""

import httpx
import numpy as np
from typing import Callable, List, Optional, Tuple
import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768  # nomic-embed-text dimension

# Circuit breaker + retry tuning (IDX-B-002, IDX-B-004).
# BE-B-014: defaults; CompassConfig overrides at Embedder.__init__.
_BREAKER_FAILURE_THRESHOLD = 3
_BREAKER_OPEN_SECONDS = 30.0
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFFS = (0.5, 1.0, 2.0)

# BE-A-010 + BE-B-005: process-wide concurrency cap on Ollama embed calls.
# Previously embed_batch() created `asyncio.Semaphore(8)` per call, which
# enforced batch-local concurrency but never serialized concurrent batches.
# This module-level semaphore caps ACROSS the process: indexing rebuild
# + simultaneous query embeddings share the same 8 slots.
_GLOBAL_EMBED_CONCURRENCY = 8
_global_embed_semaphore: Optional[asyncio.Semaphore] = None


def _get_global_embed_semaphore() -> asyncio.Semaphore:
    """Lazy-init the process-wide semaphore on the active event loop."""
    global _global_embed_semaphore
    if _global_embed_semaphore is None:
        _global_embed_semaphore = asyncio.Semaphore(_GLOBAL_EMBED_CONCURRENCY)
    return _global_embed_semaphore


class Embedder:
    """
    Async embedder using Ollama's nomic-embed-text model.
    Optimized for tool description embedding.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = EMBEDDING_MODEL,
        timeout: float = 30.0,
        breaker_failure_threshold: Optional[int] = None,
        breaker_open_seconds: Optional[float] = None,
        retry_attempts: Optional[int] = None,
        retry_backoffs: Optional[Tuple[float, ...]] = None,
        on_breaker_transition: Optional[Callable[[str, str], None]] = None,
    ):
        """Initialize embedder.

        Args (all optional, default to module-level constants — promoted to
        CompassConfig per BE-B-014):
            breaker_failure_threshold: consecutive failures before opening.
            breaker_open_seconds: cooldown before half-open probe.
            retry_attempts: max retry count per call.
            retry_backoffs: per-attempt sleep schedule.
            on_breaker_transition: callback fired on state transition
                (from_state, to_state) — used by the gateway to emit the
                breaker_transitions_total counter (BE-B-002).
        """
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

        self._breaker_failure_threshold = (
            int(breaker_failure_threshold)
            if breaker_failure_threshold is not None
            else _BREAKER_FAILURE_THRESHOLD
        )
        self._breaker_open_seconds = (
            float(breaker_open_seconds)
            if breaker_open_seconds is not None
            else _BREAKER_OPEN_SECONDS
        )
        self._retry_attempts = (
            int(retry_attempts) if retry_attempts is not None else _RETRY_ATTEMPTS
        )
        self._retry_backoffs = (
            tuple(retry_backoffs)
            if retry_backoffs is not None
            else _RETRY_BACKOFFS
        )
        self._on_breaker_transition = on_breaker_transition

        self._client: Optional[httpx.AsyncClient] = None

        # Circuit breaker state (IDX-B-002 + BE-B-006).
        # States: closed | half_open | open.
        # half_open lets exactly ONE probe through after cooldown; the result
        # decides whether we close (success) or re-open (failure). Without
        # half_open the breaker oscillates hard on flaky upstreams.
        self._ollama_breaker = {
            "state": "closed",  # closed | half_open | open
            "failure_count": 0,
            "opened_at": 0.0,
            "probe_in_flight": False,
        }
        # BE-B-006: ensure at most one probe enters the half-open window.
        self._breaker_lock = asyncio.Lock()

        # Metrics (IDX-B-003 + BE-B-005 + BE-B-013).
        # latency_samples is a bounded deque of per-call latency in
        # milliseconds. inflight + queue_wait_ms_samples are saturation
        # signals (BE-B-005). last_success_at + consecutive_failures are
        # forensic signals for "when did Ollama last work" (BE-B-013).
        self._metrics = {
            "total_calls": 0,
            "total_failures": 0,
            "latency_samples": deque(maxlen=1000),  # ms
            "queue_wait_ms_samples": deque(maxlen=1000),  # ms
            "inflight": 0,
            "consecutive_failures": 0,
            "last_success_at": 0.0,
        }
        self._inflight_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        """Check if Ollama is available and model is loaded.

        BE-A-021: prefer exact match (with or without ':latest' suffix) over
        substring containment so 'foo-nomic-embed-text-v2' doesn't accidentally
        match 'nomic-embed-text'. Substring fallback remains for backward
        compat with already-tagged-but-renamed models.
        """
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                names = [m.get("name", "") for m in data.get("models", [])]
                if any(
                    n == self.model
                    or n == f"{self.model}:latest"
                    or n.startswith(f"{self.model}:")
                    for n in names
                ):
                    return True
                # Defensive: substring fallback.
                return any(self.model in n for n in names if n)
            return False
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def pull_model(self) -> bool:
        """Pull the embedding model if not present."""
        try:
            client = await self._get_client()
            response = await client.post(
                "/api/pull",
                json={"name": self.model},
                timeout=300.0,  # Model download can take time
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to pull model: {e}")
            return False

    def _set_breaker_state(self, new_state: str) -> None:
        """Transition the breaker, firing the optional callback (BE-B-002).

        Always updates `state` even if the new state equals the old; callbacks
        only fire on a real transition so /metrics doesn't churn.
        """
        br = self._ollama_breaker
        old = br["state"]
        if old != new_state:
            br["state"] = new_state
            if self._on_breaker_transition is not None:
                try:
                    self._on_breaker_transition(old, new_state)
                except Exception as e:
                    logger.debug(f"on_breaker_transition callback failed: {e}")
        else:
            br["state"] = new_state

    def _breaker_check(self) -> None:
        """Raise fast if the Ollama circuit breaker is open (IDX-B-002 + BE-B-006).

        Three-state machine: closed | half_open | open.
        - closed: requests flow normally.
        - open: requests fast-fail until cooldown elapses; first request after
          cooldown transitions to half_open and is allowed through as a probe.
        - half_open: probe in flight; further requests fast-fail until the
          probe resolves. _record_success transitions to closed; _record_failure
          transitions back to open.
        """
        br = self._ollama_breaker
        state = br["state"]
        if state == "closed":
            return
        if state == "open":
            if time.time() - br["opened_at"] >= self._breaker_open_seconds:
                # Cooldown elapsed — half-open: allow exactly one probe.
                if not br["probe_in_flight"]:
                    br["probe_in_flight"] = True
                    self._set_breaker_state("half_open")
                    return
                # Cooldown elapsed but another probe is racing — fast fail.
                raise RuntimeError("Ollama circuit breaker half-open (probe in flight)")
            raise RuntimeError("Ollama circuit breaker open")
        if state == "half_open":
            # Probe already in flight — sibling requests fast-fail to avoid
            # the Hystrix anti-pattern of concurrent probes during recovery.
            raise RuntimeError("Ollama circuit breaker half-open (probe in flight)")

    def _record_success(self, latency_ms: float) -> None:
        """Reset breaker failure count and log latency sample."""
        self._metrics["total_calls"] += 1
        self._metrics["latency_samples"].append(latency_ms)
        self._metrics["consecutive_failures"] = 0
        self._metrics["last_success_at"] = time.monotonic()
        br = self._ollama_breaker
        if br["state"] != "closed":
            self._set_breaker_state("closed")
        br["failure_count"] = 0
        br["opened_at"] = 0.0
        br["probe_in_flight"] = False

    def _record_failure(self) -> None:
        """Increment failure count; open breaker at threshold."""
        self._metrics["total_calls"] += 1
        self._metrics["total_failures"] += 1
        self._metrics["consecutive_failures"] += 1
        br = self._ollama_breaker
        br["failure_count"] += 1
        # If this failure happened during a half-open probe, snap straight
        # back to open and reset the cooldown timer.
        if br["state"] == "half_open":
            self._set_breaker_state("open")
            br["opened_at"] = time.time()
            br["probe_in_flight"] = False
            return
        if br["failure_count"] >= self._breaker_failure_threshold:
            self._set_breaker_state("open")
            br["opened_at"] = time.time()
            br["probe_in_flight"] = False

    def circuit_breaker_state(self) -> str:
        """Public accessor for gateway fallback logic (IDX-B-002 + BE-B-006)."""
        return self._ollama_breaker["state"]

    def get_stats(self) -> dict:
        """Return embedder metrics snapshot (IDX-B-003 + BE-B-005 + BE-B-013).

        latency percentiles are computed from the bounded sample deque.
        failure_rate is 0.0 when no calls have been made (not NaN).

        Added in BE-B-005 / BE-B-013:
            inflight: live count of in-flight embed calls
            queue_wait_ms_{p50,p95}: time spent waiting for the global
                concurrency semaphore (leading saturation indicator)
            consecutive_failures: "how close are we to tripping right now"
            time_since_last_success_ms: "when did Ollama last work"
        """
        samples = list(self._metrics["latency_samples"])
        total_calls = self._metrics["total_calls"]
        total_failures = self._metrics["total_failures"]

        if samples:
            sorted_samples = sorted(samples)
            n = len(sorted_samples)
            p50 = sorted_samples[n // 2]
            # p95 index: floor(0.95 * n), clamped.
            p95_idx = min(n - 1, int(n * 0.95))
            p95 = sorted_samples[p95_idx]
        else:
            p50 = 0.0
            p95 = 0.0

        qw_samples = list(self._metrics["queue_wait_ms_samples"])
        if qw_samples:
            qw_sorted = sorted(qw_samples)
            qn = len(qw_sorted)
            qw_p50 = qw_sorted[qn // 2]
            qw_p95 = qw_sorted[min(qn - 1, int(qn * 0.95))]
        else:
            qw_p50 = 0.0
            qw_p95 = 0.0

        failure_rate = (total_failures / total_calls) if total_calls > 0 else 0.0

        last_success = self._metrics["last_success_at"]
        time_since_last_success_ms = (
            (time.monotonic() - last_success) * 1000.0
            if last_success > 0
            else None
        )

        return {
            "total_calls": total_calls,
            "total_failures": total_failures,
            "failure_rate": failure_rate,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "circuit_breaker": self._ollama_breaker["state"],
            "consecutive_failures": self._metrics["consecutive_failures"],
            "time_since_last_success_ms": time_since_last_success_ms,
            "inflight": self._metrics["inflight"],
            "queue_wait_ms_p50": qw_p50,
            "queue_wait_ms_p95": qw_p95,
            "global_concurrency_limit": _GLOBAL_EMBED_CONCURRENCY,
        }

    async def _post_embed_with_retry(
        self,
        client: httpx.AsyncClient,
        payload: dict,
        trace_id: Optional[str] = None,
    ) -> httpx.Response:
        """POST /api/embed with retry on transient failures (IDX-B-004 + BE-B-014).

        Retries on: TransportError, TimeoutException, 5xx responses.
        Does NOT retry 4xx (client errors).
        Every failed attempt counts toward the circuit breaker.
        Breaker must be probed BEFORE entering this method so we don't
        waste attempts when Ollama is known-down.

        Retry attempts and backoff are taken from instance config (BE-B-014).
        """
        last_exc: Optional[BaseException] = None
        attempts = self._retry_attempts
        backoffs = self._retry_backoffs
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post("/api/embed", json=payload)
                if response.status_code >= 500:
                    # Transient server error — retry.
                    err = f"HTTP {response.status_code}: {response.text[:200]}"
                    self._record_failure()
                    last_exc = RuntimeError(err)
                    if attempt < attempts:
                        # backoffs has `attempts - 1` entries by convention.
                        wait = backoffs[min(attempt - 1, len(backoffs) - 1)]
                        logger.warning(
                            f"Ollama embed retry {attempt}/{attempts} "
                            f"after {wait}s: {err}"
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise last_exc
                if response.status_code != 200:
                    # 4xx — don't retry, don't count toward breaker (not Ollama's fault).
                    raise RuntimeError(
                        f"Embedding failed ({response.status_code}): {response.text}"
                    )
                return response
            except (httpx.TransportError, httpx.TimeoutException) as e:
                self._record_failure()
                last_exc = e
                if attempt < attempts:
                    wait = backoffs[min(attempt - 1, len(backoffs) - 1)]
                    logger.warning(
                        f"Ollama embed retry {attempt}/{attempts} "
                        f"after {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        # Unreachable — loop either returns or raises.
        assert last_exc is not None
        raise last_exc

    async def _inflight_incr(self) -> None:
        async with self._inflight_lock:
            self._metrics["inflight"] += 1

    async def _inflight_decr(self) -> None:
        async with self._inflight_lock:
            self._metrics["inflight"] = max(0, self._metrics["inflight"] - 1)

    async def _embed_with_concurrency_cap(
        self,
        prefixed_text: str,
        trace_id: Optional[str],
    ) -> np.ndarray:
        """Acquire global semaphore, do one POST /api/embed, normalize.

        Centralizes:
        - process-wide concurrency cap (BE-A-010)
        - queue-wait histogram + inflight gauge (BE-B-005)
        - breaker check + success/failure recording (IDX-B-002 + BE-B-006)
        """
        # Breaker gate before queueing; fast-fail freed slot is cheaper than
        # entering the queue, waiting, then failing.
        self._breaker_check()

        sem = _get_global_embed_semaphore()
        client = await self._get_client()

        queue_start = time.monotonic()
        async with sem:
            queue_wait_ms = (time.monotonic() - queue_start) * 1000.0
            self._metrics["queue_wait_ms_samples"].append(queue_wait_ms)
            # Re-check breaker after acquiring the slot — state may have
            # re-opened while waiting (another concurrent failure tripped it).
            # Note: a half_open state with probe_in_flight=True here means
            # WE are that probe (set by our own first _breaker_check above);
            # the canonical _breaker_check would falsely reject it, so we
            # only guard the closed→open transition during the queue wait.
            if self._ollama_breaker["state"] == "open":
                raise RuntimeError("Ollama circuit breaker re-opened during queue wait")

            await self._inflight_incr()
            try:
                start = time.monotonic()
                response = await self._post_embed_with_retry(
                    client,
                    {"model": self.model, "input": prefixed_text},
                    trace_id=trace_id,
                )
                latency_ms = (time.monotonic() - start) * 1000.0
                self._record_success(latency_ms)
                logger.debug(
                    "embed complete",
                    extra={
                        "event": "embed",
                        "latency_ms": latency_ms,
                        "queue_wait_ms": queue_wait_ms,
                        "model": self.model,
                        "trace_id": trace_id,
                    },
                )
            finally:
                await self._inflight_decr()

        data = response.json()
        embedding = np.array(data["embeddings"][0], dtype=np.float32)

        # Normalize for cosine similarity
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

    async def embed(
        self, text: str, trace_id: Optional[str] = None
    ) -> np.ndarray:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed (tool description, query, etc.)
            trace_id: Optional correlation ID for structured logs.

        Returns:
            numpy array of shape (EMBEDDING_DIM,)
        """
        # Add task prefix for better retrieval (nomic-embed-text recommendation)
        prefixed_text = f"search_document: {text}"
        return await self._embed_with_concurrency_cap(prefixed_text, trace_id)

    async def embed_query(
        self, query: str, trace_id: Optional[str] = None
    ) -> np.ndarray:
        """
        Generate embedding for a search query.
        Uses search_query prefix for better retrieval.

        Args:
            query: Search query (user intent)
            trace_id: Optional correlation ID for structured logs.

        Returns:
            numpy array of shape (EMBEDDING_DIM,)
        """
        # Query prefix for retrieval tasks
        prefixed_query = f"search_query: {query}"
        return await self._embed_with_concurrency_cap(prefixed_query, trace_id)

    async def embed_batch(
        self, texts: List[str], trace_id: Optional[str] = None
    ) -> np.ndarray:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            trace_id: Optional correlation ID propagated to per-item embed() calls.

        Returns:
            numpy array of shape (len(texts), EMBEDDING_DIM)

        BE-A-010 + BE-B-005: concurrency is now enforced at process scope by
        the module-level semaphore (acquired inside each embed() call), so
        embed_batch no longer creates its own per-call Semaphore. Indexing
        rebuild + concurrent query embeddings share the same 8 slots.
        """
        tasks = [self.embed(text, trace_id=trace_id) for text in texts]
        embeddings = await asyncio.gather(*tasks)
        return np.stack(embeddings)


# Synchronous wrapper for non-async contexts
class SyncEmbedder:
    """Synchronous wrapper around async Embedder.

    Safe to call from:
    - A normal synchronous context (no running loop) — uses asyncio.run()
    - Inside an active event loop (e.g., Gradio, FastMCP) — runs the
      coroutine in a dedicated worker thread with its own loop
    """

    def __init__(self, **kwargs):
        self._async_embedder = Embedder(**kwargs)

    def _run(self, coro):
        """Run coroutine safely from any context."""
        try:
            asyncio.get_running_loop()
            # A loop is already running (e.g., Gradio, FastMCP) —
            # run_until_complete would crash, so use a worker thread.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        except RuntimeError:
            # No running loop — safe to use asyncio.run directly.
            return asyncio.run(coro)

    def health_check(self) -> bool:
        return self._run(self._async_embedder.health_check())

    def embed(self, text: str) -> np.ndarray:
        return self._run(self._async_embedder.embed(text))

    def embed_query(self, query: str) -> np.ndarray:
        return self._run(self._async_embedder.embed_query(query))

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        return self._run(self._async_embedder.embed_batch(texts))

    def close(self):
        self._run(self._async_embedder.close())


if __name__ == "__main__":
    # Quick test
    async def test():
        embedder = Embedder()

        print("Checking Ollama health...")
        healthy = await embedder.health_check()
        print(f"Ollama available: {healthy}")

        if healthy:
            print("\nGenerating test embedding...")
            emb = await embedder.embed("Read file contents from disk")
            print(f"Embedding shape: {emb.shape}")
            print(f"Embedding norm: {np.linalg.norm(emb):.4f}")

            print("\nGenerating query embedding...")
            query_emb = await embedder.embed_query("I need to read a file")
            print(f"Query embedding shape: {query_emb.shape}")

            # Test similarity
            similarity = np.dot(emb, query_emb)
            print(f"Similarity: {similarity:.4f}")

        await embedder.close()

    asyncio.run(test())
