"""
Tool Compass - Embedder Module
Handles embedding generation via Ollama's nomic-embed-text model.
"""

import httpx
import numpy as np
from typing import List, Optional
import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768  # nomic-embed-text dimension

# Circuit breaker + retry tuning (IDX-B-002, IDX-B-004)
_BREAKER_FAILURE_THRESHOLD = 3
_BREAKER_OPEN_SECONDS = 30.0
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFFS = (0.5, 1.0, 2.0)


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
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

        # Circuit breaker state (IDX-B-002). Tracks consecutive Ollama
        # failures so we fast-fail when Ollama is offline instead of eating
        # the 30s timeout on every call.
        self._ollama_breaker = {
            "state": "closed",  # closed | open
            "failure_count": 0,
            "opened_at": 0.0,
        }

        # Metrics (IDX-B-003). latency_samples is a bounded deque of
        # per-call latency in milliseconds — keeps memory flat while
        # giving us enough samples for p50/p95.
        self._metrics = {
            "total_calls": 0,
            "total_failures": 0,
            "latency_samples": deque(maxlen=1000),  # ms
        }

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
        """Check if Ollama is available and model is loaded."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [m["name"] for m in data.get("models", [])]
                # Check if our model is available (with or without :latest tag)
                return any(self.model in m for m in models)
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

    def _breaker_check(self) -> None:
        """Raise fast if the Ollama circuit breaker is open (IDX-B-002).

        If the breaker opened more than _BREAKER_OPEN_SECONDS ago, half-open
        by resetting to closed so the next call can probe Ollama again.
        """
        br = self._ollama_breaker
        if br["state"] == "open":
            if time.time() - br["opened_at"] >= _BREAKER_OPEN_SECONDS:
                # Cooldown elapsed — allow one probe.
                br["state"] = "closed"
                br["failure_count"] = 0
            else:
                raise RuntimeError("Ollama circuit breaker open")

    def _record_success(self, latency_ms: float) -> None:
        """Reset breaker failure count and log latency sample."""
        self._metrics["total_calls"] += 1
        self._metrics["latency_samples"].append(latency_ms)
        br = self._ollama_breaker
        br["state"] = "closed"
        br["failure_count"] = 0
        br["opened_at"] = 0.0

    def _record_failure(self) -> None:
        """Increment failure count; open breaker at threshold."""
        self._metrics["total_calls"] += 1
        self._metrics["total_failures"] += 1
        br = self._ollama_breaker
        br["failure_count"] += 1
        if br["failure_count"] >= _BREAKER_FAILURE_THRESHOLD:
            br["state"] = "open"
            br["opened_at"] = time.time()

    def circuit_breaker_state(self) -> str:
        """Public accessor for gateway fallback logic (IDX-B-002)."""
        return self._ollama_breaker["state"]

    def get_stats(self) -> dict:
        """Return embedder metrics snapshot (IDX-B-003).

        latency percentiles are computed from the bounded sample deque.
        failure_rate is 0.0 when no calls have been made (not NaN).
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

        failure_rate = (total_failures / total_calls) if total_calls > 0 else 0.0

        return {
            "total_calls": total_calls,
            "total_failures": total_failures,
            "failure_rate": failure_rate,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "circuit_breaker": self._ollama_breaker["state"],
        }

    async def _post_embed_with_retry(
        self,
        client: httpx.AsyncClient,
        payload: dict,
        trace_id: Optional[str] = None,
    ) -> httpx.Response:
        """POST /api/embed with 3-attempt retry on transient failures (IDX-B-004).

        Retries on: TransportError, TimeoutException, 5xx responses.
        Does NOT retry 4xx (client errors).
        Every failed attempt counts toward the circuit breaker.
        Breaker must be probed BEFORE entering this method so we don't
        waste attempts when Ollama is known-down.
        """
        last_exc: Optional[BaseException] = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                response = await client.post("/api/embed", json=payload)
                if response.status_code >= 500:
                    # Transient server error — retry.
                    err = f"HTTP {response.status_code}: {response.text[:200]}"
                    self._record_failure()
                    last_exc = RuntimeError(err)
                    if attempt < _RETRY_ATTEMPTS:
                        wait = _RETRY_BACKOFFS[attempt - 1]
                        logger.warning(
                            f"Ollama embed retry {attempt}/{_RETRY_ATTEMPTS} "
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
                if attempt < _RETRY_ATTEMPTS:
                    wait = _RETRY_BACKOFFS[attempt - 1]
                    logger.warning(
                        f"Ollama embed retry {attempt}/{_RETRY_ATTEMPTS} "
                        f"after {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        # Unreachable — loop either returns or raises.
        assert last_exc is not None
        raise last_exc

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
        # Fast-fail when breaker is open so the gateway's lexical fallback
        # kicks in immediately instead of eating the timeout.
        self._breaker_check()

        client = await self._get_client()

        # Add task prefix for better retrieval (nomic-embed-text recommendation)
        prefixed_text = f"search_document: {text}"

        start = time.monotonic()
        try:
            response = await self._post_embed_with_retry(
                client,
                {"model": self.model, "input": prefixed_text},
                trace_id=trace_id,
            )
        except Exception:
            # _post_embed_with_retry records failures internally for transient
            # errors; 4xx raises without recording, which is intentional.
            raise
        latency_ms = (time.monotonic() - start) * 1000.0
        self._record_success(latency_ms)
        logger.debug(
            "embed complete",
            extra={
                "event": "embed",
                "latency_ms": latency_ms,
                "model": self.model,
                "trace_id": trace_id,
            },
        )

        data = response.json()
        embedding = np.array(data["embeddings"][0], dtype=np.float32)

        # Normalize for cosine similarity
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

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
        # Breaker gate — when open, raise immediately so the gateway can
        # fall back to lexical search without a 30s timeout.
        self._breaker_check()

        client = await self._get_client()

        # Query prefix for retrieval tasks
        prefixed_query = f"search_query: {query}"

        start = time.monotonic()
        response = await self._post_embed_with_retry(
            client,
            {"model": self.model, "input": prefixed_query},
            trace_id=trace_id,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        self._record_success(latency_ms)
        logger.debug(
            "embed_query complete",
            extra={
                "event": "embed",
                "latency_ms": latency_ms,
                "model": self.model,
                "trace_id": trace_id,
            },
        )

        data = response.json()
        embedding = np.array(data["embeddings"][0], dtype=np.float32)

        # Normalize for cosine similarity
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

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
        """
        # Ollama doesn't support true batching, so we parallelize.
        # Cap concurrency so we don't overwhelm Ollama (or the async runtime)
        # when indexing large tool lists.
        semaphore = asyncio.Semaphore(8)

        async def _bounded_embed(text: str) -> np.ndarray:
            async with semaphore:
                return await self.embed(text, trace_id=trace_id)

        tasks = [_bounded_embed(text) for text in texts]
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
