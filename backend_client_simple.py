"""
Tool Compass - Simple Backend Client
Uses subprocess directly with JSON-RPC to avoid anyio conflicts.

This module provides a robust, Windows-compatible MCP client that:
- Uses asyncio.create_subprocess_exec directly (avoids anyio task group issues)
- Implements connection pooling with keep-alive
- Has proper error handling and timeouts
- Supports graceful shutdown
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

from config import CompassConfig, StdioBackend, load_config
from _version import __version__

logger = logging.getLogger(__name__)

# Timeout constants (in seconds)
CONNECTION_TIMEOUT = 10
TOOL_CALL_TIMEOUT = 15
KEEPALIVE_INTERVAL = 30  # Ping backends every 30s to keep connection alive
MAX_RETRIES = 2

# Stream bounds — guard the gateway against a malicious/buggy backend that
# writes a massive single line (would otherwise OOM the parent process)
STDOUT_LINE_LIMIT = 1024 * 1024  # 1 MiB per JSON-RPC line
STDOUT_READ_TIMEOUT = 30.0  # Per-readline timeout in seconds


class BackendShuttingDownError(RuntimeError):
    """Raised when a request is cancelled because the backend is shutting down.

    The message is deliberately user-actionable so it surfaces cleanly through
    any error envelope the gateway produces.
    """


class BackendProtocolError(RuntimeError):
    """Raised when a backend returns a structured MCP/JSON-RPC error.

    Preserves the numeric ``code``, human ``message``, and any ``data`` payload
    from the original error so downstream logs / responses can surface the
    structured shape instead of flattening it into a bare RuntimeError string.
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
    """Track connection health metrics."""
    connected_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    total_calls: int = 0
    failed_calls: int = 0
    avg_latency_ms: float = 0.0

    def record_call(self, success: bool, latency_ms: float):
        self.last_used = datetime.now()
        self.total_calls += 1
        if not success:
            self.failed_calls += 1
        # Running average
        self.avg_latency_ms = (self.avg_latency_ms * (self.total_calls - 1) + latency_ms) / self.total_calls


class SimpleBackendConnection:
    """
    Simple MCP backend connection using subprocess directly.
    Avoids anyio task group conflicts by not using the MCP client library.

    Features:
    - Direct asyncio subprocess management
    - Connection keep-alive with periodic pings
    - Automatic reconnection on failure
    - Detailed error handling
    """

    def __init__(self, name: str, backend: StdioBackend):
        self.name = name
        self.backend = backend
        self._process: Optional[asyncio.subprocess.Process] = None
        self._tools: List[Dict[str, Any]] = []
        self._connected = False
        self._request_id = 0
        # GW-FT-001: split locking model.
        # - _write_lock serializes stdin writes ONLY (so concurrent callers
        #   don't interleave JSON-RPC frames on stdout).
        # - The read side runs in a dedicated _read_loop task that dispatches
        #   responses to per-request futures in _pending. This lets N concurrent
        #   tool calls to the same backend actually run in parallel.
        # - _lock is preserved as an alias so disconnect() can still grab it
        #   (external tests may also inject a mock). It maps to _write_lock.
        self._write_lock = asyncio.Lock()
        self._lock = self._write_lock  # Backwards-compatible alias
        self._pending: Dict[int, "asyncio.Future[Dict[str, Any]]"] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._stats = ConnectionStats()
        self._stderr_task: Optional[asyncio.Task] = None
        # GW-B-004: flipped by disconnect() so any in-flight _send_request
        # can distinguish a shutdown from a genuine backend crash.
        self._shutting_down: bool = False

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

        GW-FT-001: one task per connection. Runs until EOF, a read error, or
        the task is cancelled during disconnect(). Malformed lines are logged
        at WARNING and skipped (the writer-side timeout will still surface a
        stuck request).
        """
        assert self._process is not None and self._process.stdout is not None
        stdout = self._process.stdout
        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        stdout.readline(),
                        timeout=STDOUT_READ_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    # Idle read timeout — keep looping. Per-request deadlines
                    # are enforced by the writer with asyncio.wait_for(fut).
                    if self._shutting_down:
                        break
                    continue
                except asyncio.LimitOverrunError as e:
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
        if self._connected and self._process and self._process.returncode is None:
            return True

        timeout = timeout or CONNECTION_TIMEOUT

        try:
            logger.info(f"Connecting to backend: {self.name} (timeout={timeout}s)")

            # Build environment - inherit from current process and add extras
            env = os.environ.copy()
            if self.backend.env:
                env.update(self.backend.env)
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

        GW-B-004: Try to acquire the request lock so we don't rip the process
        out from under an in-flight call. If the lock doesn't free within 5s
        we proceed anyway (any in-flight request will see _shutting_down and
        surface BackendShuttingDownError instead of a raw BrokenPipeError).
        """
        # Signal in-flight requests BEFORE we start tearing anything down.
        self._shutting_down = True
        self._connected = False

        # GW-FT-001: fail any pending futures immediately so callers stuck in
        # asyncio.wait_for(fut) wake with BackendShuttingDownError rather than
        # hitting their own tool timeout.
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

            # Cancel stdout reader (GW-FT-001)
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
                try:
                    # Try graceful shutdown first
                    if self._process.stdin:
                        self._process.stdin.close()
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        self._process.kill()
                        await self._process.wait()
                except Exception as e:
                    logger.debug(f"Error during disconnect of {self.name}: {e}")
                self._process = None

            self._tools = []
        finally:
            if lock_acquired:
                self._write_lock.release()

    async def _read_stderr(self):
        """Read and log stderr from the backend process."""
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                # Log backend stderr at debug level
                logger.debug(f"[{self.name}] {line.decode('utf-8', errors='replace').rstrip()}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Stderr reader error for {self.name}: {e}")

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for its response.

        GW-FT-001: only the write side is serialized (``_write_lock``). The
        response arrives asynchronously via ``_read_loop`` which sets
        ``_pending[request_id]``. Concurrent requests to the same backend no
        longer serialize on the read side.

        GW-B-004: ``_shutting_down`` is still honoured at every boundary, and
        ``disconnect()`` fails every pending future with
        ``BackendShuttingDownError``.
        """
        if self._shutting_down:
            raise BackendShuttingDownError(
                f"Backend {self.name} is shutting down — request cancelled"
            )
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError("Not connected")
        if self._process.returncode is not None:
            raise RuntimeError(
                f"Process exited with code {self._process.returncode}"
            )

        loop = asyncio.get_running_loop()
        fut: "asyncio.Future[Dict[str, Any]]" = loop.create_future()

        async with self._write_lock:
            # Re-check shutdown after acquiring the write lock — disconnect()
            # may have run while we were queued.
            if self._shutting_down:
                raise BackendShuttingDownError(
                    f"Backend {self.name} is shutting down — request cancelled"
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
                # Pull our future back off the pending map before surfacing.
                self._pending.pop(request_id, None)
                if self._shutting_down:
                    raise BackendShuttingDownError(
                        f"Backend {self.name} is shutting down — request cancelled"
                    ) from e
                raise

        # Now wait for the read loop to resolve our future. We don't hold the
        # write lock here, so other callers can send their own requests in
        # parallel.
        try:
            return await asyncio.wait_for(fut, timeout=STDOUT_READ_TIMEOUT)
        except asyncio.TimeoutError:
            if self._shutting_down:
                raise BackendShuttingDownError(
                    f"Backend {self.name} is shutting down — request cancelled"
                )
            raise RuntimeError(
                f"Backend {self.name} did not respond within {STDOUT_READ_TIMEOUT}s"
            )
        finally:
            # Whether we succeeded or timed out, don't leak an entry.
            self._pending.pop(request_id, None)

    async def _send_notification(self, method: str, params: Optional[Dict[str, Any]] = None):
        """Send a JSON-RPC notification (no response expected)."""
        async with self._write_lock:
            if not self._process or not self._process.stdin:
                raise RuntimeError("Not connected")

            notification: Dict[str, Any] = {
                "jsonrpc": "2.0",
                "method": method,
            }
            if params:
                notification["params"] = params

            notification_str = json.dumps(notification) + "\n"
            self._process.stdin.write(notification_str.encode("utf-8"))
            await self._process.stdin.drain()

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
        """Call a tool on this backend with automatic reconnection."""
        if not self._connected:
            raise RuntimeError(f"Not connected to backend: {self.name}")

        start_time = asyncio.get_event_loop().time()

        try:
            result = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments
            })

            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            if "error" in result:
                self._stats.record_call(False, latency_ms)
                return {
                    "success": False,
                    "error": result["error"].get("message", str(result["error"]))
                }

            if "result" in result:
                res = result["result"]
                if res.get("isError"):
                    self._stats.record_call(False, latency_ms)
                    content = res.get("content", [])
                    error_text = ""
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and "text" in item:
                                error_text += item["text"]
                    return {
                        "success": False,
                        "error": error_text or "Tool returned error"
                    }

                # Extract text content
                content = []
                for item in res.get("content", []):
                    if isinstance(item, dict) and "text" in item:
                        content.append(item["text"])
                    elif isinstance(item, str):
                        content.append(item)
                    else:
                        content.append(str(item))

                self._stats.record_call(True, latency_ms)
                return {
                    "success": True,
                    "result": "\n".join(content) if content else "Tool executed successfully"
                }

            self._stats.record_call(False, latency_ms)
            return {"success": False, "error": "Invalid response from backend"}

        except Exception:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self._stats.record_call(False, latency_ms)

            # Check if process died
            if self._process and self._process.returncode is not None:
                self._connected = False
                logger.warning(f"Backend {self.name} process died, will reconnect on next call")

            raise

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
        self._lock = asyncio.Lock()

    async def connect_backend(self, name: str, timeout: Optional[float] = None) -> bool:
        """Connect to a specific backend with retry logic."""
        async with self._lock:
            # Check if already connected
            if name in self._backends and self._backends[name].is_connected:
                return True

            backend = self.config.backends.get(name)
            if not backend:
                logger.error(f"Unknown backend: {name}")
                return False

            if not isinstance(backend, StdioBackend):
                logger.error(f"Unsupported backend type for {name}")
                return False

            # Disconnect existing broken connection
            if name in self._backends:
                await self._backends[name].disconnect()

            # Try to connect with retries
            conn = SimpleBackendConnection(name, backend)

            for attempt in range(MAX_RETRIES + 1):
                success = await conn.connect(timeout=timeout)
                if success:
                    self._backends[name] = conn
                    for tool in conn.get_tools():
                        self._tool_index[tool.qualified_name] = name
                    return True

                if attempt < MAX_RETRIES:
                    logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES} for backend {name}")
                    await asyncio.sleep(0.5)  # Brief pause before retry

            return False

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

    async def disconnect_all(self):
        """Disconnect from all backends gracefully."""
        async with self._lock:
            tasks = [conn.disconnect() for conn in self._backends.values()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._backends.clear()
            self._tool_index.clear()

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
        """Execute a tool by its qualified name with automatic reconnection."""
        timeout = timeout or TOOL_CALL_TIMEOUT

        # Parse qualified name
        if ":" in qualified_name:
            server_name, tool_name = qualified_name.split(":", 1)
        else:
            server_name = self._tool_index.get(qualified_name)
            tool_name = qualified_name
            if not server_name:
                return {
                    "success": False,
                    "error": f"Tool not found: {qualified_name}. Use format 'server:tool_name'.",
                }

        # Ensure connected (with automatic reconnection)
        if not await self.ensure_connected(server_name):
            return {
                "success": False,
                "error": f"Failed to connect to backend: {server_name}",
            }

        conn = self._backends.get(server_name)
        if not conn:
            return {
                "success": False,
                "error": f"Backend not available: {server_name}",
            }

        try:
            return await asyncio.wait_for(
                conn.call_tool(tool_name, arguments),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Tool execution timed out after {timeout}s: {qualified_name}")
            return {
                "success": False,
                "error": f"Tool execution timed out after {timeout}s",
            }
        except Exception as e:
            logger.error(f"Error executing {qualified_name}: {e}")

            # Try one reconnect and retry
            logger.info(f"Attempting reconnect to {server_name}...")
            if await self.connect_backend(server_name):
                try:
                    return await asyncio.wait_for(
                        self._backends[server_name].call_tool(tool_name, arguments),
                        timeout=timeout
                    )
                except Exception as retry_error:
                    return {
                        "success": False,
                        "error": f"Retry failed: {retry_error}",
                    }

            return {
                "success": False,
                "error": str(e),
            }

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics for all backends."""
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
                    "connected_at": conn.stats.connected_at.isoformat() if conn.stats.connected_at else None,
                    "last_used": conn.stats.last_used.isoformat() if conn.stats.last_used else None,
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

    async def health_check(self) -> Dict[str, Any]:
        """Check health of all backends."""
        health = {}
        for name in self.config.backends.keys():
            conn = self._backends.get(name)
            if conn and conn.is_connected:
                health[name] = {
                    "status": "connected",
                    "tools": len(conn.get_tools()),
                    "success_rate": round(
                        (1 - conn.stats.failed_calls / max(conn.stats.total_calls, 1)) * 100, 1
                    ),
                }
            else:
                health[name] = {"status": "disconnected"}
        return health
