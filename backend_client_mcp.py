"""
Tool Compass - MCP SDK Backend Client (EXPERIMENTAL / NOT USED AT RUNTIME)

This module uses the official MCP Python SDK (mcp.client.stdio) for backend
connections. It is NOT used by the gateway — see backend_client_simple.py for
the canonical runtime client, which uses direct subprocess JSON-RPC to avoid
anyio task group conflicts when nested inside another MCP server.

Kept for reference and potential future use when MCP SDK nesting is stable.

If/when this module is reactivated:

- BR-A-015: the SDK path passes ``env=None`` to ``StdioServerParameters`` when
  no extras are configured, which makes the SDK inherit the parent
  environment. The runtime client (``backend_client_simple.py``) gives the
  operator an env-inheritance policy via the ``__env_inheritance__`` reserved
  key; mirror that here before reactivation so the two code paths agree.
- BR-B-001: the runtime client returns a structured error envelope with an
  ``error_kind`` field. The shim below builds the same envelope shape so
  switching back to this client does not break downstream consumers.
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Any, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool, CallToolResult

from config import CompassConfig, StdioBackend, load_config

logger = logging.getLogger(__name__)

# Timeout constants (in seconds)
# NOTE: Claude Code's MCP timeout is ~30s, so we need faster connections
CONNECTION_TIMEOUT = 15  # Max time to establish backend connection
TOOL_CALL_TIMEOUT = 20   # Max time for a single tool execution


@dataclass
class ToolInfo:
    """Normalized tool information from a backend."""

    name: str  # Original tool name
    qualified_name: str  # server:tool_name format
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


class BackendConnection:
    """Manages a single MCP backend server connection."""

    def __init__(self, name: str, backend: StdioBackend):
        self.name = name
        self.backend = backend
        self.session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._tools: List[Tool] = []
        self._connected = False
        self._last_notification_at: Optional[datetime] = None
        self._on_catalog_changed: Optional[Callable[[str], Any]] = None
        self._resources: List[Dict[str, Any]] = []
        self._prompts: List[Dict[str, Any]] = []

    async def connect(self, timeout: Optional[float] = None) -> bool:
        """
        Establish connection to the backend server.

        Args:
            timeout: Connection timeout in seconds. Defaults to CONNECTION_TIMEOUT.
        """
        if self._connected:
            return True

        timeout = timeout or CONNECTION_TIMEOUT

        try:
            logger.info(f"Connecting to backend: {self.name} (timeout={timeout}s)")

            # Build environment. BC-004: honor the BR-A-006 env-inheritance
            # policy that the runtime client (backend_client_simple) enforces,
            # so this experimental path does not leak the parent process's full
            # environment to a backend that opted out. A backend may set the
            # reserved ``__env_inheritance__`` key in its ``env`` dict to
            # ``"none"`` to start from an empty environment; the key is consumed
            # and never passed to the subprocess. Default ("all") preserves the
            # prior inherit-parent behaviour.
            backend_env = dict(self.backend.env) if self.backend.env else {}
            inheritance_policy = backend_env.pop("__env_inheritance__", "all")
            if inheritance_policy == "none":
                env: Optional[Dict[str, str]] = dict(backend_env)
            elif backend_env:
                env = os.environ.copy()
                env.update(backend_env)
            else:
                # No explicit overrides — let the MCP SDK apply its own default
                # environment (env=None), matching prior behaviour.
                env = None

            # Create server parameters
            server_params = StdioServerParameters(
                command=self.backend.command,
                args=self.backend.args,
                env=env,
                cwd=self.backend.cwd,
            )

            # Setup connection with timeout protection
            async def _establish_connection():
                self._exit_stack = AsyncExitStack()
                stdio_transport = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                read_stream, write_stream = stdio_transport

                self.session = await self._exit_stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                        message_handler=self._on_session_message,
                    )
                )

                # Initialize the session
                await self.session.initialize()

                # Cache tools
                await self._refresh_tools()

            await asyncio.wait_for(_establish_connection(), timeout=timeout)
            self._connected = True

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
            # CancelledError is a BaseException on 3.9+; a cancel during
            # enter_async_context / initialize must still aclose the stack.
            try:
                await self.disconnect()
            except Exception:
                logger.debug(
                    f"Disconnect after cancelled connect to {self.name} failed"
                )
            raise

    async def disconnect(self):
        """Close the connection."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning(f"Error closing connection to {self.name}: {e}")
            self._exit_stack = None
        self.session = None
        self._connected = False
        self._tools = []

    async def _on_session_message(self, message: Any) -> None:
        """Honor tools/list_changed instead of dropping no-id notifications."""
        try:
            root = getattr(message, "root", message)
            inner = getattr(root, "root", None)
            method = getattr(root, "method", None) or getattr(inner, "method", None)
            if not method:
                return
            self._last_notification_at = datetime.now()
            method_s = str(method)
            if method_s.endswith("tools/list_changed"):
                await self._refresh_tools()
                cb = self._on_catalog_changed
                if cb is not None:
                    maybe = cb(self.name)
                    if asyncio.iscoroutine(maybe):
                        await maybe
            elif method_s.endswith("prompts/list_changed"):
                await self.list_prompts()
            elif method_s.endswith("resources/list_changed"):
                await self.list_resources()
        except Exception as e:
            logger.debug(f"SDK session message handler for {self.name} failed: {e}")

    async def _refresh_tools(self):
        """Refresh the cached tool list (follow nextCursor)."""
        if not self.session:
            return

        try:
            tools: List[Tool] = []
            cursor = None
            for _ in range(32):
                result = (
                    await self.session.list_tools(cursor=cursor)
                    if cursor
                    else await self.session.list_tools()
                )
                tools.extend(result.tools)
                cursor = getattr(result, "nextCursor", None)
                if not isinstance(cursor, str) or not cursor:
                    break
            self._tools = tools
        except Exception as e:
            logger.error(f"Failed to list tools from {self.name}: {e}")
            self._tools = []

    async def list_resources(self) -> List[Dict[str, Any]]:
        """Live-backend resources/list (F-e126a298)."""
        if not self.session or not self._connected:
            raise RuntimeError(f"Not connected to backend: {self.name}")
        items: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(32):
            result = (
                await self.session.list_resources(cursor=cursor)
                if cursor
                else await self.session.list_resources()
            )
            for res in result.resources:
                if hasattr(res, "model_dump"):
                    items.append(res.model_dump(mode="json"))
                else:
                    items.append({"uri": str(getattr(res, "uri", "")), "name": getattr(res, "name", None)})
            cursor = getattr(result, "nextCursor", None)
            if not isinstance(cursor, str) or not cursor:
                break
        self._resources = items
        return items

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Live-backend resources/read (F-e126a298)."""
        if not self.session or not self._connected:
            raise RuntimeError(f"Not connected to backend: {self.name}")
        from pydantic import AnyUrl
        result = await self.session.read_resource(AnyUrl(uri))
        contents = []
        for item in result.contents or []:
            if hasattr(item, "model_dump"):
                contents.append(item.model_dump(mode="json"))
            else:
                contents.append({"uri": uri, "text": getattr(item, "text", None)})
        return {"success": True, "uri": uri, "contents": contents, "backend": self.name}

    async def list_prompts(self) -> List[Dict[str, Any]]:
        """Live-backend prompts/list (F-e126a298)."""
        if not self.session or not self._connected:
            raise RuntimeError(f"Not connected to backend: {self.name}")
        items: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(32):
            result = (
                await self.session.list_prompts(cursor=cursor)
                if cursor
                else await self.session.list_prompts()
            )
            for prompt in result.prompts:
                if hasattr(prompt, "model_dump"):
                    items.append(prompt.model_dump(mode="json"))
                else:
                    items.append({"name": getattr(prompt, "name", "")})
            cursor = getattr(result, "nextCursor", None)
            if not isinstance(cursor, str) or not cursor:
                break
        self._prompts = items
        return items

    async def get_prompt(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Live-backend prompts/get (F-e126a298)."""
        if not self.session or not self._connected:
            raise RuntimeError(f"Not connected to backend: {self.name}")
        str_args = {k: str(v) for k, v in arguments.items()} if arguments else None
        result = await self.session.get_prompt(name, str_args)
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

    def get_tools(self) -> List[ToolInfo]:
        """Get normalized tool info list."""
        tools = []
        for tool in self._tools:
            tools.append(
                ToolInfo(
                    name=tool.name,
                    qualified_name=f"{self.name}:{tool.name}",
                    description=tool.description or "",
                    server=self.name,
                    input_schema=tool.inputSchema
                    if hasattr(tool, "inputSchema")
                    else {},
                )
            )
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        progress_callback: Optional[Any] = None,
    ) -> CallToolResult:
        """Call a tool on this backend (forwards SDK progress if provided)."""
        if not self.session or not self._connected:
            raise RuntimeError(f"Not connected to backend: {self.name}")

        return await self.session.call_tool(
            tool_name, arguments, progress_callback=progress_callback
        )

    @property
    def is_connected(self) -> bool:
        return self._connected


class BackendManager:
    """
    Manages multiple MCP backend connections.
    Acts as the routing layer for tool discovery and execution.
    """

    def __init__(self, config: Optional[CompassConfig] = None):
        self.config = config or load_config()
        self._backends: Dict[str, BackendConnection] = {}
        self._tool_index: Dict[str, str] = {}  # qualified_name -> server_name
        self._lock: Optional[asyncio.Lock] = None
        self._connecting: Dict[str, "asyncio.Future[bool]"] = {}

    def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def connect_all(self, timeout: Optional[float] = None) -> Dict[str, bool]:
        """
        Connect to all configured backends concurrently.

        Args:
            timeout: Per-backend connection timeout. Defaults to CONNECTION_TIMEOUT.

        Returns:
            Dict mapping backend name to connection success status.
        """
        results = {}
        timeout = timeout or CONNECTION_TIMEOUT

        # Build connection tasks for all stdio backends
        tasks = []
        backend_names = []
        connections = []

        for name, backend in self.config.backends.items():
            if isinstance(backend, StdioBackend):
                conn = BackendConnection(name, backend)
                connections.append(conn)
                backend_names.append(name)
                tasks.append(conn.connect(timeout=timeout))
            else:
                logger.warning(
                    f"Backend type not yet supported: {type(backend)} for {name}"
                )
                results[name] = False

        # Run all connections concurrently
        if tasks:
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)

            for name, conn, outcome in zip(backend_names, connections, outcomes):
                if isinstance(outcome, Exception):
                    logger.error(f"Backend {name} connection failed: {outcome}")
                    results[name] = False
                elif outcome:  # True = success
                    results[name] = True
                    self._backends[name] = conn
                    for tool in conn.get_tools():
                        self._tool_index[tool.qualified_name] = name
                else:
                    results[name] = False

        return results

    async def connect_backend(self, name: str, timeout: Optional[float] = None) -> bool:
        """
        Connect to a specific backend.

        Single-flight per backend (sibling of F-47ef65da): waiters await the
        in-flight connect instead of spawning a sibling session. On swap, a
        different live occupant wins and the extra is disconnected.

        Args:
            name: Backend name to connect to.
            timeout: Connection timeout in seconds. Defaults to CONNECTION_TIMEOUT.
        """
        lock = self._ensure_lock()
        waiter: Optional["asyncio.Future[bool]"] = None
        slot: Optional["asyncio.Future[bool]"] = None
        backend = None
        reject = False

        async with lock:
            if name in self._backends and self._backends[name].is_connected:
                return True
            inflight = self._connecting.get(name)
            if inflight is not None and not inflight.done():
                waiter = inflight
            else:
                slot = asyncio.get_running_loop().create_future()
                self._connecting[name] = slot
                backend = self.config.backends.get(name)
                if not backend or not isinstance(backend, StdioBackend):
                    reject = True

        if waiter is not None:
            return await waiter

        extra = None
        result = False
        try:
            if reject:
                if not backend:
                    logger.error(f"Unknown backend: {name}")
                else:
                    logger.error(
                        f"Unsupported backend type for {name}: {type(backend)}"
                    )
                return False

            conn = BackendConnection(name, backend)
            success = await conn.connect(timeout=timeout)
            if not success:
                return False

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

    async def disconnect_all(self):
        """Disconnect from all backends."""
        lock = self._ensure_lock()
        async with lock:
            conns = list(self._backends.values())
            self._backends.clear()
            self._tool_index.clear()
            connecting = list(self._connecting.values())
            self._connecting.clear()
        for fut in connecting:
            if not fut.done():
                fut.set_result(False)
        for conn in conns:
            await conn.disconnect()

    def get_all_tools(self) -> List[ToolInfo]:
        """Get all tools from all connected backends."""
        tools = []
        for conn in self._backends.values():
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
            # Try parsing the qualified name
            if ":" in qualified_name:
                server_name, tool_name = qualified_name.split(":", 1)
            else:
                return None

        conn = self._backends.get(server_name)
        if not conn:
            return None

        for tool in conn.get_tools():
            if (
                tool.qualified_name == qualified_name
                or tool.name == qualified_name.split(":")[-1]
            ):
                return tool.to_dict()

        return None

    async def execute_tool(
        self,
        qualified_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool by its qualified name (server:tool_name).

        Args:
            qualified_name: Tool name in 'server:tool' format.
            arguments: Tool arguments.
            timeout: Execution timeout in seconds. Defaults to TOOL_CALL_TIMEOUT.

        Returns:
            Dict with 'success', 'result' or 'error' keys.
        """
        timeout = timeout or TOOL_CALL_TIMEOUT

        # Parse qualified name. BC-003: mirror backend_client_simple's
        # tool-index-first parse so a backend name containing ':' does not get
        # silently mis-split by a naive ``split(':', 1)``. Prefer the known
        # ``qualified_name -> server_name`` mapping and recover the tool name by
        # stripping the resolved server prefix; only fall back to the naive
        # split when the name is not indexed.
        if qualified_name in self._tool_index:
            server_name = self._tool_index[qualified_name]
            prefix = f"{server_name}:"
            if qualified_name.startswith(prefix):
                tool_name = qualified_name[len(prefix):]
            else:
                tool_name = qualified_name
        elif ":" in qualified_name:
            server_name, tool_name = qualified_name.split(":", 1)
        else:
            # Try to find in index
            server_name = self._tool_index.get(qualified_name)
            tool_name = qualified_name
            if not server_name:
                return {
                    "success": False,
                    "error_kind": "backend_unavailable",
                    "error": (
                        f"Tool not found: {qualified_name}. "
                        "Use format 'server:tool_name'."
                    ),
                    "retryable": False,
                }

        # Get backend
        conn = self._backends.get(server_name)
        if not conn:
            # Try to connect on-demand
            if server_name in self.config.backends:
                success = await self.connect_backend(server_name)
                if not success:
                    return {
                        "success": False,
                        "error_kind": "backend_unavailable",
                        "error": (
                            f"Failed to connect to backend: {server_name}"
                        ),
                        "backend": server_name,
                        "retryable": True,
                    }
                conn = self._backends.get(server_name)
            else:
                return {
                    "success": False,
                    "error_kind": "backend_unavailable",
                    "error": f"Unknown backend: {server_name}",
                    "backend": server_name,
                    "retryable": False,
                }

        # Execute with timeout protection. Envelope shape matches the runtime
        # client's contract (see backend_client_simple.make_error_envelope)
        # so a future swap-over does not break downstream consumers.
        try:
            result = await asyncio.wait_for(
                conn.call_tool(tool_name, arguments), timeout=timeout
            )

            # Parse result
            if result.isError:
                # MCP isError — tool_error. Preserve the content array.
                content_list = list(result.content) if result.content else []
                error_text_parts = []
                for item in content_list:
                    if hasattr(item, "text"):
                        error_text_parts.append(item.text)
                error_text = "".join(error_text_parts) or "Tool returned error"
                return {
                    "success": False,
                    "error_kind": "tool_error",
                    "error": error_text,
                    "backend": server_name,
                    "retryable": True,
                    "content": content_list,
                }

            # Extract content
            content = []
            for item in result.content:
                if hasattr(item, "text"):
                    content.append(item.text)
                elif hasattr(item, "data"):
                    content.append(f"[Binary data: {item.mimeType}]")
                else:
                    content.append(str(item))

            return {
                "success": True,
                "result": "\n".join(content)
                if content
                else "Tool executed successfully",
            }

        except asyncio.TimeoutError:
            logger.error(f"Tool execution timed out after {timeout}s: {qualified_name}")
            return {
                "success": False,
                "error_kind": "timeout",
                "error": f"Tool execution timed out after {timeout}s",
                "backend": server_name,
                "retryable": True,
            }
        except Exception as e:
            logger.error(f"Error executing {qualified_name}: {e}")
            return {
                "success": False,
                "error_kind": "transport_error",
                "error": str(e),
                "backend": server_name,
                "retryable": False,
            }

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        connected = [name for name, conn in self._backends.items() if conn.is_connected]
        tool_count = len(self._tool_index)

        return {
            "configured_backends": list(self.config.backends.keys()),
            "connected_backends": connected,
            "total_tools": tool_count,
            "tools_by_backend": {
                name: len(conn.get_tools()) for name, conn in self._backends.items()
            },
        }


# Singleton instance
_manager: Optional[BackendManager] = None


async def get_backend_manager() -> BackendManager:
    """Get or create the global backend manager."""
    global _manager
    if _manager is None:
        _manager = BackendManager()
    return _manager


async def init_backends(connect: bool = True) -> BackendManager:
    """Initialize backends, optionally connecting to all."""
    manager = await get_backend_manager()
    if connect:
        await manager.connect_all()
    return manager
