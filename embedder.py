"""
Tool Compass - Embedder Module
Handles embedding generation via a *pluggable* provider backend.

Provider seam (BE-FT-PE-001)
============================
Historically this module was hard-wired to Ollama's ``POST /api/embed``
endpoint with the nomic-embed-text ``search_query:`` / ``search_document:``
prefix convention. The low-risk seam decouples the *transport orchestration*
(circuit breaker + retry + per-loop concurrency cap + cache + metrics) from
the *provider-specific* parts:

    - the endpoint path appended to ``base_url`` (Ollama: ``/api/embed``),
    - the request body shape (Ollama: ``{"model", "input"}``),
    - where the vector lives in the JSON response
      (Ollama: ``data["embeddings"][0]``),
    - the per-kind text prefix (nomic: ``search_query:`` / ``search_document:``),
    - any auth headers (OpenAI-compatible: ``Authorization: Bearer <key>``).

Everything the orchestration layer does is unchanged: ``Embedder`` still owns
``_embed_with_concurrency_cap`` / ``_post_embed_with_retry`` / the breaker /
``_record_*`` / the per-loop semaphore. They now call
``self._provider.endpoint_path`` / ``build_body`` / ``parse_vector`` /
``apply_prefix`` / ``request_headers`` instead of the hardcoded Ollama call.

Adding a new backend (e.g. sentence-transformers, Cohere) means writing an
``EmbeddingProvider`` subclass and registering it via ``@register_provider``
— the orchestration layer never changes.
"""

import httpx
import numpy as np
from typing import Callable, Dict, List, Optional, Tuple, Type
import asyncio
import logging
import time
import weakref
from collections import deque

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768  # nomic-embed-text dimension

# Default provider — current behavior. Keeping this a module constant means a
# bare Embedder() embeds byte-for-byte identically to the pre-seam code.
DEFAULT_PROVIDER = "ollama"

# nomic-embed-text retrieval-prefix convention. Non-nomic models (OpenAI etc.)
# don't use it, so providers expose configurable/empty prefixes.
NOMIC_QUERY_PREFIX = "search_query: "
NOMIC_DOCUMENT_PREFIX = "search_document: "

# Circuit breaker + retry tuning (IDX-B-002, IDX-B-004).
# BE-B-014: defaults; CompassConfig overrides at Embedder.__init__.
_BREAKER_FAILURE_THRESHOLD = 3
_BREAKER_OPEN_SECONDS = 30.0
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFFS = (0.5, 1.0, 2.0)

# BE-A-010 + BE-B-005: process-wide concurrency cap on Ollama embed calls.
# Previously embed_batch() created `asyncio.Semaphore(8)` per call, which
# enforced batch-local concurrency but never serialized concurrent batches.
# The cap is per-event-loop: indexing rebuild + simultaneous query
# embeddings on the SAME loop share the same 8 slots.
#
# SC-001: an asyncio.Semaphore is bound to the loop it has waiters on. The
# SyncEmbedder._run / CompassIndex.search_sync / ui.py paths spin a fresh
# worker-thread loop per call (asyncio.run). A single module-global
# semaphore awaited from loop B once it had waiters on loop A raised
# "RuntimeError: ... is bound to a different event loop", silently
# degrading to lexical fallback. Keying the semaphore on id(running_loop)
# — created lazily INSIDE the running loop — gives each loop its own cap
# and removes the cross-loop binding entirely. A WeakValueDictionary lets
# dead loops' semaphores be garbage-collected once their loop is gone.
_GLOBAL_EMBED_CONCURRENCY = 8
_loop_embed_semaphores: "weakref.WeakValueDictionary[int, asyncio.Semaphore]" = (
    weakref.WeakValueDictionary()
)
# Strong refs keyed on the loop object keep each loop's semaphore alive for
# the loop's lifetime (WeakValueDictionary alone would let it die between
# awaits while no coroutine holds it). Entries drop when the loop is GC'd.
_loop_embed_semaphore_owners: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _get_global_embed_semaphore() -> asyncio.Semaphore:
    """Return the concurrency semaphore for the *running* event loop.

    Created lazily inside the running loop and cached per-loop so a
    semaphore is never awaited from a loop other than the one it was
    created on (SC-001).
    """
    loop = asyncio.get_event_loop()
    key = id(loop)
    sem = _loop_embed_semaphores.get(key)
    if sem is None:
        sem = asyncio.Semaphore(_GLOBAL_EMBED_CONCURRENCY)
        _loop_embed_semaphores[key] = sem
        # Anchor a strong ref to the loop's lifetime so the semaphore
        # isn't collected between awaits.
        _loop_embed_semaphore_owners[loop] = sem
    return sem


# =============================================================================
# Provider seam (BE-FT-PE-001)
# =============================================================================
#
# An EmbeddingProvider isolates the provider-specific request/response details.
# It is intentionally tiny and stateless w.r.t. the orchestration layer: it
# does NOT own the httpx client, the breaker, retries, or the cache. The
# Embedder calls into it for exactly five things:
#
#   endpoint_path                -> path appended to base_url for the POST
#   request_headers()            -> auth/content headers for the POST
#   build_body(text)             -> the JSON body dict
#   parse_vector(json_response)  -> the raw embedding list out of the JSON
#   apply_prefix(text, kind)     -> retrieval prefix ('query' | 'document')
#
# This keeps the seam at the smallest possible surface — the same retry +
# breaker + concurrency + cache + metrics path serves every provider.


class EmbeddingProvider:
    """Base class for a provider-specific embedding backend.

    Subclasses customize the endpoint, body shape, response parse, auth
    headers, and retrieval-prefix convention. The orchestration layer
    (breaker/retry/concurrency/cache/metrics) lives entirely in ``Embedder``
    and is never touched by a provider.
    """

    #: Provider name as used in config + the registry. Subclasses set this.
    name: str = "base"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        query_prefix: Optional[str] = None,
        document_prefix: Optional[str] = None,
    ):
        # base_url is normalized (no trailing slash) so endpoint joins are
        # predictable regardless of how the operator wrote it in config.
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key
        # None means "use this provider's default prefix"; "" means "no prefix"
        # (an explicit operator choice). We distinguish them deliberately.
        self.query_prefix = (
            query_prefix if query_prefix is not None else self.default_query_prefix
        )
        self.document_prefix = (
            document_prefix
            if document_prefix is not None
            else self.default_document_prefix
        )

    # --- prefix convention -------------------------------------------------
    default_query_prefix: str = ""
    default_document_prefix: str = ""

    def apply_prefix(self, text: str, kind: str) -> str:
        """Prefix ``text`` per the retrieval convention for ``kind``.

        kind is 'query' or 'document'. Unknown kinds get the document prefix
        (the conservative default — corpus embeddings outnumber queries).
        """
        if kind == "query":
            return f"{self.query_prefix}{text}"
        return f"{self.document_prefix}{text}"

    # --- transport ---------------------------------------------------------
    @property
    def endpoint_path(self) -> str:
        """Path appended to base_url for the embed POST. Override per provider."""
        raise NotImplementedError

    def request_headers(self) -> Dict[str, str]:
        """Headers for the embed POST. Default: none (Ollama needs no auth)."""
        return {}

    def build_body(self, text: str) -> dict:
        """Build the JSON request body for one already-prefixed text."""
        raise NotImplementedError

    def parse_vector(self, data: dict) -> list:
        """Pull the raw embedding list out of the parsed JSON response."""
        raise NotImplementedError


class OllamaProvider(EmbeddingProvider):
    """Default provider — Ollama's ``POST /api/embed`` (byte-for-byte legacy).

    Body: ``{"model", "input"}``. Vector at ``data["embeddings"][0]``.
    Prefixes: the nomic search_query/search_document convention.
    """

    name = "ollama"
    default_query_prefix = NOMIC_QUERY_PREFIX
    default_document_prefix = NOMIC_DOCUMENT_PREFIX

    @property
    def endpoint_path(self) -> str:
        return "/api/embed"

    def build_body(self, text: str) -> dict:
        return {"model": self.model, "input": text}

    def parse_vector(self, data: dict) -> list:
        # Legacy parse — kept exactly as the pre-seam code:
        # data["embeddings"][0].
        return data["embeddings"][0]


class OpenAICompatibleProvider(EmbeddingProvider):
    """OpenAI / OpenAI-compatible provider — ``POST {base}/v1/embeddings``.

    Covers OpenAI, LM Studio, and any server exposing the OpenAI embeddings
    contract. Body: ``{"model", "input"}``. Vector at
    ``data["data"][0]["embedding"]``. An api_key (from config or env) is sent
    as ``Authorization: Bearer <key>``. Prefixes default to empty because
    non-nomic models don't use the search_* retrieval convention; an operator
    can still set them explicitly via config.
    """

    name = "openai"
    # Non-nomic models: no retrieval prefix by default.
    default_query_prefix = ""
    default_document_prefix = ""

    @property
    def endpoint_path(self) -> str:
        return "/v1/embeddings"

    def request_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def build_body(self, text: str) -> dict:
        return {"model": self.model, "input": text}

    def parse_vector(self, data: dict) -> list:
        # OpenAI embeddings contract: data["data"][0]["embedding"].
        return data["data"][0]["embedding"]


# --- registry / factory ----------------------------------------------------
#
# The registry is the documented extension point. To add a backend later
# (sentence-transformers, Cohere, ...) write an EmbeddingProvider subclass and
# decorate it with @register_provider — no orchestration-layer changes needed.

_PROVIDER_REGISTRY: Dict[str, Type[EmbeddingProvider]] = {}


def register_provider(cls: Type[EmbeddingProvider]) -> Type[EmbeddingProvider]:
    """Class decorator: register an EmbeddingProvider under its ``name``.

    Also registers any aliases listed in a ``aliases`` class attribute so
    'openai-compatible' resolves to the OpenAI provider.
    """
    _PROVIDER_REGISTRY[cls.name] = cls
    for alias in getattr(cls, "aliases", ()):  # pragma: no branch
        _PROVIDER_REGISTRY[alias] = cls
    return cls


# Register the two shipped providers. 'openai-compatible' is an alias so both
# spellings in config resolve to the same backend.
OpenAICompatibleProvider.aliases = ("openai-compatible",)
register_provider(OllamaProvider)
register_provider(OpenAICompatibleProvider)


def known_providers() -> Tuple[str, ...]:
    """Return the sorted tuple of registered provider names (incl. aliases)."""
    return tuple(sorted(_PROVIDER_REGISTRY.keys()))


def create_provider(
    provider: Optional[str],
    base_url: str,
    model: str,
    api_key: Optional[str] = None,
    query_prefix: Optional[str] = None,
    document_prefix: Optional[str] = None,
) -> EmbeddingProvider:
    """Factory: build the EmbeddingProvider for ``provider``.

    An unknown provider name warns and falls back to the default (ollama) so a
    typo in config degrades gracefully to working behavior rather than
    crashing the embed path — mirroring CompassConfig.validate_and_clamp's
    "warn + fall back" discipline.
    """
    key = (provider or DEFAULT_PROVIDER).strip().lower()
    cls = _PROVIDER_REGISTRY.get(key)
    if cls is None:
        logger.warning(
            "Unknown embedding_provider %r; falling back to %r. "
            "Known providers: %s",
            provider,
            DEFAULT_PROVIDER,
            ", ".join(known_providers()),
        )
        cls = _PROVIDER_REGISTRY[DEFAULT_PROVIDER]
    return cls(
        base_url=base_url,
        model=model,
        api_key=api_key,
        query_prefix=query_prefix,
        document_prefix=document_prefix,
    )


class Embedder:
    """
    Async embedder with a pluggable provider backend (default: Ollama).

    The orchestration layer — circuit breaker + retry + per-loop concurrency
    cap + metrics — is provider-agnostic. Provider-specific details
    (endpoint, body, response parse, auth, prefixes) live behind
    ``self._provider``. A bare ``Embedder()`` is byte-for-byte the legacy
    Ollama nomic-embed-text embedder.
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
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        query_prefix: Optional[str] = None,
        document_prefix: Optional[str] = None,
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

        Provider seam (BE-FT-PE-001 — all optional, default to the legacy
        Ollama behavior so a bare ``Embedder()`` is unchanged):
            provider: backend name ('ollama' [default] / 'openai' /
                'openai-compatible'). Unknown -> warn + fall back to ollama.
            api_key: secret for OpenAI-compatible auth (Authorization: Bearer).
            query_prefix / document_prefix: override the retrieval prefix
                convention. None -> the provider's default (nomic search_* for
                ollama, empty for openai).
        """
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

        # Build the provider behind the orchestration layer. An unknown name
        # warns + falls back to ollama (graceful degradation, not a crash).
        self.provider_name = (provider or DEFAULT_PROVIDER).strip().lower()
        self._provider = create_provider(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            query_prefix=query_prefix,
            document_prefix=document_prefix,
        )
        # Reflect the actually-resolved provider name (post fallback) so
        # callers/metrics report the truth, not the requested-but-unknown name.
        self.provider_name = self._provider.name

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
        """Reset breaker failure count and log latency sample.

        SC-003: total_calls is counted ONCE per logical embed in
        _embed_with_concurrency_cap, NOT here — recording it on success (and
        on every failed attempt in _record_failure) triple-counted a single
        embed that retried, inflating failure_rate and tripping the breaker
        sooner than the threshold implies.
        """
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
        """Increment failure count; open breaker at threshold.

        SC-003: only touches failure_count / consecutive_failures /
        total_failures. total_calls is incremented once per logical embed in
        _embed_with_concurrency_cap, regardless of how many attempts the
        retry loop made — so one embed that fails N times then succeeds
        records total_calls=1, not N+1.
        """
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
        """POST the provider's embed endpoint with retry (IDX-B-004 + BE-B-014).

        Retries on: TransportError, TimeoutException, 5xx responses.
        Does NOT retry 4xx (client errors).
        Every failed attempt counts toward the circuit breaker.
        Breaker must be probed BEFORE entering this method so we don't
        waste attempts when the backend is known-down.

        Retry attempts and backoff are taken from instance config (BE-B-014).

        BE-FT-PE-001: the endpoint path + auth headers come from the provider
        (Ollama: ``/api/embed`` + no headers; OpenAI-compatible:
        ``/v1/embeddings`` + ``Authorization: Bearer``). The retry/breaker
        logic itself is untouched.
        """
        last_exc: Optional[BaseException] = None
        attempts = self._retry_attempts
        backoffs = self._retry_backoffs
        endpoint = self._provider.endpoint_path
        headers = self._provider.request_headers()
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(
                    endpoint, json=payload, headers=headers
                )
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

            # SC-003: count the LOGICAL embed exactly once here, regardless
            # of how many retry attempts _post_embed_with_retry makes or
            # whether it ultimately succeeds or raises. _record_success and
            # _record_failure no longer touch total_calls.
            self._metrics["total_calls"] += 1

            await self._inflight_incr()
            try:
                start = time.monotonic()
                response = await self._post_embed_with_retry(
                    client,
                    # BE-FT-PE-001: provider builds the request body shape.
                    self._provider.build_body(prefixed_text),
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
                        "provider": self.provider_name,
                        "trace_id": trace_id,
                    },
                )
            finally:
                await self._inflight_decr()

        data = response.json()
        # BE-FT-PE-001: provider knows where the vector lives in the JSON.
        embedding = np.array(self._provider.parse_vector(data), dtype=np.float32)

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
        # Add task prefix for better retrieval. The provider owns the
        # convention (nomic search_document: for ollama, empty for openai).
        prefixed_text = self._provider.apply_prefix(text, "document")
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
        # Query prefix for retrieval tasks — provider owns the convention
        # (nomic search_query: for ollama, empty for openai).
        prefixed_query = self._provider.apply_prefix(query, "query")
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
