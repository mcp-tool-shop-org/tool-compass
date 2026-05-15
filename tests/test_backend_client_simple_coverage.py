"""
Coverage-focused tests for backend_client_simple.py.

Targets the wave-7 hardening code paths that pre-existing tests do not exercise:

- Connection lifecycle: connect / initialize / tools-list / disconnect /
  re-disconnect / cleanup of pipe handles + read tasks.
- Read loop multiplexing, EOF handling, JSON-decode tolerance, oversize lines.
- Stderr reader path including LimitOverrunError (BR-A-002).
- _send_request / _send_notification shutdown re-checks (BR-A-003).
- BackendOverloadedError when inflight semaphore is saturated (BR-B-006).
- KILL_WAIT_TIMEOUT bounded post-kill wait and abandoned PID tracking
  (BR-B-008).
- Active health probe (BR-B-007) and health_check active vs passive modes.
- call_tool envelope shapes: success / protocol_error / tool_error /
  invalid response (no result, no error) / BackendShuttingDownError /
  BackendOverloadedError / BackendNotConnectedError / Timeout /
  BrokenPipeError / general Exception.
- execute_tool retry filter (BR-A-005): only transport errors retry;
  protocol/tool/timeout/shutdown raise immediately.
- Manager: connect_backend retries, stale tool-index clearing during reconnect,
  disconnect_all snapshot-then-await-outside-lock semantics, get_stats and
  health_check output shapes.

The mock subprocess uses an asyncio.Queue for stdout, matching the
GW-FT-001 pattern in tests/test_features_v2_2_0.py.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, Mock, patch

import pytest

from backend_client_simple import (
    SimpleBackendConnection,
    SimpleBackendManager,
    BackendNotConnectedError,
    BackendOverloadedError,
    BackendProtocolError,
    BackendShuttingDownError,
    ToolInfo,
    OUTCOME_BACKEND_UNAVAILABLE,
    OUTCOME_PROTOCOL_ERROR,
    OUTCOME_SHUTDOWN_CANCELLED,
    OUTCOME_SUCCESS,
    OUTCOME_TIMEOUT,
    OUTCOME_TOOL_ERROR,
    OUTCOME_TRANSPORT_ERROR,
    MAX_INFLIGHT_REQUESTS_PER_BACKEND,
    KILL_WAIT_TIMEOUT,
    HEALTH_PROBE_TIMEOUT,
)
from config import CompassConfig, StdioBackend


# =============================================================================
# Helpers — fake subprocess that uses an asyncio.Queue for stdout responses.
# =============================================================================


class FakeStream:
    """Stand-in for an asyncio StreamReader.

    Supports:
    - ``readline`` that pulls bytes from an asyncio.Queue.
    - ``feed_eof`` so cleanup can be invoked without raising.
    - Raising a pre-seeded exception once on next readline (for transport
      / oversize tests).
    """

    def __init__(self):
        self.queue: "asyncio.Queue[bytes]" = asyncio.Queue()
        self._raise_once: Optional[BaseException] = None
        self.fed_eof = False

    async def readline(self) -> bytes:
        if self._raise_once is not None:
            exc = self._raise_once
            self._raise_once = None
            raise exc
        return await self.queue.get()

    async def read(self, n: int = -1) -> bytes:
        # Used by _read_stderr when LimitOverrunError fires.
        return b"oversize payload preview"

    def feed_eof(self) -> None:
        self.fed_eof = True


class FakeProcess:
    """Stand-in for asyncio.subprocess.Process."""

    def __init__(
        self,
        *,
        pid: int = 12345,
        die_on_wait: bool = True,
        wait_delay: float = 0.0,
    ):
        self.pid = pid
        self.returncode: Optional[int] = None
        self._die_on_wait = die_on_wait
        self._wait_delay = wait_delay

        self.stdout = FakeStream()
        self.stderr = FakeStream()

        self.stdin = Mock()
        self.stdin.write = Mock()
        self.stdin.drain = AsyncMock()
        self.stdin.close = Mock()
        self.stdin.wait_closed = AsyncMock()

        self.terminate = Mock(side_effect=self._terminate)
        self.kill = Mock(side_effect=self._kill)
        # _transport so the cleanup branch (BR-B-003 transport.close) runs.
        self._transport = Mock()

        self.written_lines: List[bytes] = []

        def _write(data: bytes) -> None:
            self.written_lines.append(data)

        self.stdin.write.side_effect = _write

    def _terminate(self) -> None:
        # Soft "graceful" path — flip returncode so wait() returns.
        if self._die_on_wait:
            self.returncode = 0

    def _kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        if self._wait_delay > 0:
            await asyncio.sleep(self._wait_delay)
        if self.returncode is None:
            # Simulate slow-but-eventual exit.
            self.returncode = 0
        return self.returncode

    def get_last_request(self) -> Dict[str, Any]:
        """Decode the most recent JSON-RPC frame written to stdin."""
        assert self.written_lines, "stdin.write was never called"
        line = self.written_lines[-1]
        return json.loads(line.decode("utf-8").rstrip("\n"))

    def get_request_id(self, method: str) -> Optional[int]:
        """Find the JSON-RPC id of the most recent request for *method*."""
        for raw in reversed(self.written_lines):
            try:
                msg = json.loads(raw.decode("utf-8").rstrip("\n"))
            except Exception:
                continue
            if msg.get("method") == method and "id" in msg:
                return msg["id"]
        return None

    def reply(self, msg: Dict[str, Any]) -> None:
        """Queue a JSON-RPC reply on stdout."""
        self.stdout.queue.put_nowait(
            (json.dumps(msg) + "\n").encode("utf-8")
        )


def make_backend() -> StdioBackend:
    return StdioBackend(command="python", args=["-c", "pass"], env={})


def make_connection() -> Tuple[SimpleBackendConnection, FakeProcess]:
    """Construct a SimpleBackendConnection wired to a fake subprocess.

    Mirrors what ``connect()`` would have done internally, minus the real
    subprocess + initialize handshake — so the connection is in a "post-
    handshake" state and ready for ``call_tool`` etc.
    """
    conn = SimpleBackendConnection("test", make_backend())
    proc = FakeProcess()
    conn._process = proc  # type: ignore[assignment]
    conn._connected = True
    conn._tools = [
        {"name": "echo", "description": "Echo a string", "inputSchema": {}}
    ]
    conn._ensure_async_primitives()
    return conn, proc


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def config_one_backend() -> CompassConfig:
    return CompassConfig(
        backends={"test": make_backend()},
        auto_sync=False,
    )


@pytest.fixture
def config_two_backends() -> CompassConfig:
    return CompassConfig(
        backends={
            "alpha": make_backend(),
            "beta": make_backend(),
        },
        auto_sync=False,
    )


# =============================================================================
# Read loop — JSON parsing, EOF, oversize, malformed, id-less messages
# =============================================================================


class TestReadLoop:
    """BR-A-002 / GW-FT-001 read-loop edge cases."""

    async def test_id_less_message_is_ignored_and_loop_continues(self):
        """A JSON-RPC notification (no id) must not crash the reader."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        # Server sends a notification (no id) — reader should log and skip.
        proc.reply({"jsonrpc": "2.0", "method": "server/notification", "params": {}})
        # Then a real response for id=1 that we'll subscribe to.
        fut = asyncio.get_event_loop().create_future()
        conn._pending[1] = fut
        proc.reply({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

        msg = await asyncio.wait_for(fut, timeout=2.0)
        assert msg["result"] == {"ok": True}

        # Loop is still alive; clean up.
        conn._shutting_down = True
        proc.stdout.queue.put_nowait(b"")  # EOF
        await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_malformed_json_line_logs_and_skips(self, caplog):
        """A non-JSON line is logged at WARNING; reader keeps running."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        proc.stdout.queue.put_nowait(b"not json at all\n")
        # Then a valid response so we can prove the loop is alive.
        fut = asyncio.get_event_loop().create_future()
        conn._pending[7] = fut
        proc.reply({"jsonrpc": "2.0", "id": 7, "result": "ok"})
        msg = await asyncio.wait_for(fut, timeout=2.0)
        assert msg["id"] == 7

        conn._shutting_down = True
        proc.stdout.queue.put_nowait(b"")
        await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_unknown_id_response_is_dropped(self, caplog):
        """A reply for an id we never sent is logged and dropped."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        # No pending future for id=99 — must not raise.
        proc.reply({"jsonrpc": "2.0", "id": 99, "result": "lost"})

        # Now a real, expected response.
        fut = asyncio.get_event_loop().create_future()
        conn._pending[1] = fut
        proc.reply({"jsonrpc": "2.0", "id": 1, "result": "hello"})
        msg = await asyncio.wait_for(fut, timeout=2.0)
        assert msg["result"] == "hello"

        conn._shutting_down = True
        proc.stdout.queue.put_nowait(b"")
        await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_eof_terminates_loop_and_fails_pending(self):
        """EOF on stdout fails all pending futures with BackendShuttingDownError."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        fut = asyncio.get_event_loop().create_future()
        conn._pending[5] = fut
        # EOF.
        proc.stdout.queue.put_nowait(b"")

        with pytest.raises(BackendShuttingDownError):
            await asyncio.wait_for(fut, timeout=2.0)
        # Reader has exited.
        await asyncio.wait_for(conn._read_task, timeout=2.0)
        assert conn._read_task.done()

    async def test_oversize_line_triggers_limit_overrun_path(self):
        """BR-A-002 read path: asyncio.LimitOverrunError aborts the loop
        cleanly and fails pending futures with an oversize-line RuntimeError.

        The LimitOverrunError branch fails pending futures with a structured
        ``RuntimeError`` BEFORE the ``finally`` block runs — so callers see the
        oversize-line message, which is the most actionable signal for the
        operator. The finally clean-up only resolves any future still pending.
        """
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        fut = asyncio.get_event_loop().create_future()
        conn._pending[3] = fut
        # Inject an oversize-line failure on the next readline.
        proc.stdout._raise_once = asyncio.LimitOverrunError("too big", 1)

        with pytest.raises(RuntimeError, match="oversize line"):
            await asyncio.wait_for(fut, timeout=2.0)
        await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_broken_pipe_in_readline_terminates_loop(self):
        """BrokenPipeError during read aborts the loop without crashing."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        fut = asyncio.get_event_loop().create_future()
        conn._pending[1] = fut
        proc.stdout._raise_once = BrokenPipeError("pipe gone")

        with pytest.raises(BackendShuttingDownError):
            await asyncio.wait_for(fut, timeout=2.0)
        await asyncio.wait_for(conn._read_task, timeout=2.0)


# =============================================================================
# _send_request shutdown re-check + inflight semaphore (BR-A-003 / BR-B-006)
# =============================================================================


class TestSendRequestGuards:
    async def test_request_raises_when_shutting_down(self):
        """BR-A-003: short-circuit when shutdown flag is set."""
        conn, _ = make_connection()
        conn._shutting_down = True
        with pytest.raises(BackendShuttingDownError):
            await conn._send_request("ping", {})

    async def test_request_raises_when_not_connected_missing_pipes(self):
        conn = SimpleBackendConnection("test", make_backend())
        conn._ensure_async_primitives()
        conn._process = None  # no subprocess
        with pytest.raises(BackendNotConnectedError):
            await conn._send_request("ping", {})

    async def test_request_raises_when_process_already_exited(self):
        conn, proc = make_connection()
        proc.returncode = 1  # process died
        with pytest.raises(BackendNotConnectedError):
            await conn._send_request("ping", {})

    async def test_overloaded_when_inflight_sem_saturated(self):
        """BR-B-006: cap reached -> fail fast with BackendOverloadedError."""
        conn, _ = make_connection()
        # Acquire all permits so the semaphore is "locked".
        assert conn._inflight_sem is not None
        for _ in range(MAX_INFLIGHT_REQUESTS_PER_BACKEND):
            await conn._inflight_sem.acquire()
        with pytest.raises(BackendOverloadedError) as exc_info:
            await conn._send_request("ping", {})
        assert exc_info.value.cap == MAX_INFLIGHT_REQUESTS_PER_BACKEND
        # Clean up.
        for _ in range(MAX_INFLIGHT_REQUESTS_PER_BACKEND):
            conn._inflight_sem.release()

    async def test_request_writes_then_resolves_on_reply(self):
        """Happy path: write request, reader resolves future, frame appears on the wire."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply_when_ready():
            # Wait a turn for the writer to register its pending future.
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply({"jsonrpc": "2.0", "id": rid, "result": {"ok": True}})

        replier = asyncio.create_task(reply_when_ready())
        try:
            result = await conn._send_request("ping", {"k": "v"})
            assert result["result"] == {"ok": True}
            # Verify the wire frame.
            sent = proc.get_last_request()
            assert sent["method"] == "ping"
            assert sent["params"] == {"k": "v"}
            assert sent["jsonrpc"] == "2.0"
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_request_broken_pipe_during_drain_surfaces(self):
        """Write side failure cleans up the pending entry."""
        conn, proc = make_connection()
        proc.stdin.drain = AsyncMock(side_effect=BrokenPipeError("dead"))

        with pytest.raises(BrokenPipeError):
            await conn._send_request("ping", {})
        # No leak in the pending map.
        assert conn._pending == {}

    async def test_request_broken_pipe_during_shutdown_translates_error(self):
        """If pipe breaks AFTER shutdown was set, raise BackendShuttingDownError."""
        conn, proc = make_connection()

        # Make the drain fail, but flip the shutdown flag mid-flight so the
        # error translation branch runs.
        original_drain = proc.stdin.drain

        async def failing_drain():
            conn._shutting_down = True
            raise BrokenPipeError("pipe closed during shutdown")

        proc.stdin.drain = AsyncMock(side_effect=failing_drain)

        with pytest.raises(BackendShuttingDownError):
            await conn._send_request("ping", {})

    async def test_request_timeout_path_surfaces_asyncio_timeout(self):
        """When the read loop never replies, the per-request deadline trips."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        with patch(
            "backend_client_simple.PER_REQUEST_TIMEOUT", 0.05
        ):
            with pytest.raises(asyncio.TimeoutError):
                await conn._send_request("never_replied", {})

        conn._shutting_down = True
        proc.stdout.queue.put_nowait(b"")
        await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_request_timeout_during_shutdown_translates(self):
        """Timeout while _shutting_down=True translates to BackendShuttingDownError."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def trigger_shutdown_after_delay():
            await asyncio.sleep(0.02)
            conn._shutting_down = True

        flipper = asyncio.create_task(trigger_shutdown_after_delay())
        try:
            with patch("backend_client_simple.PER_REQUEST_TIMEOUT", 0.05):
                with pytest.raises(BackendShuttingDownError):
                    await conn._send_request("hang", {})
        finally:
            flipper.cancel()
            try:
                await flipper
            except asyncio.CancelledError:
                pass
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)


# =============================================================================
# _send_notification (BR-A-003)
# =============================================================================


class TestSendNotification:
    async def test_notification_succeeds(self):
        conn, proc = make_connection()
        await conn._send_notification("notifications/initialized", {"hello": 1})
        msg = proc.get_last_request()
        assert msg["method"] == "notifications/initialized"
        assert msg["params"] == {"hello": 1}
        assert "id" not in msg  # notifications have no id

    async def test_notification_without_params(self):
        conn, proc = make_connection()
        await conn._send_notification("ping")
        msg = proc.get_last_request()
        assert msg["method"] == "ping"
        assert "params" not in msg

    async def test_notification_raises_when_shutting_down(self):
        conn, _ = make_connection()
        conn._shutting_down = True
        with pytest.raises(BackendShuttingDownError):
            await conn._send_notification("nope")

    async def test_notification_raises_when_no_pipes(self):
        conn = SimpleBackendConnection("test", make_backend())
        conn._ensure_async_primitives()
        conn._process = None
        with pytest.raises(BackendNotConnectedError):
            await conn._send_notification("nope")

    async def test_notification_translates_broken_pipe_to_shutdown(self):
        conn, proc = make_connection()

        async def failing_drain():
            conn._shutting_down = True
            raise BrokenPipeError("dead")

        proc.stdin.drain = AsyncMock(side_effect=failing_drain)
        with pytest.raises(BackendShuttingDownError):
            await conn._send_notification("nope")


# =============================================================================
# call_tool: every envelope shape (BR-B-001 / BR-B-012 / BR-A-004 / BR-A-005)
# =============================================================================


class TestCallToolEnvelopes:
    async def test_call_tool_raises_when_not_connected(self):
        conn, _ = make_connection()
        conn._connected = False
        with pytest.raises(BackendNotConnectedError):
            await conn.call_tool("echo", {"text": "hi"})

    async def test_success_envelope_extracts_text(self):
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply_with(result):
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply({"jsonrpc": "2.0", "id": rid, "result": result})

        async def driver():
            replier = asyncio.create_task(
                reply_with({"content": [{"type": "text", "text": "hello"}]})
            )
            try:
                env = await conn.call_tool("echo", {"text": "hi"})
                assert env["success"] is True
                assert env["result"] == "hello"
                assert env["content"][0]["text"] == "hello"
                # Outcome was recorded as success.
                assert conn.stats.outcomes[OUTCOME_SUCCESS] == 1
                assert conn.stats.failed_calls == 0
            finally:
                replier.cancel()

        try:
            await driver()
        finally:
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_protocol_error_envelope_carries_code_and_data(self):
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {
                        "code": -32601,
                        "message": "Method not found",
                        "data": {"detail": "bogus"},
                    },
                }
            )

        replier = asyncio.create_task(reply())
        try:
            env = await conn.call_tool("echo", {})
            assert env["success"] is False
            assert env["error_kind"] == OUTCOME_PROTOCOL_ERROR
            assert env["code"] == -32601
            assert env["data"] == {"detail": "bogus"}
            assert env["retryable"] is False
            assert conn.stats.outcomes[OUTCOME_PROTOCOL_ERROR] == 1
            assert conn.stats.failed_calls == 1
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_protocol_error_with_non_dict_error_payload(self):
        """If the error field is a bare string, code/data come back None."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply({"jsonrpc": "2.0", "id": rid, "error": "raw string error"})

        replier = asyncio.create_task(reply())
        try:
            env = await conn.call_tool("echo", {})
            assert env["error_kind"] == OUTCOME_PROTOCOL_ERROR
            assert env["error"] == "raw string error"
            assert "code" not in env  # code was None, omitted from envelope
            assert "data" not in env
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_tool_error_isError_preserves_content(self):
        """MCP isError: count as tool_error, NOT a backend failure."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "isError": True,
                        "content": [
                            {"type": "text", "text": "permission denied"}
                        ],
                    },
                }
            )

        replier = asyncio.create_task(reply())
        try:
            env = await conn.call_tool("echo", {})
            assert env["success"] is False
            assert env["error_kind"] == OUTCOME_TOOL_ERROR
            assert env["error"] == "permission denied"
            assert env["retryable"] is True
            assert env["content"][0]["text"] == "permission denied"
            # Tool error must NOT count as backend failure (BR-B-004).
            assert conn.stats.outcomes[OUTCOME_TOOL_ERROR] == 1
            assert conn.stats.failed_calls == 0
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_tool_error_with_empty_content_uses_fallback_text(self):
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {"isError": True, "content": []},
                }
            )

        replier = asyncio.create_task(reply())
        try:
            env = await conn.call_tool("echo", {})
            assert env["error"] == "Tool returned error"
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_success_with_string_and_non_dict_content_items(self):
        """Content items that are strings or non-dict objects are coerced via str()."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "content": [
                            {"type": "text", "text": "first"},
                            "raw_string",
                            123,
                        ]
                    },
                }
            )

        replier = asyncio.create_task(reply())
        try:
            env = await conn.call_tool("echo", {})
            assert env["success"] is True
            # Joined with newlines, all parts present.
            assert "first" in env["result"]
            assert "raw_string" in env["result"]
            assert "123" in env["result"]
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_success_with_no_content_returns_default_message(self):
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply({"jsonrpc": "2.0", "id": rid, "result": {"content": []}})

        replier = asyncio.create_task(reply())
        try:
            env = await conn.call_tool("echo", {})
            assert env["success"] is True
            assert env["result"] == "Tool executed successfully"
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_invalid_response_no_result_no_error(self):
        """A response with neither result nor error -> protocol_error envelope."""
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply({"jsonrpc": "2.0", "id": rid})  # neither result nor error

        replier = asyncio.create_task(reply())
        try:
            env = await conn.call_tool("echo", {})
            assert env["error_kind"] == OUTCOME_PROTOCOL_ERROR
            assert "Invalid response" in env["error"]
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_call_tool_shutdown_cancelled_bucket(self):
        """BR-A-004: BackendShuttingDownError is re-raised AND records
        shutdown_cancelled outcome (not a real failure)."""
        conn, _ = make_connection()
        conn._shutting_down = True

        with pytest.raises(BackendShuttingDownError):
            await conn.call_tool("echo", {})

        # Stats: shutdown_cancelled bucket, NOT failed_calls.
        assert conn.stats.outcomes[OUTCOME_SHUTDOWN_CANCELLED] == 1
        assert conn.stats.failed_calls == 0

    async def test_call_tool_overloaded_records_backend_unavailable(self):
        """BackendOverloadedError -> records backend_unavailable outcome."""
        conn, _ = make_connection()
        # Saturate the inflight semaphore.
        assert conn._inflight_sem is not None
        for _ in range(MAX_INFLIGHT_REQUESTS_PER_BACKEND):
            await conn._inflight_sem.acquire()

        with pytest.raises(BackendOverloadedError):
            await conn.call_tool("echo", {})
        assert conn.stats.outcomes[OUTCOME_BACKEND_UNAVAILABLE] == 1
        assert conn.stats.failed_calls == 1

        # Release for cleanliness.
        for _ in range(MAX_INFLIGHT_REQUESTS_PER_BACKEND):
            conn._inflight_sem.release()

    async def test_call_tool_not_connected_records_backend_unavailable(self):
        conn, proc = make_connection()
        # Connected at the moment call_tool runs the precondition check,
        # but the underlying _send_request will raise BackendNotConnectedError
        # because we nuke the process.
        proc.stdin = None  # forces BackendNotConnectedError in _send_request
        with pytest.raises(BackendNotConnectedError):
            await conn.call_tool("echo", {})
        assert conn.stats.outcomes[OUTCOME_BACKEND_UNAVAILABLE] == 1

    async def test_call_tool_broken_pipe_records_transport_error(self):
        conn, proc = make_connection()
        proc.stdin.drain = AsyncMock(side_effect=BrokenPipeError("pipe gone"))

        with pytest.raises(BrokenPipeError):
            await conn.call_tool("echo", {})
        assert conn.stats.outcomes[OUTCOME_TRANSPORT_ERROR] == 1
        assert conn.stats.failed_calls == 1

    async def test_call_tool_generic_exception_records_transport_error(self):
        conn, proc = make_connection()

        # Force a generic Exception during write so the broad except path runs.
        proc.stdin.write = Mock(side_effect=RuntimeError("disk full mid-write"))

        with pytest.raises(RuntimeError):
            await conn.call_tool("echo", {})
        # Default: transport_error bucket.
        assert conn.stats.outcomes[OUTCOME_TRANSPORT_ERROR] == 1

    async def test_call_tool_timeout_records_timeout_outcome(self):
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        try:
            with patch("backend_client_simple.PER_REQUEST_TIMEOUT", 0.05):
                with pytest.raises(asyncio.TimeoutError):
                    await conn.call_tool("echo", {})
            assert conn.stats.outcomes[OUTCOME_TIMEOUT] == 1
            assert conn.stats.failed_calls == 1
        finally:
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)


# =============================================================================
# Active probe (BR-B-007)
# =============================================================================


class TestActiveProbe:
    async def test_probe_when_not_connected_returns_unavailable(self):
        conn = SimpleBackendConnection("test", make_backend())
        result = await conn.active_probe()
        assert result["ok"] is False
        assert result["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE

    async def test_probe_when_process_died(self):
        conn, proc = make_connection()
        proc.returncode = 1  # died
        result = await conn.active_probe()
        assert result["ok"] is False
        assert result["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE

    async def test_probe_success_returns_latency(self):
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        async def reply():
            for _ in range(50):
                await asyncio.sleep(0)
                if conn._pending:
                    break
            rid = next(iter(conn._pending.keys()))
            proc.reply(
                {"jsonrpc": "2.0", "id": rid, "result": {"tools": []}}
            )

        replier = asyncio.create_task(reply())
        try:
            result = await conn.active_probe(timeout=2.0)
            assert result["ok"] is True
            assert "latency_ms" in result
            # Stats unaffected — probes don't count.
            assert conn.stats.total_calls == 0
        finally:
            replier.cancel()
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_probe_timeout_returns_timeout_kind(self):
        conn, proc = make_connection()
        conn._read_task = asyncio.create_task(conn._read_loop())

        try:
            result = await conn.active_probe(timeout=0.05)
            assert result["ok"] is False
            assert result["error_kind"] == OUTCOME_TIMEOUT
            assert "latency_ms" in result
        finally:
            conn._shutting_down = True
            proc.stdout.queue.put_nowait(b"")
            await asyncio.wait_for(conn._read_task, timeout=2.0)

    async def test_probe_overloaded_returns_unavailable(self):
        conn, _ = make_connection()
        # Saturate the semaphore so _send_request hits the cap branch.
        assert conn._inflight_sem is not None
        for _ in range(MAX_INFLIGHT_REQUESTS_PER_BACKEND):
            await conn._inflight_sem.acquire()
        result = await conn.active_probe()
        assert result["ok"] is False
        assert result["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE
        for _ in range(MAX_INFLIGHT_REQUESTS_PER_BACKEND):
            conn._inflight_sem.release()

    async def test_probe_shutdown_returns_shutdown_kind(self):
        conn, _ = make_connection()
        conn._shutting_down = True
        result = await conn.active_probe()
        assert result["ok"] is False
        assert result["error_kind"] == OUTCOME_SHUTDOWN_CANCELLED


# =============================================================================
# get_tools + is_connected
# =============================================================================


class TestGetToolsAndConnected:
    def test_get_tools_returns_normalized_tool_info(self):
        conn, _ = make_connection()
        # connection seeded with one echo tool.
        tools = conn.get_tools()
        assert len(tools) == 1
        t = tools[0]
        assert isinstance(t, ToolInfo)
        assert t.name == "echo"
        assert t.qualified_name == "test:echo"
        assert t.server == "test"

    def test_is_connected_true(self):
        conn, _ = make_connection()
        assert conn.is_connected is True

    def test_is_connected_flips_when_process_dies(self):
        conn, proc = make_connection()
        proc.returncode = 99  # process is dead
        assert conn.is_connected is False
        # And the internal flag must be flipped.
        assert conn._connected is False

    def test_is_connected_false_when_not_connected_flag(self):
        conn, _ = make_connection()
        conn._connected = False
        assert conn.is_connected is False

    def test_stats_property_exposes_connection_stats(self):
        conn, _ = make_connection()
        assert conn.stats is conn._stats


# =============================================================================
# disconnect + cleanup (BR-B-003, BR-B-008)
# =============================================================================


class TestDisconnect:
    async def test_disconnect_clears_state_and_calls_terminate(self):
        conn, proc = make_connection()
        # Set up a pending future so we can verify it gets cancelled.
        fut = asyncio.get_event_loop().create_future()
        conn._pending[1] = fut

        await conn.disconnect()

        # Pending future was failed.
        assert fut.done()
        with pytest.raises(BackendShuttingDownError):
            fut.result()
        assert conn._connected is False
        assert conn._process is None
        assert conn._tools == []
        # terminate was called.
        proc.terminate.assert_called_once()
        # transport close was attempted.
        proc._transport.close.assert_called_once()
        # feed_eof called on stdout + stderr.
        assert proc.stdout.fed_eof is True
        assert proc.stderr.fed_eof is True

    async def test_disconnect_idempotent_second_call_is_noop(self):
        conn, _ = make_connection()
        await conn.disconnect()
        # Second disconnect must not crash — no process to terminate.
        await conn.disconnect()
        assert conn._process is None

    async def test_disconnect_kill_branch_when_terminate_does_not_drop_proc(self):
        """If wait() after terminate times out, we hit kill + post-kill wait."""
        conn, proc = make_connection()

        # Make wait() block forever — disconnect's 2s wait_for will time out
        # and then we kill the process.
        async def hang_forever():
            await asyncio.sleep(60)
            return 0

        proc._terminate = lambda: None  # don't auto-die on terminate
        proc.terminate = Mock(side_effect=proc._terminate)
        proc.wait = hang_forever

        # The disconnect path bounds wait by 2s + KILL_WAIT_TIMEOUT.
        # Patch the timeouts to keep the test fast.
        with patch("backend_client_simple.KILL_WAIT_TIMEOUT", 0.1):
            await asyncio.wait_for(conn.disconnect(), timeout=5.0)

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        # PID was tracked as abandoned (post-kill wait timed out).
        assert proc.pid in conn._abandoned_pids


# =============================================================================
# _read_stderr (BR-A-002)
# =============================================================================


class TestReadStderr:
    async def test_stderr_emits_lines_then_eof(self):
        conn, proc = make_connection()
        task = asyncio.create_task(conn._read_stderr())

        proc.stderr.queue.put_nowait(b"backend warning\n")
        proc.stderr.queue.put_nowait(b"")  # EOF terminates the reader

        await asyncio.wait_for(task, timeout=2.0)

    async def test_stderr_limit_overrun_truncates_and_continues(self):
        conn, proc = make_connection()

        # Raise LimitOverrunError on first readline, then EOF.
        proc.stderr._raise_once = asyncio.LimitOverrunError("too big", 1)
        task = asyncio.create_task(conn._read_stderr())
        proc.stderr.queue.put_nowait(b"")  # EOF after the oversize-line handling
        await asyncio.wait_for(task, timeout=2.0)

    async def test_stderr_broken_pipe_terminates_loop(self):
        conn, proc = make_connection()
        proc.stderr._raise_once = BrokenPipeError("dead")
        task = asyncio.create_task(conn._read_stderr())
        await asyncio.wait_for(task, timeout=2.0)

    async def test_stderr_returns_immediately_when_no_process(self):
        conn = SimpleBackendConnection("test", make_backend())
        conn._process = None  # type: ignore[assignment]
        # Must not raise.
        await conn._read_stderr()


# =============================================================================
# connect() lifecycle — initialize handshake + tools/list + error paths
# =============================================================================


class TestConnectLifecycle:
    """Drive the full connect() handshake by mocking create_subprocess_exec."""

    @staticmethod
    def _patch_subprocess(proc: FakeProcess):
        """Patch ``asyncio.create_subprocess_exec`` to return ``proc`` once."""
        async def fake_create(*_args, **_kwargs):
            return proc

        return patch(
            "backend_client_simple.asyncio.create_subprocess_exec",
            side_effect=fake_create,
        )

    async def test_connect_happy_path_returns_true_and_populates_tools(self):
        conn = SimpleBackendConnection("test", make_backend())
        proc = FakeProcess()

        # Bridge that watches stdin.write for outgoing JSON-RPC frames and
        # auto-replies based on the method. This keeps timing race-free
        # because the reply is queued AFTER the request was written.
        original_write = proc.stdin.write

        def auto_reply(data: bytes) -> None:
            original_write(data)
            try:
                msg = json.loads(data.decode("utf-8").rstrip("\n"))
            except Exception:
                return
            method = msg.get("method")
            mid = msg.get("id")
            if mid is None:
                # notifications get no reply
                return
            if method == "initialize":
                proc.reply(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {"protocolVersion": "2024-11-05"},
                    }
                )
            elif method == "tools/list":
                proc.reply(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "tools": [
                                {
                                    "name": "ping",
                                    "description": "Ping",
                                    "inputSchema": {},
                                }
                            ]
                        },
                    }
                )

        proc.stdin.write = Mock(side_effect=auto_reply)

        with self._patch_subprocess(proc):
            ok = await conn.connect(timeout=5.0)

        try:
            assert ok is True
            assert conn._connected is True
            # Tools list was parsed.
            assert len(conn._tools) == 1
            assert conn._tools[0]["name"] == "ping"
            # Stats were stamped.
            assert conn.stats.connected_at is not None
        finally:
            await conn.disconnect()

    async def test_connect_subprocess_dies_immediately_returns_false(self):
        conn = SimpleBackendConnection("test", make_backend())
        proc = FakeProcess()
        # Process dies before initialize.
        proc.returncode = 2

        with self._patch_subprocess(proc):
            # The connect path sleeps 0.2s then checks returncode.
            ok = await conn.connect(timeout=2.0)
        assert ok is False
        assert conn._connected is False

    async def test_connect_initialize_protocol_error_returns_false(self):
        conn = SimpleBackendConnection("test", make_backend())
        proc = FakeProcess()

        original_write = proc.stdin.write

        def auto_reply(data: bytes) -> None:
            original_write(data)
            try:
                msg = json.loads(data.decode("utf-8").rstrip("\n"))
            except Exception:
                return
            if msg.get("method") == "initialize":
                proc.reply(
                    {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "error": {
                            "code": -32603,
                            "message": "Internal error",
                            "data": {"detail": "oops"},
                        },
                    }
                )

        proc.stdin.write = Mock(side_effect=auto_reply)
        with self._patch_subprocess(proc):
            ok = await conn.connect(timeout=5.0)
        assert ok is False
        assert conn._connected is False

    async def test_connect_initialize_protocol_error_non_dict_payload(self):
        conn = SimpleBackendConnection("test", make_backend())
        proc = FakeProcess()

        original_write = proc.stdin.write

        def auto_reply(data: bytes) -> None:
            original_write(data)
            try:
                msg = json.loads(data.decode("utf-8").rstrip("\n"))
            except Exception:
                return
            if msg.get("method") == "initialize":
                proc.reply(
                    {"jsonrpc": "2.0", "id": msg["id"], "error": "raw string"}
                )

        proc.stdin.write = Mock(side_effect=auto_reply)
        with self._patch_subprocess(proc):
            ok = await conn.connect(timeout=5.0)
        assert ok is False

    async def test_connect_initialize_timeout_returns_false(self):
        conn = SimpleBackendConnection("test", make_backend())
        proc = FakeProcess()

        with self._patch_subprocess(proc):
            # No replies are fed — initialize will time out.
            ok = await conn.connect(timeout=0.5)
        assert ok is False
        assert conn._connected is False

    async def test_connect_already_connected_short_circuits(self):
        conn, _ = make_connection()
        # Already connected — connect() must return True without spawning.
        with patch(
            "backend_client_simple.asyncio.create_subprocess_exec"
        ) as spawn:
            ok = await conn.connect()
            assert ok is True
            spawn.assert_not_called()

    async def test_connect_env_inheritance_none_starts_empty(self):
        """BR-A-006: env_inheritance=none yields an empty base env."""
        backend = StdioBackend(
            command="python",
            args=["-c", "pass"],
            env={"__env_inheritance__": "none", "MY_VAR": "1"},
        )
        conn = SimpleBackendConnection("test", backend)
        proc = FakeProcess()

        captured_env: Dict[str, Optional[Dict[str, str]]] = {"env": None}

        async def fake_create(*args, **kwargs):
            captured_env["env"] = kwargs.get("env")
            return proc

        original_write = proc.stdin.write

        def auto_reply(data: bytes) -> None:
            original_write(data)
            try:
                msg = json.loads(data.decode("utf-8").rstrip("\n"))
            except Exception:
                return
            method = msg.get("method")
            mid = msg.get("id")
            if mid is None:
                return
            if method == "initialize":
                proc.reply({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "tools/list":
                proc.reply(
                    {"jsonrpc": "2.0", "id": mid, "result": {"tools": []}}
                )

        proc.stdin.write = Mock(side_effect=auto_reply)

        with patch(
            "backend_client_simple.asyncio.create_subprocess_exec",
            side_effect=fake_create,
        ):
            ok = await conn.connect(timeout=5.0)
        try:
            assert ok is True
            captured = captured_env["env"]
            assert captured is not None
            # Base env was empty (no PATH from os.environ). Only the backend's
            # explicit env vars + the always-added Python flags appear.
            assert captured.get("MY_VAR") == "1"
            assert captured.get("PYTHONIOENCODING") == "utf-8"
            # Critically: __env_inheritance__ was consumed, not passed on.
            assert "__env_inheritance__" not in captured
        finally:
            await conn.disconnect()


# =============================================================================
# SimpleBackendManager.connect_backend (BR-B-002 manager-lock scope)
# =============================================================================


class TestManagerConnectBackend:
    async def test_connect_returns_false_for_unknown_backend(self, config_one_backend):
        mgr = SimpleBackendManager(config_one_backend)
        assert await mgr.connect_backend("not_a_backend") is False

    async def test_connect_skips_when_already_connected(self, config_one_backend):
        mgr = SimpleBackendManager(config_one_backend)
        mock_conn = Mock()
        mock_conn.is_connected = True
        mgr._backends["test"] = mock_conn
        assert await mgr.connect_backend("test") is True

    async def test_connect_pops_stale_tool_index_during_reconnect(
        self, config_one_backend
    ):
        """BR-B-002: stale tool-index entries for the reconnecting backend must
        be cleared before the new connection registers."""
        mgr = SimpleBackendManager(config_one_backend)

        # Seed an old broken connection + stale tool-index entries.
        old_conn = Mock()
        old_conn.is_connected = False
        old_conn.disconnect = AsyncMock()
        mgr._backends["test"] = old_conn
        mgr._tool_index["test:stale1"] = "test"
        mgr._tool_index["test:stale2"] = "test"
        mgr._tool_index["other:keep"] = "other"

        # Patch SimpleBackendConnection to return a controllable mock that
        # "connects" successfully and exposes one new tool.
        new_conn = Mock()
        new_conn.connect = AsyncMock(return_value=True)
        new_conn.get_tools = Mock(
            return_value=[ToolInfo("fresh", "test:fresh", "Fresh tool", "test", {})]
        )

        with patch(
            "backend_client_simple.SimpleBackendConnection",
            return_value=new_conn,
        ):
            ok = await mgr.connect_backend("test")
        assert ok is True
        # Old conn disconnect was awaited OUTSIDE the lock.
        old_conn.disconnect.assert_awaited_once()
        # Stale entries are gone.
        assert "test:stale1" not in mgr._tool_index
        assert "test:stale2" not in mgr._tool_index
        # Unrelated entry preserved.
        assert mgr._tool_index["other:keep"] == "other"
        # New entry registered.
        assert mgr._tool_index["test:fresh"] == "test"

    async def test_connect_retries_then_fails(self, config_one_backend):
        """When connect returns False repeatedly, manager returns False."""
        mgr = SimpleBackendManager(config_one_backend)

        # The patched SimpleBackendConnection always fails.
        failing = Mock()
        failing.connect = AsyncMock(return_value=False)

        with patch(
            "backend_client_simple.SimpleBackendConnection", return_value=failing
        ):
            # Short retry sleep so test stays fast.
            with patch("backend_client_simple.asyncio.sleep", AsyncMock()):
                ok = await mgr.connect_backend("test")
        assert ok is False
        # MAX_RETRIES + 1 attempts.
        assert failing.connect.await_count == 3


class TestManagerDisconnectAll:
    async def test_disconnect_all_empty_registry_returns_clean_result(
        self, config_one_backend
    ):
        mgr = SimpleBackendManager(config_one_backend)
        result = await mgr.disconnect_all()
        assert result == {"disconnected": [], "laggards": [], "timed_out": False}

    async def test_disconnect_all_succeeds_for_all(self, config_two_backends):
        mgr = SimpleBackendManager(config_two_backends)
        for name in ("alpha", "beta"):
            mock_conn = Mock()
            mock_conn.disconnect = AsyncMock()
            mgr._backends[name] = mock_conn
            mgr._tool_index[f"{name}:t"] = name

        result = await mgr.disconnect_all()
        assert set(result["disconnected"]) == {"alpha", "beta"}
        assert result["laggards"] == []
        assert result["timed_out"] is False
        # Registry + index cleared under the lock.
        assert mgr._backends == {}
        assert mgr._tool_index == {}

    async def test_disconnect_all_records_laggard_on_exception(
        self, config_two_backends
    ):
        mgr = SimpleBackendManager(config_two_backends)
        alpha = Mock()
        alpha.disconnect = AsyncMock()
        beta = Mock()
        beta.disconnect = AsyncMock(side_effect=RuntimeError("boom"))
        mgr._backends["alpha"] = alpha
        mgr._backends["beta"] = beta

        result = await mgr.disconnect_all()
        assert "alpha" in result["disconnected"]
        assert any(l["name"] == "beta" for l in result["laggards"])

    async def test_disconnect_all_times_out_when_budget_exceeded(
        self, config_two_backends
    ):
        mgr = SimpleBackendManager(config_two_backends)

        async def slow_disconnect():
            await asyncio.sleep(5)

        for name in ("alpha", "beta"):
            mc = Mock()
            mc.disconnect = AsyncMock(side_effect=slow_disconnect)
            mgr._backends[name] = mc

        result = await mgr.disconnect_all(total_timeout=0.05)
        assert result["timed_out"] is True
        # Both names show up as laggards.
        names = [l["name"] for l in result["laggards"]]
        assert "alpha" in names
        assert "beta" in names


class TestManagerConnectAll:
    async def test_connect_all_returns_per_backend_results(self, config_two_backends):
        mgr = SimpleBackendManager(config_two_backends)
        mgr.connect_backend = AsyncMock(side_effect=[True, False])
        results = await mgr.connect_all()
        assert results == {"alpha": True, "beta": False}

    async def test_connect_all_records_exception_as_false(self, config_two_backends):
        mgr = SimpleBackendManager(config_two_backends)
        mgr.connect_backend = AsyncMock(
            side_effect=[True, RuntimeError("setup failed")]
        )
        results = await mgr.connect_all()
        assert results["alpha"] is True
        assert results["beta"] is False


# =============================================================================
# execute_tool retry filter (BR-A-005)
# =============================================================================


class TestExecuteTool:
    async def _make_manager_with_registered_conn(
        self, config: CompassConfig, mock_conn: Mock
    ) -> SimpleBackendManager:
        mgr = SimpleBackendManager(config)
        mock_conn.is_connected = True
        mgr._backends["test"] = mock_conn
        mgr._tool_index["test:echo"] = "test"
        return mgr

    async def test_execute_tool_unknown_qualified_name(self, config_one_backend):
        mgr = SimpleBackendManager(config_one_backend)
        env = await mgr.execute_tool("nonexistent_no_colon", {})
        assert env["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE
        assert "format" in env["error"].lower()

    async def test_execute_tool_unknown_backend_via_colon_returns_unavailable(
        self, config_one_backend
    ):
        mgr = SimpleBackendManager(config_one_backend)
        # The backend "unknown" isn't in config, so ensure_connected will fail.
        env = await mgr.execute_tool("unknown:tool", {})
        assert env["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE
        # Backend field present.
        assert env["backend"] == "unknown"

    async def test_execute_tool_success_via_tool_index(self, config_one_backend):
        mock_conn = Mock()
        mock_conn.call_tool = AsyncMock(
            return_value={"success": True, "result": "ok", "content": []}
        )
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        env = await mgr.execute_tool("test:echo", {"x": 1})
        assert env["success"] is True
        mock_conn.call_tool.assert_awaited_once_with("echo", {"x": 1})

    async def test_execute_tool_strips_backend_prefix_via_tool_index(
        self, config_one_backend
    ):
        """BR-A-018: tool-index match recovers tool name by stripping prefix."""
        mock_conn = Mock()
        mock_conn.call_tool = AsyncMock(
            return_value={"success": True, "result": "ok", "content": []}
        )
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        await mgr.execute_tool("test:echo", {})
        # Tool name part is "echo", not "test:echo".
        mock_conn.call_tool.assert_awaited_once_with("echo", {})

    async def test_execute_tool_timeout_returns_timeout_envelope(
        self, config_one_backend
    ):
        mock_conn = Mock()

        async def slow_call(*_args, **_kwargs):
            await asyncio.sleep(5)

        mock_conn.call_tool = AsyncMock(side_effect=slow_call)
        mock_conn.stats = Mock()
        mock_conn.stats.record_call = Mock()
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        env = await mgr.execute_tool("test:echo", {}, timeout=0.05)
        assert env["error_kind"] == OUTCOME_TIMEOUT
        assert env["retryable"] is True
        # BR-B-009: manager records the timeout in connection stats.
        mock_conn.stats.record_call.assert_called()

    async def test_execute_tool_shutdown_returns_shutdown_envelope(
        self, config_one_backend
    ):
        mock_conn = Mock()
        mock_conn.call_tool = AsyncMock(
            side_effect=BackendShuttingDownError("shutting down")
        )
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_SHUTDOWN_CANCELLED
        assert env["retryable"] is False

    async def test_execute_tool_overloaded_returns_unavailable_envelope(
        self, config_one_backend
    ):
        mock_conn = Mock()
        mock_conn.call_tool = AsyncMock(
            side_effect=BackendOverloadedError("test", 64)
        )
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE
        assert env["retryable"] is True

    async def test_execute_tool_not_connected_returns_unavailable_envelope(
        self, config_one_backend
    ):
        mock_conn = Mock()
        mock_conn.call_tool = AsyncMock(
            side_effect=BackendNotConnectedError("test", "pipes gone")
        )
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE
        assert env["retryable"] is True

    async def test_execute_tool_protocol_error_carries_code(
        self, config_one_backend
    ):
        mock_conn = Mock()
        mock_conn.call_tool = AsyncMock(
            side_effect=BackendProtocolError(-32601, "Method not found", {"x": 1})
        )
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_PROTOCOL_ERROR
        assert env["code"] == -32601
        assert env["data"] == {"x": 1}
        assert env["retryable"] is False

    async def test_execute_tool_transport_error_retries_once(
        self, config_one_backend
    ):
        """BR-A-005: transport errors are the ONLY retried path."""
        first = Mock()
        first.is_connected = True
        first.call_tool = AsyncMock(side_effect=BrokenPipeError("pipe broke"))

        second = Mock()
        second.is_connected = True
        second.call_tool = AsyncMock(
            return_value={"success": True, "result": "retry ok", "content": []}
        )

        mgr = SimpleBackendManager(config_one_backend)
        mgr._backends["test"] = first
        mgr._tool_index["test:echo"] = "test"

        # connect_backend is the manager-side reconnect — patch it to inject
        # the "second" connection.
        async def fake_reconnect(name, timeout=None):
            mgr._backends[name] = second
            return True

        mgr.connect_backend = AsyncMock(side_effect=fake_reconnect)

        env = await mgr.execute_tool("test:echo", {})
        assert env["success"] is True
        second.call_tool.assert_awaited_once()

    async def test_execute_tool_transport_error_retry_fails(
        self, config_one_backend
    ):
        mock_conn = Mock()
        mock_conn.is_connected = True
        mock_conn.call_tool = AsyncMock(side_effect=BrokenPipeError("pipe broke"))

        mgr = SimpleBackendManager(config_one_backend)
        mgr._backends["test"] = mock_conn
        mgr._tool_index["test:echo"] = "test"
        # No reconnect — connect_backend returns False.
        mgr.connect_backend = AsyncMock(return_value=False)

        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_TRANSPORT_ERROR
        assert env["retryable"] is False

    async def test_execute_tool_transport_error_retry_times_out(
        self, config_one_backend
    ):
        first = Mock()
        first.is_connected = True
        first.call_tool = AsyncMock(side_effect=BrokenPipeError("pipe"))

        second = Mock()
        second.is_connected = True

        async def slow_retry(*_args, **_kwargs):
            await asyncio.sleep(5)

        second.call_tool = AsyncMock(side_effect=slow_retry)
        second.stats = Mock()
        second.stats.record_call = Mock()

        mgr = SimpleBackendManager(config_one_backend)
        mgr._backends["test"] = first
        mgr._tool_index["test:echo"] = "test"

        async def fake_reconnect(name, timeout=None):
            mgr._backends[name] = second
            return True

        mgr.connect_backend = AsyncMock(side_effect=fake_reconnect)

        env = await mgr.execute_tool("test:echo", {}, timeout=0.05)
        assert env["error_kind"] == OUTCOME_TIMEOUT
        assert env["retryable"] is False

    async def test_execute_tool_transport_error_retry_raises_generic(
        self, config_one_backend
    ):
        first = Mock()
        first.is_connected = True
        first.call_tool = AsyncMock(side_effect=BrokenPipeError("pipe"))

        second = Mock()
        second.is_connected = True
        second.call_tool = AsyncMock(side_effect=RuntimeError("second failed"))

        mgr = SimpleBackendManager(config_one_backend)
        mgr._backends["test"] = first
        mgr._tool_index["test:echo"] = "test"

        async def fake_reconnect(name, timeout=None):
            mgr._backends[name] = second
            return True

        mgr.connect_backend = AsyncMock(side_effect=fake_reconnect)

        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_TRANSPORT_ERROR
        assert "second failed" in env["error"]

    async def test_execute_tool_generic_exception_returns_transport_error(
        self, config_one_backend
    ):
        mock_conn = Mock()
        mock_conn.call_tool = AsyncMock(
            side_effect=RuntimeError("something blew up")
        )
        mgr = await self._make_manager_with_registered_conn(
            config_one_backend, mock_conn
        )
        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_TRANSPORT_ERROR

    async def test_execute_tool_ensure_connected_false_returns_unavailable(
        self, config_one_backend
    ):
        """When ensure_connected fails, manager returns unavailable envelope."""
        mgr = SimpleBackendManager(config_one_backend)
        mgr.ensure_connected = AsyncMock(return_value=False)

        env = await mgr.execute_tool("test:echo", {})
        assert env["error_kind"] == OUTCOME_BACKEND_UNAVAILABLE
        assert env["retryable"] is True


# =============================================================================
# get_stats + health_check (BR-B-004, BR-B-007)
# =============================================================================


class TestStatsAndHealth:
    def test_get_stats_reflects_connected_backends(self, config_two_backends):
        mgr = SimpleBackendManager(config_two_backends)
        c1 = Mock()
        c1.is_connected = True
        c1.get_tools.return_value = [
            ToolInfo("t1", "alpha:t1", "", "alpha", {})
        ]
        c1.stats.total_calls = 5
        c1.stats.failed_calls = 1
        c1.stats.avg_latency_ms = 12.5
        c1.stats.connected_at = None
        c1.stats.last_used = None
        c1.stats.outcomes = {OUTCOME_SUCCESS: 4, OUTCOME_TIMEOUT: 1}
        c1.stats.inflight_count = 0
        c1.stats.inflight_peak = 2
        c1._abandoned_pids = []
        mgr._backends["alpha"] = c1

        stats = mgr.get_stats()
        assert "alpha" in stats["connected_backends"]
        # Untouched beta is configured but not connected -> NOT in connected list.
        assert "beta" in stats["configured_backends"]
        assert "beta" not in stats["connected_backends"]
        # Inflight peak surfaced.
        assert stats["stats"]["alpha"]["inflight_peak"] == 2
        assert stats["stats"]["alpha"]["inflight_cap"] == MAX_INFLIGHT_REQUESTS_PER_BACKEND

    async def test_health_check_passive_disconnected_marked(
        self, config_two_backends
    ):
        mgr = SimpleBackendManager(config_two_backends)
        c = Mock()
        c.is_connected = True
        c.get_tools.return_value = []
        c.stats.total_calls = 0
        c.stats.failed_calls = 0
        c.stats.outcomes = {}
        c.stats.inflight_count = 0
        c.stats.inflight_peak = 0
        mgr._backends["alpha"] = c

        h = await mgr.health_check(active=False)
        assert h["alpha"]["status"] == "connected"
        assert h["beta"]["status"] == "disconnected"

    async def test_health_check_tool_errors_not_blamed_on_backend(
        self, config_one_backend
    ):
        """BR-B-004: tool_error rate is reported separately from success_rate."""
        mgr = SimpleBackendManager(config_one_backend)
        c = Mock()
        c.is_connected = True
        c.get_tools.return_value = []
        c.stats.total_calls = 10
        c.stats.failed_calls = 0  # NO backend failures
        c.stats.outcomes = {OUTCOME_SUCCESS: 7, OUTCOME_TOOL_ERROR: 3}
        c.stats.inflight_count = 0
        c.stats.inflight_peak = 0
        mgr._backends["test"] = c

        h = await mgr.health_check(active=False)
        # success_rate is 100% — tool errors don't lower it.
        assert h["test"]["success_rate"] == 100.0
        # tool_error_rate is reported separately.
        assert h["test"]["tool_error_rate"] == 30.0

    async def test_health_check_active_probe_degrades_failing_backend(
        self, config_one_backend
    ):
        mgr = SimpleBackendManager(config_one_backend)
        c = Mock()
        c.is_connected = True
        c.get_tools.return_value = []
        c.stats.total_calls = 0
        c.stats.failed_calls = 0
        c.stats.outcomes = {}
        c.stats.inflight_count = 0
        c.stats.inflight_peak = 0
        c.active_probe = AsyncMock(
            return_value={"ok": False, "error_kind": OUTCOME_TIMEOUT, "error": "slow"}
        )
        mgr._backends["test"] = c

        h = await mgr.health_check(active=True)
        # Probe was actually invoked.
        c.active_probe.assert_awaited()
        assert h["test"]["status"] == "degraded"
        assert h["test"]["probe"]["ok"] is False

    async def test_health_check_active_probe_ok_keeps_connected(
        self, config_one_backend
    ):
        mgr = SimpleBackendManager(config_one_backend)
        c = Mock()
        c.is_connected = True
        c.get_tools.return_value = []
        c.stats.total_calls = 0
        c.stats.failed_calls = 0
        c.stats.outcomes = {}
        c.stats.inflight_count = 0
        c.stats.inflight_peak = 0
        c.active_probe = AsyncMock(return_value={"ok": True, "latency_ms": 5.0})
        mgr._backends["test"] = c

        h = await mgr.health_check(active=True)
        assert h["test"]["status"] == "connected"
        assert h["test"]["probe"]["ok"] is True


# =============================================================================
# Manager-level get_backend_tools / get_tool_schema (read paths)
# =============================================================================


class TestManagerToolLookup:
    def test_get_backend_tools_not_connected(self, config_one_backend):
        mgr = SimpleBackendManager(config_one_backend)
        assert mgr.get_backend_tools("test") == []
        # unknown name
        assert mgr.get_backend_tools("nope") == []

    def test_get_backend_tools_returns_connection_tools(self, config_one_backend):
        mgr = SimpleBackendManager(config_one_backend)
        c = Mock()
        c.is_connected = True
        c.get_tools.return_value = [
            ToolInfo("t", "test:t", "", "test", {})
        ]
        mgr._backends["test"] = c
        tools = mgr.get_backend_tools("test")
        assert len(tools) == 1
        assert tools[0].name == "t"

    def test_get_tool_schema_via_index(self, config_one_backend):
        mgr = SimpleBackendManager(config_one_backend)
        c = Mock()
        c.is_connected = True
        c.get_tools.return_value = [
            ToolInfo("t", "test:t", "desc", "test", {"type": "object"})
        ]
        mgr._backends["test"] = c
        mgr._tool_index["test:t"] = "test"
        schema = mgr.get_tool_schema("test:t")
        assert schema is not None
        assert schema["input_schema"] == {"type": "object"}

    def test_get_tool_schema_via_colon_split(self, config_one_backend):
        """Fallback path: tool not in index but qualified_name has a colon."""
        mgr = SimpleBackendManager(config_one_backend)
        c = Mock()
        c.get_tools.return_value = [
            ToolInfo("foo", "test:foo", "", "test", {})
        ]
        mgr._backends["test"] = c
        # Note: NOT in _tool_index — exercise the split fallback branch.
        schema = mgr.get_tool_schema("test:foo")
        assert schema is not None
        assert schema["name"] == "foo"

    def test_get_tool_schema_unknown_returns_none(self, config_one_backend):
        mgr = SimpleBackendManager(config_one_backend)
        # No colon, not in index -> None.
        assert mgr.get_tool_schema("bareword") is None
        # Colon but unknown server -> None.
        assert mgr.get_tool_schema("nope:tool") is None
