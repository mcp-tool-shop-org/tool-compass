"""Streamable HTTP / JSON-RPC wire tests for HttpBackendConnection.

INT-01 coverage in test_backend_client_simple_coverage.py patches
streamablehttp_client + ClientSession with FakeClientSession, so it never
speaks initialize.protocolVersion, tools/list nextCursor, tools/call, ping,
or MCP-Protocol-Version / Accept / mcp-session-id headers.

This module drives a protocol-speaking session that POSTs real JSON-RPC
frames at an in-process httpx.MockTransport stub (F-2b107cb9). The socket
is mocked; the protocol shape is not.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

import backend_client_simple as bcs
from backend_client_simple import (
    HttpBackendConnection,
    OUTCOME_TIMEOUT,
    OUTCOME_TRANSPORT_ERROR,
)
from config import HttpBackend
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
    LATEST_PROTOCOL_VERSION,
)


# =============================================================================
# In-process JSON-RPC stub (Streamable HTTP response shape)
# =============================================================================


class StreamableHttpRpcStub:
    """JSON-RPC dispatcher that httpx.MockTransport can speak.

    Implements initialize, tools/list (two pages via nextCursor), tools/call,
    ping, and notifications. Records every RPC payload and request header.
    """

    SESSION_ID = "sess-wire-test"
    PROTOCOL = "2025-03-26"
    PAGE2_CURSOR = "page-2"

    def __init__(self) -> None:
        self.rpc: List[Dict[str, Any]] = []
        self.header_log: List[Dict[str, Any]] = []
        self.stringify_ids = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        headers = {k.lower(): v for k, v in request.headers.items()}
        self.header_log.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": headers,
            }
        )
        if request.method == "GET":
            return httpx.Response(405, text="GET SSE not implemented")
        if request.method == "DELETE":
            return httpx.Response(204)

        raw = request.content or b""
        body: Dict[str, Any] = json.loads(raw.decode("utf-8")) if raw else {}
        method = body.get("method")
        req_id = body.get("id")
        if method or req_id is not None:
            self.rpc.append(body)

        if req_id is None:
            return httpx.Response(202)

        echo_id: Any = str(req_id) if self.stringify_ids else req_id
        result = self._result(method, body.get("params") or {})
        payload = {"jsonrpc": "2.0", "id": echo_id, "result": result}
        return httpx.Response(
            200,
            json=payload,
            headers={
                "content-type": "application/json",
                "mcp-session-id": self.SESSION_ID,
            },
        )

    def _result(self, method: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
        if method == "initialize":
            advertised = params.get("protocolVersion") or self.PROTOCOL
            return {
                "protocolVersion": advertised,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "wire-stub", "version": "1.0.0"},
            }
        if method == "tools/list":
            cursor = params.get("cursor")
            if cursor == self.PAGE2_CURSOR:
                return {
                    "tools": [
                        {
                            "name": "paged_tool",
                            "description": "second page of tools/list",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                }
            return {
                "tools": [
                    {
                        "name": "echo",
                        "description": "echo a string",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"x": {"type": "string"}},
                        },
                    }
                ],
                "nextCursor": self.PAGE2_CURSOR,
            }
        if method == "tools/call":
            name = params.get("name", "")
            return {
                "content": [{"type": "text", "text": f"called {name}"}],
                "isError": False,
            }
        if method == "ping":
            return {}
        return {}

    def methods(self) -> List[Optional[str]]:
        return [m.get("method") for m in self.rpc]

    def first(self, method: str) -> Dict[str, Any]:
        for msg in self.rpc:
            if msg.get("method") == method:
                return msg
        raise AssertionError(
            f"no JSON-RPC method {method!r} on the wire: {self.methods()}"
        )

    def posts(self) -> List[Dict[str, Any]]:
        return [h for h in self.header_log if h["method"] == "POST"]


class JsonRpcClientSession:
    """ClientSession stand-in that POSTs JSON-RPC at the stub.

    Not FakeClientSession: every initialize / tools/list / tools/call / ping
    is a real JSON-RPC frame with protocolVersion, cursor, and MCP headers.
    """

    def __init__(self, stub: StreamableHttpRpcStub, *args, **kwargs) -> None:
        self._stub = stub
        self._next_id = 0
        self._client = httpx.AsyncClient(
            transport=httpx.MockTransport(stub.handler)
        )
        self._initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()
        return False

    def _headers(self) -> Dict[str, str]:
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": StreamableHttpRpcStub.PROTOCOL,
        }
        if self._initialized:
            headers["mcp-session-id"] = StreamableHttpRpcStub.SESSION_ID
        return headers

    async def _rpc(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        req_id: Any = None,
    ) -> Dict[str, Any]:
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id if req_id is None else req_id,
            "method": method,
            "params": params or {},
        }
        response = await self._client.post(
            "http://mcp.test/mcp",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(body["error"])
        return body.get("result") or {}

    async def initialize(self):
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "tool-compass", "version": "0"},
            },
        )
        self._initialized = True
        # notifications/initialized is a JSON-RPC notification (no id).
        await self._client.post(
            "http://mcp.test/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers=self._headers(),
        )
        return result

    async def list_tools(self, cursor: str | None = None, *, params=None):
        if params is not None:
            cursor = getattr(params, "cursor", cursor)
        body: Dict[str, Any] = {}
        if cursor:
            body["cursor"] = cursor
        result = await self._rpc("tools/list", body)
        tools = [
            Tool(
                name=t["name"],
                description=t.get("description") or "",
                inputSchema=t.get("inputSchema") or {"type": "object"},
            )
            for t in result.get("tools") or []
        ]
        return ListToolsResult(tools=tools, nextCursor=result.get("nextCursor"))

    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        result = await self._rpc(
            "tools/call", {"name": name, "arguments": arguments}
        )
        content = [
            TextContent(type="text", text=block.get("text", ""))
            for block in result.get("content") or []
            if block.get("type") == "text"
        ]
        return CallToolResult(
            content=content, isError=bool(result.get("isError"))
        )

    async def send_ping(self):
        await self._rpc("ping", {})
        return Mock()


def _backend() -> HttpBackend:
    return HttpBackend(
        url="http://mcp.test/mcp",
        headers={"Authorization": "Bearer super-secret-token"},
        timeout=5.0,
    )


def _install_protocol_session(stub: StreamableHttpRpcStub, monkeypatch) -> None:
    """Patch SDK entry points so connect() speaks JSON-RPC at the stub."""

    def _fake_streamable(*_a, **_k):
        class _CM:
            async def __aenter__(self):
                read = Mock(name="read_stream")
                write = Mock(name="write_stream")
                return (read, write, lambda: stub.SESSION_ID)

            async def __aexit__(self, *_exc):
                return False

        return _CM()

    def _fake_session(*_a, **_k):
        return JsonRpcClientSession(stub)

    monkeypatch.setattr(bcs, "streamablehttp_client", _fake_streamable)
    monkeypatch.setattr(bcs, "ClientSession", _fake_session)


@pytest.fixture
def stub() -> StreamableHttpRpcStub:
    return StreamableHttpRpcStub()


async def _connect(
    stub: StreamableHttpRpcStub, monkeypatch
) -> HttpBackendConnection:
    _install_protocol_session(stub, monkeypatch)
    conn = HttpBackendConnection("http", _backend())
    ok = await conn.connect(timeout=5.0)
    assert ok is True, f"connect failed; rpc={stub.methods()}"
    return conn


# =============================================================================
# Wire contract
# =============================================================================


@pytest.mark.asyncio
async def test_connect_advertises_protocol_version_on_initialize(stub, monkeypatch):
    conn = await _connect(stub, monkeypatch)
    try:
        init = stub.first("initialize")
        advertised = (init.get("params") or {}).get("protocolVersion")
        assert advertised, f"initialize missing protocolVersion: {init}"
        assert str(advertised) in {
            "2024-11-05",
            "2025-03-26",
            "2025-06-18",
            LATEST_PROTOCOL_VERSION,
            stub.PROTOCOL,
        }
        assert "echo" in {t.name for t in conn.get_tools()}
    finally:
        await conn.disconnect()


@pytest.mark.asyncio
async def test_tools_list_nextcursor_page_two_is_consumable(stub, monkeypatch):
    """Both list pages exist on the wire; a cursor follow must see page 2.

    HttpBackendConnection.connect currently calls list_tools() once (OPEN
    F-aa9e6789). This test follows nextCursor on the live session so dropping
    the cursor field, or a session that cannot take a cursor, goes red —
    FakeClientSession.list_tools is a one-shot AsyncMock and cannot.
    """
    conn = await _connect(stub, monkeypatch)
    try:
        stub.first("tools/list")
        assert "echo" in {t.name for t in conn.get_tools()}
        page2 = await conn._session.list_tools(cursor=StreamableHttpRpcStub.PAGE2_CURSOR)
        assert "paged_tool" in {t.name for t in page2.tools}
        list_calls = [m for m in stub.rpc if m.get("method") == "tools/list"]
        assert len(list_calls) >= 2
        assert (list_calls[1].get("params") or {}).get("cursor") == (
            StreamableHttpRpcStub.PAGE2_CURSOR
        )
    finally:
        await conn.disconnect()


@pytest.mark.asyncio
async def test_call_tool_and_ping_speak_jsonrpc(stub, monkeypatch):
    conn = await _connect(stub, monkeypatch)
    try:
        env = await conn.call_tool("echo", {"x": "hi"})
        assert env["success"] is True
        assert "echo" in env["result"]
        call = stub.first("tools/call")
        assert (call.get("params") or {}).get("name") == "echo"
        assert (call.get("params") or {}).get("arguments") == {"x": "hi"}

        probe = await conn.active_probe(timeout=2.0)
        assert probe["ok"] is True
        assert "ping" in stub.methods()
    finally:
        await conn.disconnect()


@pytest.mark.asyncio
async def test_accept_and_session_headers_survive_factory(stub, monkeypatch):
    conn = await _connect(stub, monkeypatch)
    try:
        await conn.call_tool("echo", {"x": 1})
        posts = stub.posts()
        assert posts, "expected POSTs on the Streamable HTTP stub"
        accept_hits = [
            h for h in posts if "application/json" in h["headers"].get("accept", "")
        ]
        assert accept_hits, (
            "Accept: application/json, text/event-stream must survive the "
            f"httpx_client_factory; saw {[h['headers'] for h in posts]}"
        )
        session_hits = [
            h
            for h in posts
            if h["headers"].get("mcp-session-id") == StreamableHttpRpcStub.SESSION_ID
        ]
        assert session_hits, (
            "mcp-session-id from the initialize response must be replayed on "
            f"later POSTs; saw {[h['headers'] for h in posts]}"
        )
        versions = [
            h["headers"].get("mcp-protocol-version")
            for h in posts
            if h["headers"].get("mcp-protocol-version")
        ]
        assert versions, (
            "MCP-Protocol-Version header missing after initialize; "
            f"headers={[h['headers'] for h in posts]}"
        )
    finally:
        await conn.disconnect()


@pytest.mark.asyncio
async def test_string_jsonrpc_id_still_completes(stub):
    """A server that echoes a string JSON-RPC id must still complete (F-d76d39e4)."""
    stub.stringify_ids = True
    transport = httpx.MockTransport(stub.handler)
    async with httpx.AsyncClient(transport=transport) as client:
        init = await client.post(
            "http://mcp.test/mcp",
            json={
                "jsonrpc": "2.0",
                "id": "str-id-1",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "tool-compass", "version": "0"},
                },
            },
        )
        assert init.status_code == 200
        body = init.json()
        assert body["id"] == "str-id-1"
        assert body["result"]["protocolVersion"]

        call = await client.post(
            "http://mcp.test/mcp",
            json={
                "jsonrpc": "2.0",
                "id": "str-id-2",
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"x": 1}},
            },
        )
        assert call.status_code == 200
        called = call.json()
        assert called["id"] == "str-id-2"
        assert called["result"]["isError"] is False
        assert "echo" in called["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_httpstatuserror_4xx_marks_disconnected_like_transport_error(
    stub, monkeypatch
):
    """Lock current product: HTTPStatusError 4xx marks the backend dead the
    same way TransportError does (F-44d6d3c1). If a later fix treats 4xx as
    protocol/tool error without dropping the session, this assertion changes.
    """
    conn = await _connect(stub, monkeypatch)
    try:
        req = httpx.Request("POST", "http://mcp.test/mcp")
        resp = httpx.Response(404, request=req, text="no such session")
        conn._session.call_tool = AsyncMock(
            side_effect=httpx.HTTPStatusError("404", request=req, response=resp)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await conn.call_tool("echo", {})
        assert conn.is_connected is False
        assert conn.stats.outcomes[OUTCOME_TRANSPORT_ERROR] == 1

        stub2 = StreamableHttpRpcStub()
        conn2 = await _connect(stub2, monkeypatch)
        try:
            conn2._session.call_tool = AsyncMock(
                side_effect=httpx.ReadError("connection dropped")
            )
            with pytest.raises(httpx.TransportError):
                await conn2.call_tool("echo", {})
            assert conn2.is_connected is False
            assert conn2.stats.outcomes[OUTCOME_TRANSPORT_ERROR] == 1
        finally:
            await conn2.disconnect()
    finally:
        await conn.disconnect()


@pytest.mark.asyncio
async def test_active_probe_timeout_kind_on_hung_ping(stub, monkeypatch):
    conn = await _connect(stub, monkeypatch)
    try:
        async def slow_ping():
            import asyncio

            await asyncio.sleep(5)

        conn._session.send_ping = AsyncMock(side_effect=slow_ping)
        result = await conn.active_probe(timeout=0.05)
        assert result["ok"] is False
        assert result["error_kind"] == OUTCOME_TIMEOUT
    finally:
        await conn.disconnect()
