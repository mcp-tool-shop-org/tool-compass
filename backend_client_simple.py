"""
Tool Compass - Simple Backend Client
Uses subprocess directly with JSON-RPC to avoid anyio conflicts.

This module provides a robust, Windows-compatible MCP client that:
- Uses ``asyncio.create_subprocess_exec`` directly (avoids anyio task group
  conflicts when nested inside another MCP server).
- Uses a split locking model: ``_write_lock`` serialises stdin writes only;
  responses are dispatched asynchronously by a dedicated ``_read_loop`` task
  so N concurrent calls to the same backend run in parallel.
- Bounds the in-flight request count per connection so unresponsive backends
  cannot blow up gateway memory (see ``MAX_INFLIGHT_REQUESTS_PER_BACKEND``).
- Distinguishes MCP ``isError`` (tool-level failure the LLM should reason
  about) from JSON-RPC errors (transport/protocol failures the operator must
  fix) in the response envelope via the ``error_kind`` field.
- Records Hystrix-style outcome taxonomy
  (success / tool_error / protocol_error / timeout / transport_error /
  backend_unavailable / shutdown_cancelled) so health signals are not
  corrupted by mixing legitimate tool errors with transport failures.
- Tears subprocesses down with a bounded post-kill wait so a zombie child
  can never wedge ``disconnect_all`` indefinitely.

Connection lifecycle (NOT keep-alive — see SimpleBackendManager for that):
- ``connect``: spawn subprocess, send initialize, send ``notifications/initialized``,
  fetch tools/list, mark connected.
- ``call_tool``: dispatches via ``_send_request`` under the bounded inflight
  semaphore.
- ``disconnect``: signal shutdown, fail in-flight futures, cancel reader
  tasks, terminate, wait (bounded), kill (bounded), feed EOF on the
  StreamReaders so the buffered chunk does not leak.
"""

import asyncio
import contextvars
import json
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Any, Literal, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime

from config import CompassConfig, StdioBackend, HttpBackend, load_config
from _version import __version__

# INT-01: the HTTP transport WRAPS the official MCP SDK's Streamable HTTP
# client. This is deliberate and differs from the STDIO path, which hand-rolls
# subprocess JSON-RPC to dodge the anyio task-group nesting hazard (a real
# problem only for stdio_client: subprocess spawn + Proactor pipe under a
# nested task group). HTTP has no subprocess and no Proactor pipe, so the SDK's
# anyio task group is safe to nest here — see backend_client_mcp.py for the
# reference AsyncExitStack + ClientSession pattern this mirrors. Imports are
# module-level (mcp is a hard dependency; see backend_client_mcp.py), and were
# VERIFIED against the installed mcp 1.28.0:
#   - streamablehttp_client  (mcp.client.streamable_http) — NOTE the exact
#     spelling: no underscores between "streamable" and "http" in the callable,
#     unlike the module name. Yields (read, write, get_session_id).
#   - create_mcp_http_client  (mcp.shared._httpx_utils, also re-exported from
#     mcp.client.streamable_http) — builds the underlying httpx.AsyncClient
#     with headers/timeout/auth; passed via the ``httpx_client_factory`` hook.
#   - StreamableHTTPError  (mcp.client.streamable_http) — SDK-level transport
#     wrapper error; grouped with httpx transport errors for OUTCOME_TRANSPORT.
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import (
    streamablehttp_client,
    create_mcp_http_client,
    StreamableHTTPError,
)
from mcp.shared.exceptions import McpError
from mcp.types import Implementation

logger = logging.getLogger(__name__)

# Timeout constants (in seconds)
CONNECTION_TIMEOUT = 10
TOOL_CALL_TIMEOUT = 15
KEEPALIVE_INTERVAL = 30  # F-414d48d4: ping / tools/list so idle sessions stay up
MAX_RETRIES = 2

# F-51e46b4c: per-backend circuit breaker (NOT the embedder breaker).
BREAKER_CLOSED = "closed"
BREAKER_OPEN = "open"
BREAKER_HALF_OPEN = "half_open"
BREAKER_FAILURE_THRESHOLD = 3  # consecutive transport/timeout
BREAKER_OPEN_SECONDS = 30.0
# Bound tools/list, resources/list, prompts/list pagination.
MAX_LIST_PAGES = 32
# Bound progress message / streamed content forwarded to the gateway.
PROGRESS_MESSAGE_LIMIT = 4096

# Stream bounds — guard the gateway against a malicious/buggy backend that
# writes a massive single line (would otherwise OOM the parent process).
STDOUT_LINE_LIMIT = 1024 * 1024  # 1 MiB per JSON-RPC line.

# BR-A-001: split the formerly-overloaded STDOUT_READ_TIMEOUT into two
# semantically distinct knobs so we don't conflate per-request deadlines with
# the read-loop idle tick.
STDOUT_READ_IDLE_TICK = 30.0  # Read-loop idle tick (used to notice shutdown).
PER_REQUEST_TIMEOUT = 30.0  # Per-pending-future deadline.
# Backwards-compat alias for callers that imported the old name.
STDOUT_READ_TIMEOUT = PER_REQUEST_TIMEOUT

# F-c0d80e5e: execute_tool publishes the resolved deadline here so
# _send_request / HttpBackendConnection.call_tool honour tool_timeouts
# above PER_REQUEST_TIMEOUT without changing the call_tool(name, args)
# positional contract.
_call_timeout: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "tool_compass_call_timeout", default=None
)


def _effective_request_timeout(explicit: Optional[float] = None) -> float:
    """Resolved per-request deadline.

    Precedence: explicit argument > execute_tool's inherited timeout >
    PER_REQUEST_TIMEOUT. Configured tool_timeouts of 60–120s must not be
    silently capped by the inner 30s wait_for.
    """
    if explicit is not None:
        return explicit
    inherited = _call_timeout.get()
    if inherited is not None:
        return inherited
    return PER_REQUEST_TIMEOUT

# BR-B-006: bound the in-flight queue per backend so a slow-loris backend
# cannot accumulate unbounded Future objects. Pick a value comfortably above
# realistic gateway concurrency (max ~16 tool calls in flight at once) but
# below anything that would matter for memory pressure.
MAX_INFLIGHT_REQUESTS_PER_BACKEND = 64

# BR-B-008: bound the post-kill wait so a zombie subprocess cannot wedge
# disconnect_all() forever. After this we abandon the process reference and
# let the OS reap it; we keep the PID in the abandoned set for the operator.
KILL_WAIT_TIMEOUT = 2.0

# BR-B-007: lightweight active health probe deadline.
HEALTH_PROBE_TIMEOUT = 2.0

# Outcome taxonomy — Hystrix-style event types used by ``ConnectionStats``.
# Treat as a closed enum even though we use Literal for cheap typing.
OUTCOME_SUCCESS = "success"
OUTCOME_TOOL_ERROR = "tool_error"
OUTCOME_PROTOCOL_ERROR = "protocol_error"
OUTCOME_TRANSPORT_ERROR = "transport_error"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_BACKEND_UNAVAILABLE = "backend_unavailable"
OUTCOME_SHUTDOWN_CANCELLED = "shutdown_cancelled"
_ALL_OUTCOMES = (
    OUTCOME_SUCCESS,
    OUTCOME_TOOL_ERROR,
    OUTCOME_PROTOCOL_ERROR,
    OUTCOME_TRANSPORT_ERROR,
    OUTCOME_TIMEOUT,
    OUTCOME_BACKEND_UNAVAILABLE,
    OUTCOME_SHUTDOWN_CANCELLED,
)

Outcome = Literal[
    "success",
    "tool_error",
    "protocol_error",
    "transport_error",
    "timeout",
    "backend_unavailable",
    "shutdown_cancelled",
]


class BackendShuttingDownError(RuntimeError):
    """Raised when a request is cancelled because the backend is shutting down.

    The message is deliberately user-actionable so it surfaces cleanly through
    any error envelope the gateway produces.
    """


class BackendNotConnectedError(RuntimeError):
    """Raised when a tool call is attempted on a backend that is not connected.

    BR-B-012: typed so the manager can convert it into a structured envelope
    with ``error_kind='backend_unavailable'`` rather than relying on
    string-substituting a raw RuntimeError.
    """

    def __init__(self, backend_name: str, reason: Optional[str] = None):
        self.backend_name = backend_name
        self.reason = reason or "connection not established"
        super().__init__(
            f"Not connected to backend: {backend_name} ({self.reason})"
        )


class BackendOverloadedError(RuntimeError):
    """Raised when the per-backend inflight cap rejects a new request.

    BR-B-006: surfaced when concurrent callers exceed
    ``MAX_INFLIGHT_REQUESTS_PER_BACKEND``. Distinct from a timeout — the
    caller fails fast rather than queuing and timing out.
    """

    def __init__(self, backend_name: str, cap: int):
        self.backend_name = backend_name
        self.cap = cap
        super().__init__(
            f"Backend {backend_name} overloaded: inflight cap {cap} reached"
        )


class BackendProtocolError(RuntimeError):
    """Raised when a backend returns a structured MCP/JSON-RPC error.

    Preserves the numeric ``code``, human ``message``, and any ``data`` payload
    from the original error so downstream logs / responses can surface the
    structured shape instead of flattening it into a bare RuntimeError string.

    BR-A-020 / BR-B-001: not just for ``initialize`` errors — also used for any
    structured JSON-RPC error path returned by ``tools/call`` so the gateway
    can emit ``error_kind='protocol_error'`` with the original ``code``.
    """

    def __init__(
        self,
        code: Optional[int],
        message: str,
        data: Optional[Any] = None,
    ):
        self.code = code
        self.message = message
        self.data = data
        # Keep str(self) useful for log messages that treat it as a plain exception
        if code is not None:
            super().__init__(f"[code={code}] {message}")
        else:
            super().__init__(message)


class ToolCallTimeoutError(asyncio.TimeoutError):
    """Timeout already recorded on ConnectionStats by call_tool.

    execute_tool catches this to return the timeout envelope without
    recording OUTCOME_TIMEOUT a second time (double-counting failed_calls).
    Still a TimeoutError subclass so direct call_tool callers keep working.
    """


def make_error_envelope(
    *,
    error_kind: Outcome,
    error: str,
    backend: Optional[str] = None,
    code: Optional[int] = None,
    data: Optional[Any] = None,
    retryable: Optional[bool] = None,
    content: Optional[List[Any]] = None,
    retry_after_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a structured error envelope.

    BR-B-001 / BR-B-012: the gateway and the LLM both consume this envelope.
    Fields are stable contract:

    - ``success``: always ``False`` for errors.
    - ``error_kind``: one of the outcome strings — lets the routing layer
      decide whether to remove the backend from rotation (transport / protocol
      / backend_unavailable) vs let the LLM retry with different arguments
      (tool_error / timeout).
    - ``error``: human-readable message.
    - ``backend``: backend name when known.
    - ``code``: JSON-RPC numeric code for protocol_error.
    - ``data``: structured JSON-RPC ``data`` payload, untruncated.
    - ``retryable``: hint to the caller. ``None`` means "no opinion".
    - ``content``: the original MCP content array for tool_error (preserves
      the structured shape the tool emitted, not concatenated to a string).
    """
    envelope: Dict[str, Any] = {
        "success": False,
        "error_kind": error_kind,
        "error": error,
    }
    if backend is not None:
        envelope["backend"] = backend
    if code is not None:
        envelope["code"] = code
    if data is not None:
        envelope["data"] = data
    if retryable is not None:
        envelope["retryable"] = retryable
    if content is not None:
        envelope["content"] = content
    if retry_after_seconds is not None:
        envelope["retry_after_seconds"] = float(retry_after_seconds)
    return envelope


def _bound_progress_message(message: Optional[str]) -> Optional[str]:
    """Cap progress text so a noisy backend cannot flood the MCP client."""
    if message is None:
        return None
    if not isinstance(message, str):
        message = str(message)
    encoded = message.encode("utf-8", errors="replace")
    if len(encoded) <= PROGRESS_MESSAGE_LIMIT:
        return message
    return encoded[:PROGRESS_MESSAGE_LIMIT].decode("utf-8", errors="replace") + "…"


def _bound_content_list(content: List[Any]) -> List[Any]:
    """Cap serialized content at STDOUT_LINE_LIMIT (F-6580241e)."""
    if not isinstance(content, list):
        return []
    total = 0
    out: List[Any] = []
    for item in content:
        try:
            encoded = json.dumps(item, default=str).encode("utf-8")
        except (TypeError, ValueError):
            encoded = str(item).encode("utf-8", errors="replace")
        if total + len(encoded) > STDOUT_LINE_LIMIT:
            out.append({
                "type": "text",
                "text": "[truncated: content exceeded STDOUT_LINE_LIMIT]",
            })
            break
        out.append(item)
        total += len(encoded)
    return out


async def _invoke_progress(
    callback: Optional[Any],
    progress: float,
    total: Optional[float] = None,
    message: Optional[str] = None,
) -> None:
    """Best-effort progress fan-out. Never raise into the call path."""
    if callback is None:
        return
    try:
        result = callback(progress, total, _bound_progress_message(message))
        if asyncio.iscoroutine(result):
            await result
    except Exception as e:
        logger.debug(f"progress callback failed: {e}")


@dataclass
class ToolInfo:
    """Normalized tool information from a backend."""
    name: str
    qualified_name: str
    description: str
    server: str
    input_schema: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "description": self.description,
            "server": self.server,
            "input_schema": self.input_schema,
        }


@dataclass
class ConnectionStats:
    """Track connection health metrics with Hystrix-style outcome taxonomy.

    BR-B-004: ``record_call`` accepts a distinct ``outcome`` per call so the
    operator and the routing layer can tell apart:

    - ``success`` — tool ran, returned success.
    - ``tool_error`` — tool ran, returned ``isError`` (legitimate in-band
      failure the LLM should reason about). Does *not* indicate the backend
      is unhealthy.
    - ``protocol_error`` — backend returned a JSON-RPC error (misbehaving
      backend, escalate).
    - ``transport_error`` — pipe broken / process died (backend dead).
    - ``timeout`` — the caller's deadline expired before a response arrived.
    - ``backend_unavailable`` — call rejected because backend is not yet
      connected, currently reconnecting, or overloaded (inflight cap hit).
    - ``shutdown_cancelled`` — request cancelled by operator-initiated
      disconnect; not a failure, not counted toward the backend-failure rate.

    The legacy ``success: bool`` keyword is still accepted for backward
    compatibility, and translates to ``success`` / ``tool_error`` (since the
    old API conflated those).
    """

    connected_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    total_calls: int = 0
    failed_calls: int = 0
    avg_latency_ms: float = 0.0
    outcomes: Dict[str, int] = field(default_factory=dict)
    inflight_count: int = 0
    inflight_peak: int = 0
    # F-51e46b4c: Hystrix-style breaker. Distinct from the embedder breaker.
    breaker_state: str = BREAKER_CLOSED
    consecutive_failures: int = 0
    breaker_opened_at: Optional[float] = None
    breaker_transitions: Dict[str, int] = field(default_factory=dict)

    def record_call(
        self,
        success: Optional[bool] = None,
        latency_ms: float = 0.0,
        *,
        outcome: Optional[Outcome] = None,
    ) -> None:
        """Record a single call outcome.

        Accepts either the legacy ``success: bool`` flag (which is still
        used by some tests) or the new ``outcome`` keyword. If both are
        supplied, ``outcome`` wins.

        Backward-compatibility note: under the legacy boolean call,
        ``success=False`` increments ``failed_calls`` (preserves the old
        semantics — caller had no way to distinguish tool_error from a real
        failure). Under the new ``outcome=`` API, only the Hystrix
        "backend really failed" outcomes count toward ``failed_calls``.
        """
        legacy_failed_call = False
        if outcome is None:
            if success is None:
                # Backward-compat: assume success when nothing specified.
                outcome = OUTCOME_SUCCESS
            else:
                if success:
                    outcome = OUTCOME_SUCCESS
                else:
                    # Legacy callers conflate tool_error and real failures.
                    # Preserve their failed_calls semantics, but bucket
                    # the outcome conservatively as tool_error so the
                    # NEW success_rate computation does not penalise the
                    # backend.
                    outcome = OUTCOME_TOOL_ERROR
                    legacy_failed_call = True
        if outcome not in _ALL_OUTCOMES:
            # Defensive: an unknown outcome string would silently dilute the
            # health signal. Coerce to a known bucket and log.
            logger.warning(
                f"ConnectionStats.record_call got unknown outcome={outcome!r}; "
                f"coercing to '{OUTCOME_TOOL_ERROR}'"
            )
            outcome = OUTCOME_TOOL_ERROR

        self.last_used = datetime.now()
        self.total_calls += 1

        # BR-B-004: ``failed_calls`` is the BACKEND-HEALTH counter and counts
        # only transport / protocol / backend-unavailable / timeout failures.
        # A tool legitimately returning isError is NOT a backend health
        # problem. Shutdown-cancelled is operator action, never a failure.
        # Exception: the legacy boolean-API call records failed_calls for
        # any ``success=False`` so existing callers/tests keep working.
        if outcome in (
            OUTCOME_PROTOCOL_ERROR,
            OUTCOME_TRANSPORT_ERROR,
            OUTCOME_TIMEOUT,
            OUTCOME_BACKEND_UNAVAILABLE,
        ) or legacy_failed_call:
            self.failed_calls += 1

        self.outcomes[outcome] = self.outcomes.get(outcome, 0) + 1

        # Running average across all calls (including tool_error — latency
        # is independent of which side blamed which).
        if self.total_calls > 0:
            self.avg_latency_ms = (
                self.avg_latency_ms * (self.total_calls - 1) + latency_ms
            ) / self.total_calls

        # Breaker is driven only by transport/timeout (not tool_error).
        if outcome in (OUTCOME_TRANSPORT_ERROR, OUTCOME_TIMEOUT):
            self.consecutive_failures += 1
            if self.breaker_state == BREAKER_HALF_OPEN:
                self._set_breaker(BREAKER_OPEN)
            elif (
                self.breaker_state == BREAKER_CLOSED
                and self.consecutive_failures >= BREAKER_FAILURE_THRESHOLD
            ):
                self._set_breaker(BREAKER_OPEN)
        elif outcome in (OUTCOME_SUCCESS, OUTCOME_TOOL_ERROR):
            self.consecutive_failures = 0
            if self.breaker_state in (BREAKER_OPEN, BREAKER_HALF_OPEN):
                self._set_breaker(BREAKER_CLOSED)

    def _set_breaker(self, new_state: str) -> None:
        old = self.breaker_state
        if old == new_state:
            return
        self.breaker_state = new_state
        key = f"{old}->{new_state}"
        self.breaker_transitions[key] = self.breaker_transitions.get(key, 0) + 1
        if new_state == BREAKER_OPEN:
            self.breaker_opened_at = time.time()
        elif new_state == BREAKER_CLOSED:
            self.breaker_opened_at = None
            self.consecutive_failures = 0
        logger.warning(
            f"backend breaker {old} -> {new_state} "
            f"(consecutive_failures={self.consecutive_failures})"
        )

    def breaker_retry_after(self) -> Optional[float]:
        """Seconds until a half-open probe is allowed; None if not OPEN."""
        if self.breaker_state != BREAKER_OPEN:
            return None
        opened = self.breaker_opened_at
        if opened is None:
            return BREAKER_OPEN_SECONDS
        remaining = BREAKER_OPEN_SECONDS - (time.time() - opened)
        return max(0.0, remaining)

    def breaker_can_attempt(self) -> bool:
        """True if connect/execute may proceed (closed, half-open, or OPEN expired)."""
        if self.breaker_state in (BREAKER_CLOSED, BREAKER_HALF_OPEN):
            return True
        if self.breaker_state == BREAKER_OPEN:
            retry = self.breaker_retry_after()
            if retry is not None and retry <= 0:
                self._set_breaker(BREAKER_HALF_OPEN)
                return True
            return False
        return True


class SimpleBackendConnection:
    """Per-backend JSON-RPC connection over an MCP server subprocess.

    BR-B-015: this docstring describes what the connection actually does.
    Reconnection and keep-alive belong to :class:`SimpleBackendManager`;
    don't expect them here.

    The connection:

    - Manages one subprocess (spawn / write / read / terminate).
    - Serialises stdin writes via ``_write_lock`` so JSON-RPC frames cannot
      interleave on the wire.
    - Dispatches responses through a dedicated ``_read_loop`` task that
      resolves per-request futures, so N concurrent calls to the same
      backend run in parallel.
    - Bounds inflight requests via ``_inflight_sem`` so a slow backend
      cannot OOM the gateway.
    - Tears down cleanly: signal shutdown, fail futures, cancel reader
      tasks, terminate, bounded wait, kill, bounded post-kill wait, drain
      stream buffers.
    """

    def __init__(self, name: str, backend: StdioBackend):
        self.name = name
        self.backend = backend
        self._process: Optional[asyncio.subprocess.Process] = None
        self._tools: List[Dict[str, Any]] = []
        self._connected = False
        self._request_id = 0
        # BR-B-005: locks and the semaphore are constructed lazily inside a
        # coroutine via _ensure_async_primitives() so they bind to the
        # running event loop at first use. Constructing them in __init__
        # ran the risk of binding to whatever loop happens to be installed
        # at instantiation time, which breaks if the same connection is
        # reused across asyncio.run() boundaries (test runners, embedded
        # gateway). Keep the type-hints visible here for IDEs.
        self._write_lock: Optional[asyncio.Lock] = None
        # _lock is a backwards-compat alias for the write lock; older code
        # and tests may grab it. Allocated together with _write_lock.
        self._lock: Optional[asyncio.Lock] = None
        # BR-B-006: bound the inflight request queue so the _pending dict
        # cannot grow unbounded during a slow-loris stall.
        self._inflight_sem: Optional[asyncio.Semaphore] = None
        self._pending: Dict[int, "asyncio.Future[Dict[str, Any]]"] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._stats = ConnectionStats()
        self._stderr_task: Optional[asyncio.Task] = None
        # Flipped by disconnect() so any in-flight _send_request can
        # distinguish a shutdown from a genuine backend crash.
        self._shutting_down: bool = False
        # BR-B-008: track PIDs we had to abandon after the post-kill wait
        # exceeded KILL_WAIT_TIMEOUT, so the operator can see them in stats.
        self._abandoned_pids: List[int] = []
        # F-414d48d4 / F-6580241e: notifications + keepalive + progress.
        self._progress_callbacks: Dict[Any, Any] = {}
        self._keepalive_task: Optional[asyncio.Task] = None
        self._last_notification_at: Optional[datetime] = None
        self._on_catalog_changed: Optional[Callable[[str], Any]] = None
        self._resources: List[Dict[str, Any]] = []
        self._prompts: List[Dict[str, Any]] = []

    def _ensure_async_primitives(self) -> None:
        """Lazily construct loop-bound asyncio primitives.

        BR-B-005: must be called from inside a running coroutine. This is
        guaranteed by every public async entry point (connect, _send_request,
        _send_notification, call_tool, disconnect).
        """
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
            self._lock = self._write_lock
        if self._inflight_sem is None:
            self._inflight_sem = asyncio.Semaphore(
                MAX_INFLIGHT_REQUESTS_PER_BACKEND
            )

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _fail_all_pending(self, exc: BaseException) -> None:
        """Resolve every in-flight request future with *exc*.

        Called on EOF, read-loop crash, or shutdown. Safe to call repeatedly:
        futures that are already done are skipped.
        """
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    async def _read_loop(self) -> None:
        """Read JSON-RPC responses from stdout and dispatch to _pending futures.

        One task per connection. Runs until EOF, a read error, or the task
        is cancelled during disconnect(). Malformed lines are logged at
        WARNING and skipped (the writer-side timeout will still surface a
        stuck request).
        """
        assert self._process is not None and self._process.stdout is not None
        stdout = self._process.stdout
        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        stdout.readline(),
                        timeout=STDOUT_READ_IDLE_TICK,
                    )
                except asyncio.TimeoutError:
                    # Idle read timeout — keep looping. Per-request deadlines
                    # are enforced by the writer with asyncio.wait_for(fut).
                    if self._shutting_down:
                        break
                    continue
                except (ValueError, asyncio.LimitOverrunError) as e:
                    # StreamReader.readline() raises a plain ValueError on
                    # limit overrun ("Separator is found, but chunk is longer
                    # than limit") — LimitOverrunError is NOT a subclass of
                    # ValueError, so catching only the latter left this branch
                    # dead and let oversize lines fall through to the generic
                    # handler that kills the reader. Catch both: the
                    # drain-and-abort recovery is the safe response to either.
                    logger.error(
                        f"Backend {self.name} emitted a line exceeding "
                        f"{STDOUT_LINE_LIMIT} bytes: {e}"
                    )
                    self._fail_all_pending(
                        RuntimeError(
                            f"Backend {self.name} emitted an oversize line "
                            f"(>{STDOUT_LINE_LIMIT} bytes)"
                        )
                    )
                    break
                except (BrokenPipeError, ConnectionResetError) as e:
                    logger.debug(f"Read loop transport closed for {self.name}: {e}")
                    break

                if not line:
                    # EOF — backend closed stdout.
                    logger.debug(f"Backend {self.name} stdout EOF")
                    break

                try:
                    msg = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    preview = line[:120].decode("utf-8", errors="replace").rstrip()
                    logger.warning(
                        f"Backend {self.name} emitted non-JSON line: {preview!r}"
                    )
                    continue

                msg_id = msg.get("id") if isinstance(msg, dict) else None
                if msg_id is None:
                    # F-414d48d4 / F-6580241e: notifications have no id.
                    # Route tools/list_changed, progress, etc. instead of
                    # dropping them on the floor.
                    if isinstance(msg, dict):
                        self._handle_notification(msg)
                    else:
                        logger.debug(
                            f"Backend {self.name} sent id-less non-object message"
                        )
                    continue

                fut = self._pending.pop(msg_id, None)
                if fut is None:
                    logger.debug(
                        f"Backend {self.name} response for unknown id={msg_id}"
                    )
                    continue
                if not fut.done():
                    fut.set_result(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # defensive
            logger.error(f"Read loop for {self.name} crashed: {e}")
            self._fail_all_pending(
                RuntimeError(f"Backend {self.name} read loop crashed: {e}")
            )
            return
        finally:
            # Whatever exit path we take, no future should stay pending.
            if self._shutting_down:
                self._fail_all_pending(
                    BackendShuttingDownError(
                        f"Backend {self.name} is shutting down — request cancelled"
                    )
                )
            else:
                self._fail_all_pending(
                    BackendShuttingDownError(
                        f"Backend {self.name} connection lost — request cancelled"
                    )
                )

    async def connect(self, timeout: Optional[float] = None) -> bool:
        """Establish connection to the backend server."""
        # BR-B-005: bind locks / semaphore to the running loop before any
        # path uses them.
        self._ensure_async_primitives()

        if self._connected and self._process and self._process.returncode is None:
            return True

        # disconnect() flips this; a new spawn (including MAX_RETRIES on the
        # same object) must be able to send initialize.
        self._shutting_down = False

        timeout = timeout or CONNECTION_TIMEOUT

        try:
            logger.info(f"Connecting to backend: {self.name} (timeout={timeout}s)")

            # BR-A-006: env inheritance policy. The default is to inherit the
            # parent's environment (current behaviour, preserved). A backend
            # config may opt into ``env_inheritance='none'`` via its ``env``
            # dict's reserved ``__env_inheritance__`` key to start with an
            # empty environment instead — useful when shipping a backend that
            # must NOT see the gateway's secrets (e.g. a sandboxed transformer
            # written by a third party). The key is consumed and never passed
            # to the subprocess. This is a forward-compat surface; the
            # canonical place to declare it lives in the config schema (see
            # cross-domain note in skipped[]).
            backend_env = dict(self.backend.env) if self.backend.env else {}
            inheritance_policy = backend_env.pop(
                "__env_inheritance__", "all"
            )
            if inheritance_policy == "none":
                env: Dict[str, str] = {}
            else:
                env = os.environ.copy()
            env.update(backend_env)
            env.update({
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
            })

            # Windows-specific: use CREATE_NO_WINDOW to prevent console popups
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            # Start subprocess (limit caps StreamReader buffer to prevent OOM)
            self._process = await asyncio.create_subprocess_exec(
                self.backend.command,
                *self.backend.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.backend.cwd,
                creationflags=creationflags,
                limit=STDOUT_LINE_LIMIT,
            )

            # Start stderr reader task (logs backend errors)
            self._stderr_task = asyncio.create_task(self._read_stderr())

            # GW-FT-001: start the dedicated stdout reader BEFORE sending
            # initialize, so its response can be dispatched to our future.
            self._read_task = asyncio.create_task(self._read_loop())

            # BR-B-010: distinguish "process never started" from "process is
            # alive but unresponsive" by giving the subprocess up to 200ms to
            # either die outright (wrong command, missing dependency) or stay
            # alive. We do NOT wait for the first stdout byte here because
            # well-behaved MCP servers stay silent until initialize.
            await asyncio.sleep(0.2)
            if self._process.returncode is not None:
                logger.error(
                    f"Backend {self.name} subprocess exited immediately with "
                    f"code {self._process.returncode} before initialize "
                    f"(check command/args/cwd)"
                )
                await self.disconnect()
                return False

            # Initialize MCP session with timeout
            init_result = await asyncio.wait_for(
                self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "tool-compass", "version": __version__}
                }, timeout=timeout),
                timeout=timeout
            )

            if "error" in init_result:
                # GW-B-006: preserve the structured MCP error shape
                err = init_result["error"]
                if isinstance(err, dict):
                    code = err.get("code")
                    message = err.get("message") or str(err)
                    data = err.get("data")
                    logger.error(
                        f"Backend {self.name} initialize failed: "
                        f"code={code} message={message}"
                    )
                    raise BackendProtocolError(code, message, data)
                # Fallback: non-dict error payload
                logger.error(f"Backend {self.name} initialize failed: {err}")
                raise BackendProtocolError(None, f"Initialize failed: {err}")

            # Send initialized notification
            await self._send_notification("notifications/initialized")

            # Get tools list (follow nextCursor so list_changed + first
            # connect see the full catalog — F-414d48d4).
            self._tools = await asyncio.wait_for(
                self._list_paginated("tools/list", "tools", timeout=timeout),
                timeout=timeout,
            )

            self._connected = True
            self._stats.connected_at = datetime.now()
            self._stats.last_used = datetime.now()
            logger.info(f"Connected to {self.name}: {len(self._tools)} tools available")
            return True

        except asyncio.TimeoutError:
            logger.error(f"Connection to {self.name} timed out after {timeout}s")
            await self.disconnect()
            return False
        except Exception as e:
            logger.error(f"Failed to connect to {self.name}: {e}")
            await self.disconnect()
            return False
        except BaseException:
            # CancelledError is a BaseException on 3.9+; an MCP-request cancel
            # or outer wait_for during the pre-initialize sleep / initialize /
            # list_tools must still reap the child and reader tasks.
            try:
                await self.disconnect()
            except Exception:
                logger.debug(
                    f"Disconnect after cancelled connect to {self.name} failed"
                )
            raise

    async def disconnect(self):
        """Close the connection gracefully.

        Sequence:

        1. Set ``_shutting_down`` and ``_connected = False`` so any in-flight
           callers wake with :class:`BackendShuttingDownError`.
        2. Fail all pending futures.
        3. Acquire the write lock (5s budget) to give any in-flight write a
           chance to finish.
        4. Cancel stderr / stdout reader tasks.
        5. Close stdin, terminate, bounded wait, kill, bounded post-kill
           wait. BR-B-008: the post-kill wait is bounded by KILL_WAIT_TIMEOUT
           so a zombie cannot wedge us forever.
        6. Feed EOF on the StreamReaders (BR-B-003) so the buffered chunk
           does not leak the underlying pipe.
        7. On Windows, close the subprocess transport so ProactorEventLoop
           releases its pipe handle.
        """
        self._ensure_async_primitives()
        assert self._write_lock is not None

        # Signal in-flight requests BEFORE we start tearing anything down.
        self._shutting_down = True
        self._connected = False
        await self._stop_keepalive()

        # Fail any pending futures immediately so callers stuck in
        # asyncio.wait_for(fut) wake with BackendShuttingDownError rather
        # than hitting their own tool timeout.
        self._fail_all_pending(
            BackendShuttingDownError(
                f"Backend {self.name} is shutting down — request cancelled"
            )
        )

        # Best-effort: wait for any in-flight writer to release the write lock.
        lock_acquired = False
        try:
            await asyncio.wait_for(self._write_lock.acquire(), timeout=5.0)
            lock_acquired = True
        except asyncio.TimeoutError:
            logger.warning(
                f"Disconnect of {self.name}: write lock held after 5s — "
                "terminating anyway; in-flight request will surface as "
                "BackendShuttingDownError"
            )

        try:
            # Cancel stderr reader
            if self._stderr_task:
                self._stderr_task.cancel()
                try:
                    await self._stderr_task
                except asyncio.CancelledError:
                    pass
                self._stderr_task = None

            # Cancel stdout reader
            if self._read_task:
                self._read_task.cancel()
                try:
                    await self._read_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug(f"Read task cleanup for {self.name}: {e}")
                self._read_task = None

            # Terminate process
            if self._process:
                proc = self._process
                pid = proc.pid
                try:
                    # Try graceful shutdown first
                    if proc.stdin:
                        try:
                            proc.stdin.close()
                            # ``wait_closed`` is async on StreamWriter; let
                            # the OS drain any buffered bytes. Tolerate
                            # errors — the process may already be gone.
                            try:
                                await asyncio.wait_for(
                                    proc.stdin.wait_closed(), timeout=0.5
                                )
                            except (
                                asyncio.TimeoutError,
                                BrokenPipeError,
                                ConnectionResetError,
                                AttributeError,
                            ):
                                pass
                        except Exception as e:
                            logger.debug(
                                f"stdin close for {self.name} failed: {e}"
                            )
                    try:
                        proc.terminate()
                    except (ProcessLookupError, OSError) as e:
                        logger.debug(
                            f"terminate() for {self.name} pid={pid}: {e}"
                        )
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except (ProcessLookupError, OSError) as e:
                            logger.debug(
                                f"kill() for {self.name} pid={pid}: {e}"
                            )
                        try:
                            # BR-B-008: bound the post-kill wait so a zombie
                            # cannot wedge disconnect_all forever.
                            await asyncio.wait_for(
                                proc.wait(), timeout=KILL_WAIT_TIMEOUT
                            )
                        except asyncio.TimeoutError:
                            logger.error(
                                f"Backend {self.name} pid={pid} did not "
                                f"reap within {KILL_WAIT_TIMEOUT}s after "
                                "kill; abandoning. OS will eventually reap."
                            )
                            self._abandoned_pids.append(pid)
                except Exception as e:
                    logger.debug(f"Error during disconnect of {self.name}: {e}")

                # BR-B-003: explicitly close the subprocess transport so
                # ProactorEventLoop releases its pipe handle. The transport
                # is reachable via the private ``_transport`` attribute on
                # the Process object on CPython 3.10+. Defensive try/except
                # — this is best-effort cleanup.
                try:
                    transport = getattr(proc, "_transport", None)
                    if transport is not None:
                        transport.close()
                except Exception as e:
                    logger.debug(
                        f"Transport close for {self.name}: {e}"
                    )

                # BR-B-003: feed EOF on the StreamReaders so any buffered
                # chunk inside the reader does not pin the underlying pipe.
                # ``feed_eof`` is the documented way to do this on a
                # StreamReader bound to a subprocess pipe.
                for stream in (proc.stdout, proc.stderr):
                    try:
                        if stream is not None:
                            stream.feed_eof()
                    except Exception as e:
                        logger.debug(
                            f"feed_eof on {self.name}: {e}"
                        )

                self._process = None

            self._tools = []
        finally:
            if lock_acquired:
                self._write_lock.release()

    async def _read_stderr(self):
        """Read and log stderr from the backend process.

        BR-A-002: tolerate oversize lines by draining as raw bytes and
        truncating rather than raising; otherwise the stderr reader dies
        silently and the backend's diagnostic stream disappears.
        """
        if not self._process or not self._process.stderr:
            return
        stderr = self._process.stderr
        try:
            while True:
                try:
                    line = await stderr.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    # StreamReader.readline() raises a plain ValueError on
                    # limit overrun (LimitOverrunError is NOT a ValueError
                    # subclass), so catching only the latter left this drain
                    # branch dead. Catch both: draining and continuing is the
                    # safe recovery for either.
                    # Drain consumed bytes up to the configured limit and log
                    # the head with a truncation marker.
                    try:
                        drained = await stderr.read(STDOUT_LINE_LIMIT)
                    except Exception:
                        drained = b""
                    if drained:
                        head = drained[:512].decode("utf-8", errors="replace").rstrip()
                        logger.warning(
                            f"[{self.name}] stderr line truncated "
                            f"(>{STDOUT_LINE_LIMIT} bytes): {head!r}..."
                        )
                    continue
                except (BrokenPipeError, ConnectionResetError):
                    break
                if not line:
                    break
                # Log backend stderr at debug level
                logger.debug(
                    f"[{self.name}] "
                    f"{line.decode('utf-8', errors='replace').rstrip()}"
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Stderr reader error for {self.name}: {e}")

    def _handle_notification(self, msg: Dict[str, Any]) -> None:
        """Dispatch JSON-RPC notifications (method, no id).

        F-414d48d4: ``notifications/tools/list_changed`` refreshes the
        cached catalog. F-6580241e: ``notifications/progress`` fans out to
        the in-flight request's progress callback.
        """
        method = msg.get("method") or ""
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        self._last_notification_at = datetime.now()

        if method in (
            "notifications/progress",
            "notifications/cancelled",
        ) or method.endswith("/progress"):
            token = params.get("progressToken")
            callback = self._progress_callbacks.get(token)
            if callback is None and token is not None:
                # Some servers echo the request id as a string.
                callback = self._progress_callbacks.get(str(token))
                if callback is None:
                    try:
                        callback = self._progress_callbacks.get(int(token))
                    except (TypeError, ValueError):
                        callback = None
            if callback is not None:
                progress = params.get("progress", 0)
                total = params.get("total")
                message = params.get("message")
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        _invoke_progress(callback, float(progress), total, message)
                    )
                except Exception as e:
                    logger.debug(f"progress dispatch for {self.name} failed: {e}")
            return

        if method in (
            "notifications/tools/list_changed",
            "notifications/prompts/list_changed",
            "notifications/resources/list_changed",
        ):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._refresh_catalog(method))
            except Exception as e:
                logger.debug(f"catalog refresh schedule for {self.name} failed: {e}")
            return

        logger.debug(
            f"Backend {self.name} sent id-less message (method={method})"
        )

    async def _refresh_catalog(self, notification_method: str) -> None:
        """Re-list tools/prompts/resources after a list_changed notification."""
        if self._shutting_down or not self._connected:
            return
        try:
            if notification_method.endswith("tools/list_changed"):
                self._tools = await self._list_paginated("tools/list", "tools")
            elif notification_method.endswith("prompts/list_changed"):
                self._prompts = await self._list_paginated("prompts/list", "prompts")
            elif notification_method.endswith("resources/list_changed"):
                self._resources = await self._list_paginated(
                    "resources/list", "resources"
                )
            cb = self._on_catalog_changed
            if cb is not None:
                maybe = cb(self.name)
                if asyncio.iscoroutine(maybe):
                    await maybe
        except Exception as e:
            logger.warning(
                f"Backend {self.name} catalog refresh after {notification_method} "
                f"failed: {e}"
            )

    async def _list_paginated(
        self,
        method: str,
        result_key: str,
        timeout: Optional[float] = None,
    ) -> List[Any]:
        """Follow nextCursor for tools/list, resources/list, prompts/list."""
        items: List[Any] = []
        cursor: Optional[str] = None
        for _ in range(MAX_LIST_PAGES):
            params: Dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            resp = await self._send_request(method, params, timeout=timeout)
            if "error" in resp:
                logger.warning(
                    f"Backend {self.name} {method} error: {resp.get('error')}"
                )
                break
            result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
            chunk = result.get(result_key) or []
            if isinstance(chunk, list):
                items.extend(chunk)
            cursor = result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        return items

    async def _keepalive_loop(self) -> None:
        """F-414d48d4: ping (fallback tools/list) on KEEPALIVE_INTERVAL."""
        try:
            while not self._shutting_down and self._connected:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._shutting_down or not self._connected:
                    break
                try:
                    await self._send_request(
                        "ping", {}, timeout=HEALTH_PROBE_TIMEOUT
                    )
                except Exception:
                    try:
                        await self._send_request(
                            "tools/list", {}, timeout=HEALTH_PROBE_TIMEOUT
                        )
                    except Exception as e:
                        logger.warning(
                            f"Keepalive failed for {self.name}: {e}"
                        )
                        self._connected = False
                        break
        except asyncio.CancelledError:
            raise

    def _start_keepalive(self) -> None:
        if self._keepalive_task is not None and not self._keepalive_task.done():
            return
        try:
            self._keepalive_task = asyncio.get_running_loop().create_task(
                self._keepalive_loop()
            )
        except Exception as e:
            logger.debug(f"keepalive start for {self.name} failed: {e}")

    async def _stop_keepalive(self) -> None:
        task = self._keepalive_task
        self._keepalive_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"keepalive stop for {self.name}: {e}")

    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any],
        timeout: Optional[float] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for its response.

        Concurrency model:

        - The inflight semaphore caps simultaneous requests to
          ``MAX_INFLIGHT_REQUESTS_PER_BACKEND``. Acquired with no wait — if
          the cap is reached, fail fast with :class:`BackendOverloadedError`
          (BR-B-006).
        - Only the write side serialises on ``_write_lock``; the response
          arrives asynchronously via the read loop, so N concurrent calls to
          the same backend run in parallel on the read side.
        - ``_shutting_down`` is re-checked at every boundary.
        - ``timeout`` is the pending-future deadline (explicit arg, else the
          execute_tool-inherited value, else PER_REQUEST_TIMEOUT).
        """
        self._ensure_async_primitives()
        assert self._inflight_sem is not None and self._write_lock is not None

        if self._shutting_down:
            raise BackendShuttingDownError(
                f"Backend {self.name} is shutting down — request cancelled"
            )
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise BackendNotConnectedError(self.name, "process pipes missing")
        if self._process.returncode is not None:
            raise BackendNotConnectedError(
                self.name,
                f"process exited with code {self._process.returncode}",
            )

        # BR-B-006: fail fast when over the inflight cap rather than queuing.
        # ``Semaphore`` doesn't have a non-blocking acquire so we look at the
        # internal counter; this is fine because we hold the GIL/event loop
        # at this moment (no other coroutine can change it without yielding
        # first, and we haven't yielded since the check).
        if self._inflight_sem.locked():
            raise BackendOverloadedError(
                self.name, MAX_INFLIGHT_REQUESTS_PER_BACKEND
            )

        await self._inflight_sem.acquire()
        self._stats.inflight_count += 1
        if self._stats.inflight_count > self._stats.inflight_peak:
            self._stats.inflight_peak = self._stats.inflight_count

        request_id: Optional[int] = None
        loop = asyncio.get_running_loop()
        fut: "asyncio.Future[Dict[str, Any]]" = loop.create_future()

        try:
            async with self._write_lock:
                # Re-check shutdown after acquiring the write lock —
                # disconnect() may have run while we were queued.
                if self._shutting_down:
                    raise BackendShuttingDownError(
                        f"Backend {self.name} is shutting down — "
                        "request cancelled"
                    )

                request_id = self._next_id()
                self._pending[request_id] = fut
                send_params = params
                if progress_callback is not None:
                    send_params = dict(params)
                    meta = dict(send_params.get("_meta") or {})
                    meta["progressToken"] = request_id
                    send_params["_meta"] = meta
                    self._progress_callbacks[request_id] = progress_callback
                    self._progress_callbacks[str(request_id)] = progress_callback
                request = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": send_params,
                }
                request_str = json.dumps(request) + "\n"
                try:
                    self._process.stdin.write(request_str.encode("utf-8"))
                    await self._process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError) as e:
                    # Pull our future back off the pending map before
                    # surfacing.
                    self._pending.pop(request_id, None)
                    if self._shutting_down:
                        raise BackendShuttingDownError(
                            f"Backend {self.name} is shutting down — "
                            "request cancelled"
                        ) from e
                    raise

            # Now wait for the read loop to resolve our future. We don't
            # hold the write lock here, so other callers can send their own
            # requests in parallel. Honour the resolved deadline so a
            # tool_timeouts entry of 60s is not silently capped at 30s.
            deadline = _effective_request_timeout(timeout)
            try:
                return await asyncio.wait_for(fut, timeout=deadline)
            except asyncio.TimeoutError:
                if self._shutting_down:
                    raise BackendShuttingDownError(
                        f"Backend {self.name} is shutting down — "
                        "request cancelled"
                    )
                raise asyncio.TimeoutError(
                    f"Backend {self.name} did not respond within "
                    f"{deadline}s"
                )
        finally:
            # Whether we succeeded or timed out, don't leak an entry.
            if request_id is not None:
                self._pending.pop(request_id, None)
                self._progress_callbacks.pop(request_id, None)
                self._progress_callbacks.pop(str(request_id), None)
            self._stats.inflight_count = max(0, self._stats.inflight_count - 1)
            self._inflight_sem.release()

    async def _send_notification(self, method: str, params: Optional[Dict[str, Any]] = None):
        """Send a JSON-RPC notification (no response expected).

        BR-A-003: re-checks ``_shutting_down`` inside the write lock so a
        concurrent disconnect doesn't write to a half-torn-down pipe.
        Symmetric with ``_send_request``.
        """
        self._ensure_async_primitives()
        assert self._write_lock is not None

        if self._shutting_down:
            raise BackendShuttingDownError(
                f"Backend {self.name} is shutting down — notification cancelled"
            )

        async with self._write_lock:
            # Re-check inside the lock for the same reason _send_request does.
            if self._shutting_down:
                raise BackendShuttingDownError(
                    f"Backend {self.name} is shutting down — "
                    "notification cancelled"
                )
            if not self._process or not self._process.stdin:
                raise BackendNotConnectedError(
                    self.name, "process pipes missing"
                )

            notification: Dict[str, Any] = {
                "jsonrpc": "2.0",
                "method": method,
            }
            if params:
                notification["params"] = params

            notification_str = json.dumps(notification) + "\n"
            try:
                self._process.stdin.write(notification_str.encode("utf-8"))
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as e:
                if self._shutting_down:
                    raise BackendShuttingDownError(
                        f"Backend {self.name} is shutting down — "
                        "notification cancelled"
                    ) from e
                raise

    def get_tools(self) -> List[ToolInfo]:
        """Get normalized tool info list."""
        tools = []
        for tool in self._tools:
            tools.append(ToolInfo(
                name=tool.get("name", ""),
                qualified_name=f"{self.name}:{tool.get('name', '')}",
                description=tool.get("description", ""),
                server=self.name,
                input_schema=tool.get("inputSchema", {}),
            ))
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Call a tool on this backend.

        Returns a structured envelope (BR-B-001 / BR-B-012):

        - Success: ``{success: True, result: str, content: [...]}``
        - JSON-RPC error: ``{success: False, error_kind: 'protocol_error',
          code, error, data, backend, retryable}``
        - Tool error (MCP ``isError``): ``{success: False,
          error_kind: 'tool_error', error, content, backend,
          retryable: True}`` — content preserved.
        - Precondition failure: ``BackendNotConnectedError`` raised so the
          manager layer can emit ``backend_unavailable`` and decide whether
          to reconnect.

        BR-A-004: ``BackendShuttingDownError`` is re-raised explicitly so the
        broad ``Exception`` handler cannot eat it and stats record a
        ``shutdown_cancelled`` outcome (not a real failure).
        """
        self._ensure_async_primitives()
        if not self._connected:
            raise BackendNotConnectedError(self.name)

        start_time = asyncio.get_event_loop().time()

        try:
            result = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            }, timeout=timeout, progress_callback=progress_callback)

            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            if "error" in result:
                # JSON-RPC error — backend reported a structured protocol
                # error. Treat as protocol_error so the routing layer can
                # escalate.
                err = result["error"]
                if isinstance(err, dict):
                    code = err.get("code")
                    message = err.get("message") or str(err)
                    data = err.get("data")
                else:
                    code = None
                    message = str(err)
                    data = None
                self._stats.record_call(
                    latency_ms=latency_ms, outcome=OUTCOME_PROTOCOL_ERROR
                )
                return make_error_envelope(
                    error_kind=OUTCOME_PROTOCOL_ERROR,
                    error=message,
                    backend=self.name,
                    code=code,
                    data=data,
                    retryable=False,
                )

            if "result" in result:
                res = result["result"]
                content_list = res.get("content", [])
                if res.get("isError"):
                    # MCP-level tool error: the LLM should reason about this.
                    # Preserve the structured content array; do NOT count as
                    # a backend failure (BR-B-004).
                    error_text_parts: List[str] = []
                    if isinstance(content_list, list):
                        for item in content_list:
                            if isinstance(item, dict) and "text" in item:
                                error_text_parts.append(item["text"])
                    error_text = "".join(error_text_parts) or "Tool returned error"
                    self._stats.record_call(
                        latency_ms=latency_ms, outcome=OUTCOME_TOOL_ERROR
                    )
                    return make_error_envelope(
                        error_kind=OUTCOME_TOOL_ERROR,
                        error=error_text,
                        backend=self.name,
                        retryable=True,
                        content=content_list,
                    )

                # Extract text content
                text_parts: List[str] = []
                if isinstance(content_list, list):
                    for item in content_list:
                        if isinstance(item, dict) and "text" in item:
                            text_parts.append(item["text"])
                        elif isinstance(item, str):
                            text_parts.append(item)
                        else:
                            text_parts.append(str(item))

                self._stats.record_call(
                    latency_ms=latency_ms, outcome=OUTCOME_SUCCESS
                )
                bounded = _bound_content_list(
                    content_list if isinstance(content_list, list) else []
                )
                return {
                    "success": True,
                    "result": "\n".join(text_parts) if text_parts else "Tool executed successfully",
                    "content": bounded,
                }

            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_PROTOCOL_ERROR
            )
            return make_error_envelope(
                error_kind=OUTCOME_PROTOCOL_ERROR,
                error="Invalid response from backend (no result and no error)",
                backend=self.name,
                retryable=False,
            )

        except BackendShuttingDownError:
            # BR-A-004: don't let the broad except below eat this. Record as
            # shutdown_cancelled so the success_rate gauge is not corrupted.
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_SHUTDOWN_CANCELLED
            )
            raise
        except BackendOverloadedError:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_BACKEND_UNAVAILABLE
            )
            raise
        except BackendNotConnectedError:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_BACKEND_UNAVAILABLE
            )
            # Check if process died
            if self._process and self._process.returncode is not None:
                self._connected = False
            raise
        except asyncio.TimeoutError as e:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_TIMEOUT
            )
            # Distinct type so execute_tool does not record OUTCOME_TIMEOUT
            # a second time. Still a TimeoutError for direct callers.
            raise ToolCallTimeoutError(
                f"Backend {self.name} tool call timed out"
            ) from e
        except (BrokenPipeError, ConnectionResetError):
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_TRANSPORT_ERROR
            )
            if self._process and self._process.returncode is not None:
                self._connected = False
                logger.warning(
                    f"Backend {self.name} process died, will reconnect "
                    "on next call"
                )
            raise
        except Exception:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            # Default to transport_error for genuinely-unknown failures
            # — these are typically pipe / runtime issues, not tool failures.
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_TRANSPORT_ERROR
            )
            if self._process and self._process.returncode is not None:
                self._connected = False
                logger.warning(
                    f"Backend {self.name} process died, will reconnect "
                    "on next call"
                )
            raise

    async def list_resources(self) -> List[Dict[str, Any]]:
        """Live-backend resources/list (F-e126a298). Follows nextCursor."""
        if not self._connected:
            raise BackendNotConnectedError(self.name)
        self._resources = await self._list_paginated("resources/list", "resources")
        return list(self._resources)

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Live-backend resources/read (F-e126a298)."""
        if not self._connected:
            raise BackendNotConnectedError(self.name)
        resp = await self._send_request("resources/read", {"uri": uri})
        if "error" in resp:
            err = resp["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            return make_error_envelope(
                error_kind=OUTCOME_PROTOCOL_ERROR,
                error=message or f"resources/read failed for {uri}",
                backend=self.name,
                retryable=False,
            )
        result = resp.get("result") or {}
        contents = result.get("contents") or []
        if isinstance(contents, list):
            contents = _bound_content_list(contents)
        return {"success": True, "uri": uri, "contents": contents, "backend": self.name}

    async def list_prompts(self) -> List[Dict[str, Any]]:
        """Live-backend prompts/list (F-e126a298). Follows nextCursor."""
        if not self._connected:
            raise BackendNotConnectedError(self.name)
        self._prompts = await self._list_paginated("prompts/list", "prompts")
        return list(self._prompts)

    async def get_prompt(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Live-backend prompts/get (F-e126a298)."""
        if not self._connected:
            raise BackendNotConnectedError(self.name)
        params: Dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        resp = await self._send_request("prompts/get", params)
        if "error" in resp:
            err = resp["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            return make_error_envelope(
                error_kind=OUTCOME_PROTOCOL_ERROR,
                error=message or f"prompts/get failed for {name}",
                backend=self.name,
                retryable=False,
            )
        result = resp.get("result") or {}
        return {
            "success": True,
            "name": name,
            "description": result.get("description"),
            "messages": result.get("messages") or [],
            "backend": self.name,
        }

    async def active_probe(self, timeout: float = HEALTH_PROBE_TIMEOUT) -> Dict[str, Any]:
        """Send a lightweight ``tools/list`` request and measure latency.

        BR-B-007: an active probe is the only way to detect a backend whose
        subprocess is alive but stuck (e.g. hung on a network read with no
        timeout). The passive ``is_connected`` check has no signal there.

        Returns a structured probe result:

        - ``{ok: True, latency_ms: float}`` on success.
        - ``{ok: False, error_kind: ..., error: str, latency_ms?: float}``
          on failure (timeout / not connected / protocol error).

        Stats are NOT recorded for probes — probes must not corrupt the
        tool-call health signal.
        """
        if not self._connected or not self._process or self._process.returncode is not None:
            return {
                "ok": False,
                "error_kind": OUTCOME_BACKEND_UNAVAILABLE,
                "error": "backend not connected",
            }

        start_time = asyncio.get_event_loop().time()
        try:
            await asyncio.wait_for(
                self._send_request("tools/list", {}), timeout=timeout
            )
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error_kind": OUTCOME_TIMEOUT,
                "error": f"probe timed out after {timeout}s",
                "latency_ms": (asyncio.get_event_loop().time() - start_time) * 1000,
            }
        except BackendShuttingDownError:
            return {
                "ok": False,
                "error_kind": OUTCOME_SHUTDOWN_CANCELLED,
                "error": "shutting down",
            }
        except BackendOverloadedError:
            return {
                "ok": False,
                "error_kind": OUTCOME_BACKEND_UNAVAILABLE,
                "error": "overloaded",
            }
        except (BackendNotConnectedError, BackendProtocolError) as e:
            return {
                "ok": False,
                "error_kind": OUTCOME_PROTOCOL_ERROR,
                "error": str(e),
            }
        except Exception as e:
            return {
                "ok": False,
                "error_kind": OUTCOME_TRANSPORT_ERROR,
                "error": str(e),
            }
        latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        return {"ok": True, "latency_ms": latency_ms}

    @property
    def is_connected(self) -> bool:
        # Check both flag and process health
        if not self._connected:
            return False
        if self._process and self._process.returncode is not None:
            self._connected = False
            return False
        return True

    @property
    def stats(self) -> ConnectionStats:
        return self._stats


class HttpBackendConnection:
    """Per-backend MCP connection over Streamable HTTP.

    INT-01: the HTTP transport for the gateway. Unlike
    :class:`SimpleBackendConnection` (which hand-rolls subprocess JSON-RPC to
    dodge the anyio task-group nesting hazard), this class WRAPS the official
    MCP SDK's Streamable HTTP client. That hazard is subprocess/Proactor-pipe
    specific and does not apply to HTTP, so nesting the SDK's anyio task group
    under our own is safe here. The reference for the AsyncExitStack +
    ClientSession pattern is ``backend_client_mcp.py``.

    Duck-typed contract — this class exposes exactly the surface the
    :class:`SimpleBackendManager` relies on, so the manager stays
    transport-agnostic:

    - ``connect(timeout=None) -> bool``
    - ``disconnect()`` (idempotent)
    - ``call_tool(tool_name, arguments) -> dict`` (same error envelope +
      :class:`ConnectionStats` recording as the stdio path)
    - ``get_tools() -> List[ToolInfo]`` (captures ``inputSchema`` so schema
      fidelity flows downstream identically to stdio)
    - ``active_probe(timeout=HEALTH_PROBE_TIMEOUT) -> dict`` (same probe dict
      shape as :meth:`SimpleBackendConnection.active_probe`)
    - properties ``is_connected`` / ``stats``
    - ``_abandoned_pids`` — always an empty list; there is no subprocess to
      abandon over HTTP, but ``get_stats`` reads ``conn._abandoned_pids``
      unconditionally so we set it to ``[]`` to avoid an AttributeError there.

    Outcome mapping mirrors the stdio path so health signals stay coherent
    across transports:

    - MCP ``isError`` result -> ``OUTCOME_TOOL_ERROR`` (LLM reasons about it;
      NOT a backend-health failure).
    - :class:`McpError` (structured JSON-RPC error over the session) ->
      ``OUTCOME_PROTOCOL_ERROR`` carrying ``.error.code`` / ``.message`` /
      ``.data``.
    - httpx transport errors / HTTP status errors /
      :class:`StreamableHTTPError` -> ``OUTCOME_TRANSPORT_ERROR``.
    - :class:`asyncio.TimeoutError` -> ``OUTCOME_TIMEOUT``.
    """

    def __init__(self, name: str, backend: HttpBackend):
        self.name = name
        self.backend = backend
        self._session: Optional[ClientSession] = None
        # AsyncExitStack owns the lifecycle of both the streamable_http_client
        # context and the ClientSession context; aclose()-ing it in
        # disconnect() unwinds both in LIFO order.
        self._exit_stack: Optional[AsyncExitStack] = None
        self._tools: List[Dict[str, Any]] = []
        self._connected = False
        self._stats = ConnectionStats()
        # INT-01: no subprocess over HTTP, so nothing is ever abandoned — but
        # get_stats() reads conn._abandoned_pids unconditionally. Keep the
        # attribute present (empty) so the stdio-shaped stats path does not
        # AttributeError on an HTTP backend.
        self._abandoned_pids: List[int] = []
        self._last_notification_at: Optional[datetime] = None
        self._on_catalog_changed: Optional[Callable[[str], Any]] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._resources: List[Dict[str, Any]] = []
        self._prompts: List[Dict[str, Any]] = []
        self._progress_callback: Optional[Any] = None
        self._shutting_down: bool = False

    async def _http_message_handler(self, message: Any) -> None:
        """F-414d48d4: honor tools/list_changed (and sibling) notifications."""
        try:
            root = getattr(message, "root", message)
            inner = getattr(root, "root", None)
            method = getattr(root, "method", None) or getattr(message, "method", None)
            if not method:
                method = getattr(inner, "method", None)
            if not method:
                return
            self._last_notification_at = datetime.now()
            method_s = str(method)
            if method_s.endswith("tools/list_changed"):
                await self._refresh_http_tools()
            elif method_s.endswith("prompts/list_changed"):
                await self._refresh_http_prompts()
            elif method_s.endswith("resources/list_changed"):
                await self._refresh_http_resources()
            elif method_s.endswith("/progress"):
                params = getattr(root, "params", None)
                if params is None and inner is not None:
                    params = getattr(inner, "params", None)
                if params is not None and self._progress_callback is not None:
                    await _invoke_progress(
                        self._progress_callback,
                        float(getattr(params, "progress", 0) or 0),
                        getattr(params, "total", None),
                        getattr(params, "message", None),
                    )
        except Exception as e:
            logger.debug(f"HTTP message handler for {self.name} failed: {e}")

    async def _refresh_http_tools(self) -> None:
        if self._session is None or not self._connected:
            return
        try:
            self._tools = await self._http_list_tools_paginated()
            cb = self._on_catalog_changed
            if cb is not None:
                maybe = cb(self.name)
                if asyncio.iscoroutine(maybe):
                    await maybe
        except Exception as e:
            logger.warning(f"HTTP tools refresh for {self.name} failed: {e}")

    async def _refresh_http_prompts(self) -> None:
        if self._session is None or not self._connected:
            return
        try:
            self._prompts = await self._http_list_prompts_paginated()
        except Exception as e:
            logger.warning(f"HTTP prompts refresh for {self.name} failed: {e}")

    async def _refresh_http_resources(self) -> None:
        if self._session is None or not self._connected:
            return
        try:
            self._resources = await self._http_list_resources_paginated()
        except Exception as e:
            logger.warning(f"HTTP resources refresh for {self.name} failed: {e}")

    async def _http_list_tools_paginated(self) -> List[Dict[str, Any]]:
        assert self._session is not None
        tools: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(MAX_LIST_PAGES):
            result = (
                await self._session.list_tools(cursor=cursor)
                if cursor
                else await self._session.list_tools()
            )
            for tool in result.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": (
                        tool.inputSchema
                        if getattr(tool, "inputSchema", None) is not None
                        else {}
                    ),
                })
            cursor = getattr(result, "nextCursor", None)
            if not isinstance(cursor, str) or not cursor:
                break
        return tools

    async def _http_list_resources_paginated(self) -> List[Dict[str, Any]]:
        assert self._session is not None
        items: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(MAX_LIST_PAGES):
            result = (
                await self._session.list_resources(cursor=cursor)
                if cursor
                else await self._session.list_resources()
            )
            for res in result.resources:
                dumped = res.model_dump(mode="json") if hasattr(res, "model_dump") else {
                    "uri": str(getattr(res, "uri", "")),
                    "name": getattr(res, "name", None),
                    "description": getattr(res, "description", None),
                    "mimeType": getattr(res, "mimeType", None),
                }
                items.append(dumped)
            cursor = getattr(result, "nextCursor", None)
            if not isinstance(cursor, str) or not cursor:
                break
        return items

    async def _http_list_prompts_paginated(self) -> List[Dict[str, Any]]:
        assert self._session is not None
        items: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(MAX_LIST_PAGES):
            result = (
                await self._session.list_prompts(cursor=cursor)
                if cursor
                else await self._session.list_prompts()
            )
            for prompt in result.prompts:
                dumped = prompt.model_dump(mode="json") if hasattr(prompt, "model_dump") else {
                    "name": getattr(prompt, "name", ""),
                    "description": getattr(prompt, "description", None),
                    "arguments": getattr(prompt, "arguments", None),
                }
                items.append(dumped)
            cursor = getattr(result, "nextCursor", None)
            if not isinstance(cursor, str) or not cursor:
                break
        return items

    async def _keepalive_loop(self) -> None:
        try:
            while not self._shutting_down and self._connected and self._session is not None:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._shutting_down or not self._connected or self._session is None:
                    break
                try:
                    await asyncio.wait_for(
                        self._session.send_ping(), timeout=HEALTH_PROBE_TIMEOUT
                    )
                except Exception:
                    try:
                        await asyncio.wait_for(
                            self._session.list_tools(), timeout=HEALTH_PROBE_TIMEOUT
                        )
                    except Exception as e:
                        logger.warning(f"HTTP keepalive failed for {self.name}: {e}")
                        self._connected = False
                        break
        except asyncio.CancelledError:
            raise

    def _start_keepalive(self) -> None:
        if self._keepalive_task is not None and not self._keepalive_task.done():
            return
        try:
            self._keepalive_task = asyncio.get_running_loop().create_task(
                self._keepalive_loop()
            )
        except Exception as e:
            logger.debug(f"HTTP keepalive start for {self.name} failed: {e}")

    async def _stop_keepalive(self) -> None:
        task = self._keepalive_task
        self._keepalive_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"HTTP keepalive stop for {self.name}: {e}")

    async def connect(self, timeout: Optional[float] = None) -> bool:
        """Establish the Streamable HTTP session and cache the tool list.

        Enters ``streamablehttp_client`` then :class:`ClientSession` under a
        single :class:`AsyncExitStack` stored on ``self`` so disconnect() can
        unwind both. ``initialize`` and ``list_tools`` are bounded by
        ``timeout`` (falls back to ``CONNECTION_TIMEOUT``). Any failure tears
        the half-open session down via :meth:`disconnect` and returns ``False``
        — never leaks a partially-entered exit stack.
        """
        if self._connected and self._session is not None:
            return True

        timeout = timeout or CONNECTION_TIMEOUT

        try:
            logger.info(
                f"Connecting to HTTP backend: {self.name} "
                f"(url={self.backend.url} timeout={timeout}s)"
            )

            # Build the underlying httpx client via the SDK's factory hook so
            # our configured headers / connect timeout / (no) auth are applied
            # to every request the transport makes. backend.headers is already
            # redacted for logging by the config layer; the real values flow
            # here into the transport only.
            def _http_client_factory(
                headers: Optional[Dict[str, str]] = None,
                timeout: Optional[httpx.Timeout] = None,  # noqa: A002 - SDK hook name
                auth: Optional[httpx.Auth] = None,
            ) -> httpx.AsyncClient:
                return create_mcp_http_client(
                    headers=dict(self.backend.headers) if self.backend.headers else None,
                    timeout=httpx.Timeout(self.backend.timeout),
                    auth=None,
                )

            self._exit_stack = AsyncExitStack()
            transport = await self._exit_stack.enter_async_context(
                streamablehttp_client(
                    self.backend.url,
                    headers=dict(self.backend.headers) if self.backend.headers else None,
                    timeout=httpx.Timeout(self.backend.timeout),
                    auth=None,
                    httpx_client_factory=_http_client_factory,
                )
            )
            # streamablehttp_client yields (read, write, get_session_id). We
            # only need the two streams for the session; the session-id getter
            # is not used by this connection.
            read_stream, write_stream, _get_sid = transport

            self._session = await self._exit_stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    client_info=Implementation(
                        name="tool-compass", version=__version__
                    ),
                    message_handler=self._http_message_handler,
                )
            )

            await asyncio.wait_for(self._session.initialize(), timeout=timeout)

            # Follow nextCursor so list_changed + first connect see the
            # full catalog (F-414d48d4).
            self._tools = await asyncio.wait_for(
                self._http_list_tools_paginated(), timeout=timeout
            )

            self._connected = True
            self._shutting_down = False
            self._stats.connected_at = datetime.now()
            self._stats.last_used = datetime.now()
            logger.info(
                f"Connected to {self.name}: {len(self._tools)} tools available"
            )
            return True

        except asyncio.TimeoutError:
            logger.error(
                f"HTTP connection to {self.name} timed out after {timeout}s"
            )
            await self.disconnect()
            return False
        except Exception as e:
            logger.error(f"Failed to connect to HTTP backend {self.name}: {e}")
            await self.disconnect()
            return False
        except BaseException:
            # CancelledError is a BaseException on 3.9+; a cancel during
            # enter_async_context / initialize / list_tools must still
            # aclose the partially-entered exit stack.
            try:
                await self.disconnect()
            except Exception:
                logger.debug(
                    f"Disconnect after cancelled HTTP connect to {self.name} failed"
                )
            raise

    async def disconnect(self) -> None:
        """Close the session by unwinding the AsyncExitStack. Idempotent.

        Both the ClientSession and the streamable_http_client context were
        entered on ``self._exit_stack``; a single ``aclose`` tears them down in
        LIFO order. Safe to call repeatedly and from the failure path of
        :meth:`connect` (half-open stack).
        """
        self._connected = False
        self._shutting_down = True
        await self._stop_keepalive()
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning(
                    f"Error closing HTTP connection to {self.name}: {e}"
                )
            self._exit_stack = None
        self._session = None
        self._tools = []

    def get_tools(self) -> List[ToolInfo]:
        """Get normalized tool info list.

        Identical shape to :meth:`SimpleBackendConnection.get_tools` — the
        cached ``self._tools`` dicts carry ``inputSchema`` so schema fidelity
        flows downstream the same way for both transports.
        """
        tools = []
        for tool in self._tools:
            tools.append(ToolInfo(
                name=tool.get("name", ""),
                qualified_name=f"{self.name}:{tool.get('name', '')}",
                description=tool.get("description", ""),
                server=self.name,
                input_schema=tool.get("inputSchema", {}),
            ))
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Call a tool over the HTTP session.

        Returns the SAME structured envelope as
        :meth:`SimpleBackendConnection.call_tool` (BR-B-001 / BR-B-012), built
        with :func:`make_error_envelope` and recording the SAME outcome
        taxonomy into :class:`ConnectionStats`. Wrapped in ``asyncio.wait_for``
        with the resolved deadline (explicit / execute_tool-inherited /
        PER_REQUEST_TIMEOUT) so a hung session cannot pin the caller
        indefinitely and configured timeouts above 30s are honoured.
        """
        if not self._connected or self._session is None:
            raise BackendNotConnectedError(self.name)

        start_time = asyncio.get_event_loop().time()
        deadline = _effective_request_timeout(timeout)
        self._progress_callback = progress_callback
        try:
            res = await asyncio.wait_for(
                self._session.call_tool(
                    tool_name,
                    arguments,
                    progress_callback=progress_callback,
                ),
                timeout=deadline,
            )

            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            content_list = list(res.content) if res.content else []

            if res.isError:
                # MCP-level tool error — the LLM should reason about this.
                # Preserve the content array (dumped to plain dicts so the
                # envelope stays JSON-serialisable). NOT a backend-health
                # failure (BR-B-004).
                dumped = _dump_content(content_list)
                error_text = _join_text_content(content_list) or "Tool returned error"
                self._stats.record_call(
                    latency_ms=latency_ms, outcome=OUTCOME_TOOL_ERROR
                )
                return make_error_envelope(
                    error_kind=OUTCOME_TOOL_ERROR,
                    error=error_text,
                    backend=self.name,
                    retryable=True,
                    content=dumped,
                )

            # Success — join TextContent parts for ``result`` and dump the
            # full content array for ``content``.
            text = _join_text_content(content_list)
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_SUCCESS
            )
            return {
                "success": True,
                "result": text if text else "Tool executed successfully",
                "content": _bound_content_list(_dump_content(content_list)),
            }

        except McpError as e:
            # Structured JSON-RPC error surfaced by the SDK session. Carries
            # ``.error.code`` / ``.message`` / ``.data`` — map to protocol_error
            # exactly as the stdio path maps a JSON-RPC ``error`` object.
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            err = e.error
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_PROTOCOL_ERROR
            )
            return make_error_envelope(
                error_kind=OUTCOME_PROTOCOL_ERROR,
                error=getattr(err, "message", str(e)),
                backend=self.name,
                code=getattr(err, "code", None),
                data=getattr(err, "data", None),
                retryable=False,
            )
        except asyncio.TimeoutError as e:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_TIMEOUT
            )
            raise ToolCallTimeoutError(
                f"HTTP backend {self.name} tool call timed out"
            ) from e
        except (
            httpx.TransportError,
            httpx.HTTPStatusError,
            StreamableHTTPError,
        ) as e:
            # Pipe-equivalent for HTTP: the transport dropped / the server
            # returned a hard error. Mark the connection unhealthy so the
            # manager's transport-retry path reconnects. httpx.TransportError
            # propagates so execute_tool's retry-except catches it.
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_TRANSPORT_ERROR
            )
            self._connected = False
            logger.warning(
                f"HTTP backend {self.name} transport error, will reconnect "
                f"on next call: {e}"
            )
            raise
        except BackendShuttingDownError:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_SHUTDOWN_CANCELLED
            )
            raise
        except Exception:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            # Genuinely-unknown failures default to transport_error — these are
            # typically session / runtime issues, not tool failures.
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_TRANSPORT_ERROR
            )
            self._connected = False
            raise
        finally:
            self._progress_callback = None

    async def list_resources(self) -> List[Dict[str, Any]]:
        """Live-backend resources/list over HTTP (F-e126a298)."""
        if not self._connected or self._session is None:
            raise BackendNotConnectedError(self.name)
        self._resources = await self._http_list_resources_paginated()
        return list(self._resources)

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Live-backend resources/read over HTTP (F-e126a298)."""
        if not self._connected or self._session is None:
            raise BackendNotConnectedError(self.name)
        from pydantic import AnyUrl
        try:
            result = await self._session.read_resource(AnyUrl(uri))
        except McpError as e:
            err = e.error
            return make_error_envelope(
                error_kind=OUTCOME_PROTOCOL_ERROR,
                error=getattr(err, "message", str(e)),
                backend=self.name,
                code=getattr(err, "code", None),
                retryable=False,
            )
        contents = []
        for item in result.contents or []:
            if hasattr(item, "model_dump"):
                contents.append(item.model_dump(mode="json"))
            else:
                contents.append({
                    "uri": str(getattr(item, "uri", uri)),
                    "mimeType": getattr(item, "mimeType", None),
                    "text": getattr(item, "text", None),
                    "blob": getattr(item, "blob", None),
                })
        return {
            "success": True,
            "uri": uri,
            "contents": _bound_content_list(contents),
            "backend": self.name,
        }

    async def list_prompts(self) -> List[Dict[str, Any]]:
        """Live-backend prompts/list over HTTP (F-e126a298)."""
        if not self._connected or self._session is None:
            raise BackendNotConnectedError(self.name)
        self._prompts = await self._http_list_prompts_paginated()
        return list(self._prompts)

    async def get_prompt(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Live-backend prompts/get over HTTP (F-e126a298)."""
        if not self._connected or self._session is None:
            raise BackendNotConnectedError(self.name)
        str_args = None
        if arguments:
            str_args = {k: str(v) for k, v in arguments.items()}
        try:
            result = await self._session.get_prompt(name, str_args)
        except McpError as e:
            err = e.error
            return make_error_envelope(
                error_kind=OUTCOME_PROTOCOL_ERROR,
                error=getattr(err, "message", str(e)),
                backend=self.name,
                code=getattr(err, "code", None),
                retryable=False,
            )
        messages = []
        for msg in result.messages or []:
            if hasattr(msg, "model_dump"):
                messages.append(msg.model_dump(mode="json"))
            else:
                messages.append(msg)
        return {
            "success": True,
            "name": name,
            "description": getattr(result, "description", None),
            "messages": messages,
            "backend": self.name,
        }

    async def active_probe(self, timeout: float = HEALTH_PROBE_TIMEOUT) -> Dict[str, Any]:
        """Lightweight liveness check via ``send_ping``.

        BR-B-007: returns the SAME probe dict shape as
        :meth:`SimpleBackendConnection.active_probe`
        (``{ok: True, latency_ms}`` / ``{ok: False, error_kind, error}``).
        Stats are NOT recorded for probes so the tool-call health signal is
        not corrupted.
        """
        if not self._connected or self._session is None:
            return {
                "ok": False,
                "error_kind": OUTCOME_BACKEND_UNAVAILABLE,
                "error": "backend not connected",
            }

        start_time = asyncio.get_event_loop().time()
        try:
            await asyncio.wait_for(self._session.send_ping(), timeout=timeout)
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error_kind": OUTCOME_TIMEOUT,
                "error": f"probe timed out after {timeout}s",
                "latency_ms": (asyncio.get_event_loop().time() - start_time) * 1000,
            }
        except McpError as e:
            return {
                "ok": False,
                "error_kind": OUTCOME_PROTOCOL_ERROR,
                "error": str(e),
            }
        except (
            httpx.TransportError,
            httpx.HTTPStatusError,
            StreamableHTTPError,
        ) as e:
            return {
                "ok": False,
                "error_kind": OUTCOME_TRANSPORT_ERROR,
                "error": str(e),
            }
        except Exception as e:
            return {
                "ok": False,
                "error_kind": OUTCOME_TRANSPORT_ERROR,
                "error": str(e),
            }
        latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        return {"ok": True, "latency_ms": latency_ms}

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    @property
    def stats(self) -> ConnectionStats:
        return self._stats


def _join_text_content(content_list: List[Any]) -> str:
    """Concatenate the ``text`` of every TextContent-like item.

    INT-01: HTTP results come back as SDK content objects (TextContent, etc.),
    NOT plain dicts like the stdio path. Duck-type on a ``.text`` attribute
    with a ``.type == 'text'`` guard so image / audio / resource blocks are
    skipped for the ``result`` string (they are still preserved in the dumped
    ``content`` array).
    """
    parts: List[str] = []
    for item in content_list:
        if getattr(item, "type", None) == "text" and hasattr(item, "text"):
            parts.append(item.text)
    return "".join(parts)


def _dump_content(content_list: List[Any]) -> List[Any]:
    """Render SDK content objects into JSON-serialisable plain dicts.

    INT-01: the envelope must stay JSON-serialisable for the gateway. SDK
    content blocks are pydantic models exposing ``model_dump``; fall back to
    the object itself if it is already a plain type.
    """
    dumped: List[Any] = []
    for item in content_list:
        if hasattr(item, "model_dump"):
            dumped.append(item.model_dump(mode="json"))
        else:
            dumped.append(item)
    return dumped


class SimpleBackendManager:
    """
    Manages multiple MCP backend connections using simple subprocess approach.

    Features:
    - Connection pooling with keep-alive
    - Automatic reconnection on failure
    - Health monitoring
    - Graceful shutdown
    """

    def __init__(self, config: Optional[CompassConfig] = None):
        self.config = config or load_config()
        self._backends: Dict[str, SimpleBackendConnection] = {}
        self._tool_index: Dict[str, str] = {}
        # BR-B-005: lazy lock construction; bound to running loop on first
        # use rather than at __init__ time.
        self._lock: Optional[asyncio.Lock] = None
        # F-47ef65da: single-flight slot per backend. Concurrent
        # ensure_connected / connect_backend waiters await this instead of
        # spawning a sibling subprocess / HTTP session.
        self._connecting: Dict[str, "asyncio.Future[bool]"] = {}
        # F-51e46b4c: breaker + call stats survive reconnect (new Connection
        # objects would otherwise reset consecutive_failures).
        self._backend_stats: Dict[str, ConnectionStats] = {}

    def _stats_for(self, name: str) -> ConnectionStats:
        stats = self._backend_stats.get(name)
        if stats is None:
            stats = ConnectionStats()
            self._backend_stats[name] = stats
        return stats

    def _reindex_backend(self, name: str) -> None:
        """Rebuild _tool_index entries for one backend after list_changed."""
        stale = [k for k, v in self._tool_index.items() if v == name]
        for k in stale:
            self._tool_index.pop(k, None)
        conn = self._backends.get(name)
        if conn is None:
            return
        for tool in conn.get_tools():
            self._tool_index[tool.qualified_name] = name

    def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def connect_backend(self, name: str, timeout: Optional[float] = None) -> bool:
        """Connect to a specific backend with retry logic.

        BR-B-002: the manager lock is held only across the registry-state
        snapshots (read backend config, swap in the new connection); the
        long-lived ``disconnect`` and ``connect`` awaits run OUTSIDE the
        lock so a sick backend cannot starve siblings.

        F-47ef65da: a per-backend connecting future makes spawn single-flight.
        Waiters await the in-flight connect instead of spawning a sibling.
        On swap, a different live occupant wins and the extra is disconnected.
        """
        lock = self._ensure_lock()
        waiter: Optional["asyncio.Future[bool]"] = None
        slot: Optional["asyncio.Future[bool]"] = None
        old_conn = None
        backend = None
        reject_reason: Optional[str] = None

        if self.is_backend_connected(name):
            return True
        stats = self._stats_for(name)
        if not stats.breaker_can_attempt():
            logger.warning(
                f"Skipping connect to {name}: breaker {stats.breaker_state} "
                f"retry_after={stats.breaker_retry_after()}"
            )
            return False

        async with lock:
            # Check if already connected (cheap registry read).
            if name in self._backends and self._backends[name].is_connected:
                return True

            inflight = self._connecting.get(name)
            if inflight is not None and not inflight.done():
                waiter = inflight
            else:
                slot = asyncio.get_running_loop().create_future()
                self._connecting[name] = slot

                backend = self.config.backends.get(name)
                if not backend:
                    reject_reason = "unknown"
                elif not isinstance(backend, (StdioBackend, HttpBackend)):
                    reject_reason = "unsupported"
                else:
                    # Pop the old broken connection out of the registry under
                    # lock so concurrent callers see "not connected"
                    # immediately, but actually disconnect / connect outside
                    # the lock.
                    old_conn = self._backends.pop(name, None)
                    stale_keys = [
                        k for k, v in self._tool_index.items() if v == name
                    ]
                    for k in stale_keys:
                        self._tool_index.pop(k, None)

        if waiter is not None:
            return await waiter

        extra = None
        result = False
        try:
            if reject_reason == "unknown":
                logger.error(f"Unknown backend: {name}")
                return False
            if reject_reason == "unsupported":
                logger.error(
                    f"Unsupported backend type for {name}: {type(backend).__name__}"
                )
                return False

            # Async work outside the manager lock.
            if old_conn is not None:
                try:
                    await old_conn.disconnect()
                except Exception as e:
                    logger.debug(f"Old-connection disconnect for {name}: {e}")

            # INT-01: transport factory. Both connection classes expose the
            # same duck-typed contract the manager relies on
            # (connect / is_connected / get_tools / disconnect / call_tool /
            # active_probe / stats / _abandoned_pids), so everything
            # downstream of this line — the retry loop, the registry swap,
            # execute_tool — is transport-agnostic.
            if isinstance(backend, StdioBackend):
                conn: Any = SimpleBackendConnection(name, backend)
            else:
                # isinstance(backend, HttpBackend) — guaranteed by the type
                # gate under the lock above.
                conn = HttpBackendConnection(name, backend)
            conn._stats = stats
            conn._on_catalog_changed = self._reindex_backend
            connected = False
            # Half-open: a single probe, not CONNECTION_TIMEOUT × retries.
            attempts = 1 if stats.breaker_state == BREAKER_HALF_OPEN else (MAX_RETRIES + 1)
            for attempt in range(attempts):
                success = await conn.connect(timeout=timeout)
                if success:
                    connected = True
                    break
                if attempt < attempts - 1:
                    logger.warning(
                        f"Retry {attempt + 1}/{MAX_RETRIES} for backend {name}"
                    )
                    await asyncio.sleep(0.5)

            if not connected:
                stats.record_call(
                    latency_ms=(timeout or CONNECTION_TIMEOUT) * 1000.0,
                    outcome=OUTCOME_TRANSPORT_ERROR,
                )
                return False
            if stats.breaker_state != BREAKER_CLOSED:
                stats._set_breaker(BREAKER_CLOSED)

            # Swap the new connection back into the registry under the lock.
            # Occupancy check: if another live conn is already stored, keep
            # it and disconnect this extra so we never orphan a process.
            async with lock:
                existing = self._backends.get(name)
                if (
                    existing is not None
                    and existing is not conn
                    and existing.is_connected
                ):
                    extra = conn
                    result = True
                else:
                    if existing is not None and existing is not conn:
                        extra = existing
                    self._backends[name] = conn
                    for tool in conn.get_tools():
                        self._tool_index[tool.qualified_name] = name
                    result = True
                    starter = getattr(conn, "_start_keepalive", None)
                    if callable(starter):
                        starter()
            return result
        except BaseException:
            result = False
            raise
        finally:
            try:
                if extra is not None:
                    try:
                        await extra.disconnect()
                    except Exception as e:
                        logger.debug(
                            f"Extra-connection disconnect for {name}: {e}"
                        )
            finally:
                if slot is not None and not slot.done():
                    slot.set_result(result)
                if self._connecting.get(name) is slot:
                    self._connecting.pop(name, None)

    def is_backend_connected(self, name: str) -> bool:
        """Check if a backend is currently connected."""
        return name in self._backends and self._backends[name].is_connected

    async def ensure_connected(self, name: str) -> bool:
        """Ensure a backend is connected, reconnecting if necessary."""
        if self.is_backend_connected(name):
            return True
        return await self.connect_backend(name)

    async def connect_all(self, timeout: Optional[float] = None) -> Dict[str, bool]:
        """Connect to all configured backends.

        Returns:
            Dict mapping backend name to connection success status.
        """
        results = {}
        for name in self.config.backends.keys():
            try:
                success = await self.connect_backend(name, timeout=timeout)
                results[name] = success
            except Exception as e:
                logger.error(f"Failed to connect to {name}: {e}")
                results[name] = False
        return results

    async def disconnect_all(self, *, total_timeout: Optional[float] = None) -> Dict[str, Any]:
        """Disconnect from all backends gracefully.

        BR-B-002: the manager lock is held ONLY across the snapshot/clear
        operations; the per-connection ``disconnect`` calls happen OUTSIDE
        the lock so a stuck backend cannot starve sibling
        ``connect_backend`` callers.

        BR-B-008: capped total time via ``total_timeout`` (default
        ``KILL_WAIT_TIMEOUT * 2 + 8`` so it always strictly exceeds the
        worst-case per-connection budget). Laggards are tracked in the
        returned report so the operator can identify them.

        Returns: ``{disconnected: [...], laggards: [{name, error}],
        timed_out: bool}``
        """
        lock = self._ensure_lock()

        # Snapshot the connection list and clear the registry under the lock.
        async with lock:
            conns = list(self._backends.items())
            self._backends.clear()
            self._tool_index.clear()
            connecting = list(self._connecting.values())
            self._connecting.clear()
        for fut in connecting:
            if not fut.done():
                fut.set_result(False)

        if not conns:
            return {"disconnected": [], "laggards": [], "timed_out": False}

        # Bound total time so a single sick backend can't wedge us.
        budget = total_timeout
        if budget is None:
            budget = KILL_WAIT_TIMEOUT * 2 + 8.0

        names = [name for name, _ in conns]
        tasks = [conn.disconnect() for _, conn in conns]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=budget,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"disconnect_all hit total budget {budget}s — proceeding "
                "anyway; some backends may have leaked subprocesses"
            )
            # ``gather`` is still running underneath wait_for; cancel its
            # tasks so they don't continue in the background.
            for task in tasks:
                if hasattr(task, "cancel"):
                    try:
                        task.cancel()
                    except Exception:
                        pass
            return {
                "disconnected": [],
                "laggards": [{"name": n, "error": "timeout"} for n in names],
                "timed_out": True,
            }

        disconnected: List[str] = []
        laggards: List[Dict[str, str]] = []
        for name, outcome in zip(names, results):
            if isinstance(outcome, Exception):
                laggards.append({"name": name, "error": str(outcome)})
            else:
                disconnected.append(name)
        return {
            "disconnected": disconnected,
            "laggards": laggards,
            "timed_out": False,
        }

    def get_all_tools(self) -> List[ToolInfo]:
        """Get all tools from all connected backends."""
        tools = []
        for conn in self._backends.values():
            if conn.is_connected:
                tools.extend(conn.get_tools())
        return tools

    def get_backend_tools(self, backend_name: str) -> List[ToolInfo]:
        """Get tools from a specific backend."""
        conn = self._backends.get(backend_name)
        if not conn or not conn.is_connected:
            return []
        return conn.get_tools()

    def get_tool_schema(self, qualified_name: str) -> Optional[Dict[str, Any]]:
        """Get the full schema for a specific tool."""
        server_name = self._tool_index.get(qualified_name)
        if not server_name:
            if ":" in qualified_name:
                server_name = qualified_name.split(":", 1)[0]
            else:
                return None

        conn = self._backends.get(server_name)
        if not conn:
            return None

        for tool in conn.get_tools():
            if tool.qualified_name == qualified_name or tool.name == qualified_name.split(":")[-1]:
                return tool.to_dict()

        return None

    async def execute_tool(
        self,
        qualified_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Execute a tool by its qualified name with automatic reconnection.

        Returns a structured envelope (BR-B-001 / BR-B-012). All error paths
        include ``error_kind`` so the gateway and the LLM can decide what to
        do without string-matching on the message.

        BR-A-005: retry is restricted to transport-level failures (process
        died, pipe broken). Non-transient errors — protocol errors, tool
        errors, timeouts, overloaded — are surfaced without retry so we
        don't paper over real problems with a second attempt.

        BR-B-009: manager-layer timeouts are recorded in the connection
        stats via ``record_call(outcome=OUTCOME_TIMEOUT)`` so the
        ``success_rate`` gauge sees them.

        INT-02: the effective outer deadline is resolved by precedence
        (most-specific wins) AFTER the server/tool split, just before the
        try — see the ``resolved_timeout`` block below. The naive
        ``timeout = timeout or TOOL_CALL_TIMEOUT`` used to live here; it is
        deferred so per-backend / per-tool config can participate.
        """
        # Parse qualified name. BR-A-018: prefer the tool-index match over a
        # naive split so a configured backend name containing ':' (which is
        # also a backend bug — the config layer should reject it, see
        # skipped[]) does not silently route to the wrong server.
        if qualified_name in self._tool_index:
            server_name = self._tool_index[qualified_name]
            # qualified_name is "{server_name}:{tool_name}"; recover tool_name
            # by stripping the known server prefix rather than blindly
            # splitting on ':'.
            prefix = f"{server_name}:"
            if qualified_name.startswith(prefix):
                tool_name = qualified_name[len(prefix):]
            else:
                tool_name = qualified_name
        elif ":" in qualified_name:
            server_name, tool_name = qualified_name.split(":", 1)
        else:
            server_name = self._tool_index.get(qualified_name)
            tool_name = qualified_name
            if not server_name:
                return make_error_envelope(
                    error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                    error=(
                        f"Tool not found: {qualified_name}. "
                        "Use format 'server:tool_name'."
                    ),
                    retryable=False,
                )

        # F-51e46b4c: fail fast when the breaker is OPEN so we do not pay
        # CONNECTION_TIMEOUT × retries on every call.
        breaker = self._stats_for(server_name)
        if not self.is_backend_connected(server_name) and not breaker.breaker_can_attempt():
            retry_after = breaker.breaker_retry_after()
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=(
                    f"Backend {server_name} circuit breaker is open; "
                    "skipping connect"
                ),
                backend=server_name,
                retryable=True,
                retry_after_seconds=retry_after,
            )

        # Ensure connected (with automatic reconnection)
        if not await self.ensure_connected(server_name):
            retry_after = self._stats_for(server_name).breaker_retry_after()
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=f"Failed to connect to backend: {server_name}",
                backend=server_name,
                retryable=True,
                retry_after_seconds=retry_after,
            )

        conn = self._backends.get(server_name)
        if not conn:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=f"Backend not available: {server_name}",
                backend=server_name,
                retryable=True,
            )

        # INT-02: resolve the outer tool-call deadline by precedence, most-
        # specific wins:
        #   explicit ``timeout`` arg
        #     > per-tool override (``tool_timeouts[bare_tool_name]``)
        #     > per-backend default (``default_timeout``)
        #     > TOOL_CALL_TIMEOUT (the process-wide floor; unchanged default).
        # ``tool_timeouts`` is keyed by the BARE tool name (``tool_name``
        # here, already stripped of the ``server:`` prefix above), matching
        # the config-schema contract in config.py. An explicit non-None
        # ``timeout`` short-circuits the whole lookup so callers can always
        # override config. The wait_for and the retry path below both close
        # over this local ``timeout`` and inherit the resolved value.
        resolved_timeout = timeout
        if resolved_timeout is None:
            cfg_backend = self.config.backends.get(server_name)
            if isinstance(cfg_backend, (StdioBackend, HttpBackend)):
                resolved_timeout = (
                    cfg_backend.tool_timeouts.get(tool_name)
                    or cfg_backend.default_timeout
                )
        timeout = resolved_timeout or TOOL_CALL_TIMEOUT

        # Publish the resolved deadline so _send_request /
        # HttpBackendConnection.call_tool use it instead of the hardcoded
        # 30s inner cap. call_tool(name, args) positional contract is
        # unchanged (tests assert that).
        timeout_token = _call_timeout.set(timeout)
        attempt = 1
        try:
            if progress_callback is not None:
                call = conn.call_tool(
                    tool_name, arguments, progress_callback=progress_callback
                )
            else:
                call = conn.call_tool(tool_name, arguments)
            result = await asyncio.wait_for(call, timeout=timeout)
            if isinstance(result, dict):
                result.setdefault("attempt", attempt)
                result.setdefault("retried", False)
            return result
        except ToolCallTimeoutError:
            # call_tool already recorded OUTCOME_TIMEOUT. Do not record again.
            logger.error(
                f"Tool execution timed out after {timeout}s: {qualified_name}"
            )
            return make_error_envelope(
                error_kind=OUTCOME_TIMEOUT,
                error=f"Tool execution timed out after {timeout}s",
                backend=server_name,
                retryable=True,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Tool execution timed out after {timeout}s: {qualified_name}"
            )
            # Outer wait_for cancelled a hanging call_tool that did not
            # itself record (e.g. a mock). Record here — the only layer.
            try:
                conn_for_stats = self._backends.get(server_name)
                if conn_for_stats is not None:
                    conn_for_stats.stats.record_call(
                        latency_ms=timeout * 1000.0,
                        outcome=OUTCOME_TIMEOUT,
                    )
            except Exception:
                pass
            return make_error_envelope(
                error_kind=OUTCOME_TIMEOUT,
                error=f"Tool execution timed out after {timeout}s",
                backend=server_name,
                retryable=True,
            )
        except BackendShuttingDownError as e:
            # BR-A-004: don't surface shutdown as a generic failure.
            return make_error_envelope(
                error_kind=OUTCOME_SHUTDOWN_CANCELLED,
                error=str(e),
                backend=server_name,
                retryable=False,
            )
        except BackendOverloadedError as e:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=str(e),
                backend=server_name,
                retryable=True,
            )
        except BackendNotConnectedError as e:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=str(e),
                backend=server_name,
                retryable=True,
            )
        except BackendProtocolError as e:
            return make_error_envelope(
                error_kind=OUTCOME_PROTOCOL_ERROR,
                error=str(e),
                backend=server_name,
                code=e.code,
                data=e.data,
                retryable=False,
            )
        except (
            BrokenPipeError,
            ConnectionResetError,
            httpx.TransportError,
            StreamableHTTPError,
        ) as transport_err:
            # BR-A-005: transport errors are the ONLY case we retry. The
            # backend's pipe broke — reconnect and try once more.
            # INT-01: httpx.TransportError joins the retry set so a dropped
            # HTTP connection (connection reset, read error, remote close)
            # reconnects + retries once, exactly as a broken subprocess pipe
            # does. StreamableHTTPError joins it too: an SDK-level transport
            # fault (server closed/terminated the stream, malformed SSE frame,
            # session-id mismatch) is transient and reconnectable — call_tool
            # marks _connected=False and re-raises with the explicit intent
            # that this path reconnect + retry, symmetrically with the httpx
            # and stdio (BrokenPipeError) paths. HTTPStatusError is NOT a
            # TransportError subclass and is deliberately excluded, so a 4xx/
            # 5xx does not trigger a blind retry — it surfaces as a
            # transport_error envelope via the generic handler / call_tool.
            logger.error(
                f"Transport error executing {qualified_name}: {transport_err}"
            )
            logger.info(f"Attempting reconnect to {server_name}...")
            attempt = 2
            if await self.connect_backend(server_name):
                retry_conn = self._backends.get(server_name)
                if retry_conn is not None:
                    try:
                        if progress_callback is not None:
                            retry_call = retry_conn.call_tool(
                                tool_name,
                                arguments,
                                progress_callback=progress_callback,
                            )
                        else:
                            retry_call = retry_conn.call_tool(tool_name, arguments)
                        retry_result = await asyncio.wait_for(
                            retry_call, timeout=timeout
                        )
                        if isinstance(retry_result, dict):
                            retry_result["retried"] = True
                            retry_result["attempt"] = attempt
                        return retry_result
                    except ToolCallTimeoutError:
                        return make_error_envelope(
                            error_kind=OUTCOME_TIMEOUT,
                            error=(
                                f"Tool execution timed out after {timeout}s "
                                "on retry"
                            ),
                            backend=server_name,
                            retryable=False,
                        )
                    except asyncio.TimeoutError:
                        try:
                            retry_conn.stats.record_call(
                                latency_ms=timeout * 1000.0,
                                outcome=OUTCOME_TIMEOUT,
                            )
                        except Exception:
                            pass
                        return make_error_envelope(
                            error_kind=OUTCOME_TIMEOUT,
                            error=(
                                f"Tool execution timed out after {timeout}s "
                                "on retry"
                            ),
                            backend=server_name,
                            retryable=False,
                        )
                    except Exception as retry_error:
                        env = make_error_envelope(
                            error_kind=OUTCOME_TRANSPORT_ERROR,
                            error=f"Retry failed: {retry_error}",
                            backend=server_name,
                            retryable=False,
                        )
                        env["retried"] = True
                        env["attempt"] = attempt
                        return env
            return make_error_envelope(
                error_kind=OUTCOME_TRANSPORT_ERROR,
                error=str(transport_err),
                backend=server_name,
                retryable=False,
            )
        except Exception as e:
            logger.error(f"Error executing {qualified_name}: {e}")
            return make_error_envelope(
                error_kind=OUTCOME_TRANSPORT_ERROR,
                error=str(e),
                backend=server_name,
                retryable=False,
            )
        finally:
            _call_timeout.reset(timeout_token)

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics for all backends.

        BR-B-004: surfaces per-outcome counters and the inflight peak so
        the operator can see backend health distinct from tool-error rate.
        """
        connected = []
        stats_by_backend = {}

        last_notification_at: Optional[str] = None
        for name in self.config.backends.keys():
            conn = self._backends.get(name)
            stats = conn.stats if conn is not None else self._stats_for(name)
            is_up = bool(conn is not None and conn.is_connected)
            if is_up:
                connected.append(name)
            note_at = getattr(conn, "_last_notification_at", None) if conn else None
            note_iso = None
            if note_at is not None and hasattr(note_at, "isoformat"):
                try:
                    note_iso = note_at.isoformat()
                except Exception:
                    note_iso = None
            if note_iso and (last_notification_at is None or note_iso > last_notification_at):
                last_notification_at = note_iso
            connected_at = getattr(stats, "connected_at", None)
            last_used = getattr(stats, "last_used", None)
            outcomes = getattr(stats, "outcomes", None)
            transitions = getattr(stats, "breaker_transitions", None)
            retry_after = None
            retry_fn = getattr(stats, "breaker_retry_after", None)
            if callable(retry_fn):
                try:
                    retry_after = retry_fn()
                    if not isinstance(retry_after, (int, float)):
                        retry_after = None
                except Exception:
                    retry_after = None
            breaker_state = getattr(stats, "breaker_state", BREAKER_CLOSED)
            if not isinstance(breaker_state, str):
                breaker_state = BREAKER_CLOSED
            consecutive = getattr(stats, "consecutive_failures", 0)
            if not isinstance(consecutive, (int, float)):
                consecutive = 0
            stats_by_backend[name] = {
                "tools": len(conn.get_tools()) if conn is not None else 0,
                "connected": is_up,
                "total_calls": stats.total_calls,
                "failed_calls": stats.failed_calls,
                "avg_latency_ms": round(stats.avg_latency_ms, 2),
                "connected_at": (
                    connected_at.isoformat()
                    if connected_at is not None and hasattr(connected_at, "isoformat")
                    else None
                ),
                "last_used": (
                    last_used.isoformat()
                    if last_used is not None and hasattr(last_used, "isoformat")
                    else None
                ),
                "outcomes": dict(outcomes) if isinstance(outcomes, dict) else {},
                "inflight_count": stats.inflight_count,
                "inflight_peak": stats.inflight_peak,
                "inflight_cap": MAX_INFLIGHT_REQUESTS_PER_BACKEND,
                "abandoned_pids": list(conn._abandoned_pids) if conn is not None else [],
                "breaker_state": breaker_state,
                "breaker_consecutive_failures": consecutive,
                "breaker_retry_after": retry_after,
                "breaker_transitions": dict(transitions) if isinstance(transitions, dict) else {},
                "last_notification_at": note_iso,
            }

        return {
            "configured_backends": list(self.config.backends.keys()),
            "connected_backends": connected,
            "total_tools": len(self._tool_index),
            "tools_by_backend": {
                name: len(conn.get_tools())
                for name, conn in self._backends.items()
                if conn.is_connected
            },
            "stats": stats_by_backend,
            "last_notification_at": last_notification_at,
        }

    async def health_check(self, *, active: bool = False) -> Dict[str, Any]:
        """Check health of all backends.

        BR-B-004: the ``success_rate`` gauge now reflects only backend
        failures (protocol_error / transport_error / timeout /
        backend_unavailable). Tool errors (legitimate ``isError``) are
        reported separately under ``tool_error_rate`` so a backend serving
        a flaky upstream is not falsely flagged as unhealthy.

        BR-B-007: when ``active=True``, fires an active probe per connected
        backend so a hung-but-alive backend is detected at probe time
        rather than first user request. Probes run with a hard
        :data:`HEALTH_PROBE_TIMEOUT` deadline each, in parallel, so the
        full active check completes in ~``HEALTH_PROBE_TIMEOUT`` seconds.
        """
        health: Dict[str, Any] = {}

        active_results: Dict[str, Dict[str, Any]] = {}
        if active:
            probe_targets = [
                (name, conn) for name, conn in self._backends.items()
                if conn.is_connected
            ]
            if probe_targets:
                probe_coros = [
                    conn.active_probe(timeout=HEALTH_PROBE_TIMEOUT)
                    for _, conn in probe_targets
                ]
                # Each probe already wraps its own wait_for so this gather
                # is bounded; we still cap externally as a belt-and-braces.
                try:
                    probe_outcomes = await asyncio.wait_for(
                        asyncio.gather(*probe_coros, return_exceptions=True),
                        timeout=HEALTH_PROBE_TIMEOUT + 1.0,
                    )
                except asyncio.TimeoutError:
                    probe_outcomes = [
                        {
                            "ok": False,
                            "error_kind": OUTCOME_TIMEOUT,
                            "error": "active probe set timed out",
                        }
                    ] * len(probe_targets)

                for (name, _), outcome in zip(probe_targets, probe_outcomes):
                    if isinstance(outcome, Exception):
                        active_results[name] = {
                            "ok": False,
                            "error_kind": OUTCOME_TRANSPORT_ERROR,
                            "error": str(outcome),
                        }
                    else:
                        active_results[name] = outcome  # type: ignore[assignment]

        for name in self.config.backends.keys():
            conn = self._backends.get(name)
            if conn and conn.is_connected:
                total = max(conn.stats.total_calls, 1)
                # Health = "backend not blamed for the call." Tool errors
                # are NOT a backend health problem.
                tool_errors = conn.stats.outcomes.get(OUTCOME_TOOL_ERROR, 0)
                shutdown_cancels = conn.stats.outcomes.get(
                    OUTCOME_SHUTDOWN_CANCELLED, 0
                )
                # Effective denominator excludes shutdown-cancelled.
                eff_denom = max(conn.stats.total_calls - shutdown_cancels, 1)
                health_signal_pct = round(
                    (1 - conn.stats.failed_calls / eff_denom) * 100, 1
                )
                tool_error_rate_pct = round(
                    (tool_errors / max(total, 1)) * 100, 1
                )
                entry: Dict[str, Any] = {
                    "status": "connected",
                    "tools": len(conn.get_tools()),
                    "success_rate": health_signal_pct,
                    "tool_error_rate": tool_error_rate_pct,
                    "outcomes": dict(conn.stats.outcomes),
                    "inflight_count": conn.stats.inflight_count,
                    "inflight_peak": conn.stats.inflight_peak,
                    "breaker_state": conn.stats.breaker_state,
                }
                if name in active_results:
                    entry["probe"] = active_results[name]
                    if not active_results[name].get("ok"):
                        entry["status"] = "degraded"
                health[name] = entry
            else:
                stats = self._stats_for(name)
                health[name] = {
                    "status": "disconnected",
                    "breaker_state": stats.breaker_state,
                    "breaker_retry_after": stats.breaker_retry_after(),
                }
        return health

    async def _ensure_named(self, server_name: str) -> Optional[Any]:
        if not await self.ensure_connected(server_name):
            return None
        return self._backends.get(server_name)

    async def list_resources(
        self, server_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Live-backend resources/list, qualified as server:uri (F-e126a298)."""
        names = [server_name] if server_name else list(self.config.backends.keys())
        resources: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for name in names:
            if name is None:
                continue
            conn = await self._ensure_named(name)
            if conn is None:
                errors[name] = "not connected"
                continue
            try:
                items = await conn.list_resources()
            except Exception as e:
                errors[name] = str(e)
                continue
            for item in items:
                uri = item.get("uri") if isinstance(item, dict) else getattr(item, "uri", None)
                qualified = f"{name}:{uri}" if uri else name
                entry = dict(item) if isinstance(item, dict) else {"uri": str(uri)}
                entry["server"] = name
                entry["qualified"] = qualified
                resources.append(entry)
        return {"resources": resources, "errors": errors, "total": len(resources)}

    async def read_resource(self, qualified_uri: str) -> Dict[str, Any]:
        """Read a resource qualified as server:uri (F-e126a298)."""
        if ":" not in qualified_uri:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error="Use format 'server:uri' (e.g. docs:file://specs/readme.md)",
                retryable=False,
            )
        server_name, uri = qualified_uri.split(":", 1)
        conn = await self._ensure_named(server_name)
        if conn is None:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=f"Failed to connect to backend: {server_name}",
                backend=server_name,
                retryable=True,
            )
        try:
            result = await conn.read_resource(uri)
        except Exception as e:
            return make_error_envelope(
                error_kind=OUTCOME_TRANSPORT_ERROR,
                error=str(e),
                backend=server_name,
                retryable=True,
            )
        if isinstance(result, dict):
            result.setdefault("qualified", qualified_uri)
            result.setdefault("server", server_name)
        return result

    async def list_prompts(
        self, server_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Live-backend prompts/list, qualified as server:name (F-e126a298)."""
        names = [server_name] if server_name else list(self.config.backends.keys())
        prompts: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for name in names:
            if name is None:
                continue
            conn = await self._ensure_named(name)
            if conn is None:
                errors[name] = "not connected"
                continue
            try:
                items = await conn.list_prompts()
            except Exception as e:
                errors[name] = str(e)
                continue
            for item in items:
                pname = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
                qualified = f"{name}:{pname}" if pname else name
                entry = dict(item) if isinstance(item, dict) else {"name": str(pname)}
                entry["server"] = name
                entry["qualified"] = qualified
                prompts.append(entry)
        return {"prompts": prompts, "errors": errors, "total": len(prompts)}

    async def get_prompt(
        self,
        qualified_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Get a prompt qualified as server:name (F-e126a298)."""
        if ":" not in qualified_name:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error="Use format 'server:prompt_name'",
                retryable=False,
            )
        server_name, prompt_name = qualified_name.split(":", 1)
        conn = await self._ensure_named(server_name)
        if conn is None:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=f"Failed to connect to backend: {server_name}",
                backend=server_name,
                retryable=True,
            )
        try:
            result = await conn.get_prompt(prompt_name, arguments)
        except Exception as e:
            return make_error_envelope(
                error_kind=OUTCOME_TRANSPORT_ERROR,
                error=str(e),
                backend=server_name,
                retryable=True,
            )
        if isinstance(result, dict):
            result.setdefault("qualified", qualified_name)
            result.setdefault("server", server_name)
        return result
