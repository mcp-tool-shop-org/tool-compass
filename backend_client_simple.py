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
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Any, Literal
from dataclasses import dataclass, field
from datetime import datetime

from config import CompassConfig, StdioBackend, load_config
from _version import __version__

logger = logging.getLogger(__name__)

# Timeout constants (in seconds)
CONNECTION_TIMEOUT = 10
TOOL_CALL_TIMEOUT = 15
KEEPALIVE_INTERVAL = 30  # Reserved — not wired today; see BR-A-008 / BR-B-015
MAX_RETRIES = 2

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


def make_error_envelope(
    *,
    error_kind: Outcome,
    error: str,
    backend: Optional[str] = None,
    code: Optional[int] = None,
    data: Optional[Any] = None,
    retryable: Optional[bool] = None,
    content: Optional[List[Any]] = None,
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
    return envelope


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
                    # Notification or malformed. Ignore — we don't route those
                    # to the caller, but log at debug so they're not invisible.
                    logger.debug(
                        f"Backend {self.name} sent id-less message "
                        f"(method={msg.get('method') if isinstance(msg, dict) else None})"
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
                }),
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

            # Get tools list
            tools_result = await asyncio.wait_for(
                self._send_request("tools/list", {}),
                timeout=timeout
            )

            if "result" in tools_result and "tools" in tools_result["result"]:
                self._tools = tools_result["result"]["tools"]

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

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
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
                request = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
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
            # requests in parallel.
            try:
                return await asyncio.wait_for(fut, timeout=PER_REQUEST_TIMEOUT)
            except asyncio.TimeoutError:
                if self._shutting_down:
                    raise BackendShuttingDownError(
                        f"Backend {self.name} is shutting down — "
                        "request cancelled"
                    )
                raise asyncio.TimeoutError(
                    f"Backend {self.name} did not respond within "
                    f"{PER_REQUEST_TIMEOUT}s"
                )
        finally:
            # Whether we succeeded or timed out, don't leak an entry.
            if request_id is not None:
                self._pending.pop(request_id, None)
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

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
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
            })

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
                return {
                    "success": True,
                    "result": "\n".join(text_parts) if text_parts else "Tool executed successfully",
                    "content": content_list if isinstance(content_list, list) else [],
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
        except asyncio.TimeoutError:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(
                latency_ms=latency_ms, outcome=OUTCOME_TIMEOUT
            )
            raise
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
        """
        lock = self._ensure_lock()

        async with lock:
            # Check if already connected (cheap registry read).
            if name in self._backends and self._backends[name].is_connected:
                return True

            backend = self.config.backends.get(name)
            if not backend:
                logger.error(f"Unknown backend: {name}")
                return False

            if not isinstance(backend, StdioBackend):
                logger.error(f"Unsupported backend type for {name}")
                return False

            # Pop the old broken connection out of the registry under lock
            # so concurrent callers see "not connected" immediately, but
            # actually disconnect / connect outside the lock.
            old_conn = self._backends.pop(name, None)
            # Remove any tool-index entries that pointed at this backend so
            # the index is consistent during the reconnect window.
            stale_keys = [
                k for k, v in self._tool_index.items() if v == name
            ]
            for k in stale_keys:
                self._tool_index.pop(k, None)

        # Async work outside the manager lock.
        if old_conn is not None:
            try:
                await old_conn.disconnect()
            except Exception as e:
                logger.debug(f"Old-connection disconnect for {name}: {e}")

        conn = SimpleBackendConnection(name, backend)
        connected = False
        for attempt in range(MAX_RETRIES + 1):
            success = await conn.connect(timeout=timeout)
            if success:
                connected = True
                break
            if attempt < MAX_RETRIES:
                logger.warning(
                    f"Retry {attempt + 1}/{MAX_RETRIES} for backend {name}"
                )
                await asyncio.sleep(0.5)

        if not connected:
            return False

        # Swap the new connection back into the registry under the lock.
        async with lock:
            self._backends[name] = conn
            for tool in conn.get_tools():
                self._tool_index[tool.qualified_name] = name
        return True

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
        timeout: Optional[float] = None
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
        """
        timeout = timeout or TOOL_CALL_TIMEOUT

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

        # Ensure connected (with automatic reconnection)
        if not await self.ensure_connected(server_name):
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=f"Failed to connect to backend: {server_name}",
                backend=server_name,
                retryable=True,
            )

        conn = self._backends.get(server_name)
        if not conn:
            return make_error_envelope(
                error_kind=OUTCOME_BACKEND_UNAVAILABLE,
                error=f"Backend not available: {server_name}",
                backend=server_name,
                retryable=True,
            )

        try:
            return await asyncio.wait_for(
                conn.call_tool(tool_name, arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Tool execution timed out after {timeout}s: {qualified_name}"
            )
            # BR-B-009: record the timeout in connection stats so
            # success_rate reflects it. (call_tool may have already recorded
            # if its inner per-request deadline tripped first; recording
            # twice is harmless under the new taxonomy.)
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
        except (BrokenPipeError, ConnectionResetError) as transport_err:
            # BR-A-005: transport errors are the ONLY case we retry. The
            # backend's pipe broke — reconnect and try once more.
            logger.error(
                f"Transport error executing {qualified_name}: {transport_err}"
            )
            logger.info(f"Attempting reconnect to {server_name}...")
            if await self.connect_backend(server_name):
                retry_conn = self._backends.get(server_name)
                if retry_conn is not None:
                    try:
                        return await asyncio.wait_for(
                            retry_conn.call_tool(tool_name, arguments),
                            timeout=timeout,
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
                        return make_error_envelope(
                            error_kind=OUTCOME_TRANSPORT_ERROR,
                            error=f"Retry failed: {retry_error}",
                            backend=server_name,
                            retryable=False,
                        )
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

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics for all backends.

        BR-B-004: surfaces per-outcome counters and the inflight peak so
        the operator can see backend health distinct from tool-error rate.
        """
        connected = []
        stats_by_backend = {}

        for name, conn in self._backends.items():
            if conn.is_connected:
                connected.append(name)
                stats_by_backend[name] = {
                    "tools": len(conn.get_tools()),
                    "total_calls": conn.stats.total_calls,
                    "failed_calls": conn.stats.failed_calls,
                    "avg_latency_ms": round(conn.stats.avg_latency_ms, 2),
                    "connected_at": (
                        conn.stats.connected_at.isoformat()
                        if conn.stats.connected_at else None
                    ),
                    "last_used": (
                        conn.stats.last_used.isoformat()
                        if conn.stats.last_used else None
                    ),
                    "outcomes": dict(conn.stats.outcomes),
                    "inflight_count": conn.stats.inflight_count,
                    "inflight_peak": conn.stats.inflight_peak,
                    "inflight_cap": MAX_INFLIGHT_REQUESTS_PER_BACKEND,
                    "abandoned_pids": list(conn._abandoned_pids),
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
                }
                if name in active_results:
                    entry["probe"] = active_results[name]
                    if not active_results[name].get("ok"):
                        entry["status"] = "degraded"
                health[name] = entry
            else:
                health[name] = {"status": "disconnected"}
        return health
