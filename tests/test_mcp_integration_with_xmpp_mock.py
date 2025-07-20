"""Integration tests with in-memory MCP server and mocked XMPP client."""

import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock, patch

import pytest

from jabber_mcp.bridge.mcp_bridge import McpBridge
from jabber_mcp.converters import convert_mcp_send_to_xmpp
from jabber_mcp.mcp_stdio_server import JsonRpcMessage, McpStdioServer
from jabber_mcp.xmpp_adapter import XmppAdapter


class MockXmppAdapter:
    """Mock XMPP adapter for integration testing."""

    def __init__(self, jid: str, password: str, mcp_bridge=None):
        self.jid = jid
        self.password = password
        self.mcp_bridge = mcp_bridge
        self.connected = False
        self.sent_messages: list[dict[str, Any]] = []
        self.connection_attempts = 0
        self.disconnect_calls = 0

    async def connect_and_wait(self):
        """Mock connection."""
        self.connection_attempts += 1
        await asyncio.sleep(0.01)  # Simulate connection time
        self.connected = True

    async def disconnect(self):
        """Mock disconnection."""
        self.disconnect_calls += 1
        self.connected = False

    async def send_message_to_jid(self, jid: str, body: str):
        """Mock message sending."""
        if not self.connected:
            msg = "XMPP client not connected"
            raise ConnectionError(msg)

        message = {
            "to": jid,
            "body": body,
            "timestamp": asyncio.get_event_loop().time(),
        }
        self.sent_messages.append(message)

    def simulate_incoming_message(self, from_jid: str, body: str, msg_type="chat"):
        """Simulate an incoming XMPP message."""
        if self.mcp_bridge:
            asyncio.create_task(
                self.mcp_bridge.handle_incoming_xmpp_message(from_jid, body, msg_type)
            )


class InMemoryMcpBridge(McpBridge):
    """In-memory MCP bridge for integration testing."""

    def __init__(self, queue_size: int = 100, xmpp_adapter=None):
        super().__init__(queue_size)
        self.xmpp_adapter = xmpp_adapter
        self.processed_messages: list[dict[str, Any]] = []
        self.errors: list[Exception] = []

    async def _process_xmpp_to_mcp(self) -> None:
        """Process messages from XMPP to MCP queue."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.xmpp_to_mcp, timeout=0.1)
                if message:
                    self.processed_messages.append(message)
                    # Simulate MCP processing
                    await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.errors.append(e)

    async def _process_mcp_to_xmpp(self) -> None:
        """Process messages from MCP to XMPP queue."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.mcp_to_xmpp, timeout=0.1)
                if message and self.xmpp_adapter:
                    # Forward to XMPP adapter
                    await self.xmpp_adapter.send_message_to_jid(
                        message["jid"], message["body"]
                    )
                    self.processed_messages.append(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.errors.append(e)


class InMemoryMcpServer:
    """In-memory MCP server that doesn't use stdio for testing."""

    def __init__(self):
        self.running = False
        self.xmpp_adapter = None
        self.mcp_bridge = None
        self.request_handlers = {}
        self.capabilities = {
            "tools": {
                "send_message": {
                    "description": "Send a message through XMPP",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "recipient": {"type": "string"},
                            "message": {"type": "string"},
                        },
                        "required": ["recipient", "message"],
                    },
                },
                "ping": {
                    "description": "Ping the XMPP connection",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            }
        }

    async def initialize(self, jid: str, password: str):
        """Initialize with XMPP credentials."""
        self.mcp_bridge = InMemoryMcpBridge()
        self.xmpp_adapter = MockXmppAdapter(jid, password, self.mcp_bridge)
        self.mcp_bridge.xmpp_adapter = self.xmpp_adapter

    async def start(self):
        """Start the server."""
        self.running = True
        if self.mcp_bridge:
            await self.mcp_bridge.start()
        if self.xmpp_adapter:
            await self.xmpp_adapter.connect_and_wait()

    async def stop(self):
        """Stop the server."""
        self.running = False
        if self.mcp_bridge:
            await self.mcp_bridge.stop()
        if self.xmpp_adapter:
            await self.xmpp_adapter.disconnect()

    async def handle_request(self, request: JsonRpcMessage) -> JsonRpcMessage:
        """Handle JSON-RPC requests."""
        method = request.method
        params = request.params or {}

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name == "send_message":
                return await self._handle_send_message(request, arguments)
            elif tool_name == "ping":
                return await self._handle_ping(request, arguments)

        return JsonRpcMessage(
            id=request.id,
            error={"code": -32601, "message": f"Method not found: {method}"},
        )

    async def _handle_send_message(self, request: JsonRpcMessage, args: dict[str, Any]):
        """Handle send_message tool call."""
        recipient = args.get("recipient")
        message = args.get("message")

        if not recipient or not message:
            return JsonRpcMessage(
                id=request.id,
                error={"code": -32602, "message": "Missing required parameters"},
            )

        # Check connection status before attempting to send
        if not self.xmpp_adapter or not self.xmpp_adapter.connected:
            return JsonRpcMessage(
                id=request.id,
                error={
                    "code": -32603,
                    "message": "Send failed: XMPP client not connected",
                },
            )

        try:
            await self.mcp_bridge.send_to_jabber(recipient, message)
            return JsonRpcMessage(
                id=request.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": f"Message sent to {recipient}: {message}",
                        }
                    ]
                },
            )
        except Exception as e:
            return JsonRpcMessage(
                id=request.id, error={"code": -32603, "message": f"Send failed: {e}"}
            )

    async def _handle_ping(self, request: JsonRpcMessage, args: dict[str, Any]):
        """Handle ping tool call."""
        is_connected = self.xmpp_adapter and self.xmpp_adapter.connected
        return JsonRpcMessage(
            id=request.id,
            result={
                "content": [
                    {"type": "text", "text": f"PONG! XMPP connected: {is_connected}"}
                ]
            },
        )


class TestInMemoryMcpIntegration:
    """Integration tests with in-memory MCP server and mocked XMPP client."""

    @pytest.fixture
    async def mcp_system(self):
        """Create and setup the in-memory MCP system."""
        server = InMemoryMcpServer()
        await server.initialize("test@example.com", "password")
        await server.start()

        yield server

        await server.stop()

    async def test_send_message_integration(self, mcp_system):
        """Test full integration of sending message through MCP to XMPP."""
        server = mcp_system

        # Create MCP request
        request = JsonRpcMessage(
            id="test-1",
            method="tools/call",
            params={
                "name": "send_message",
                "arguments": {
                    "recipient": "friend@example.com",
                    "message": "Hello from integration test!",
                },
            },
        )

        # Handle the request
        response = await server.handle_request(request)

        # Verify successful response
        assert response.error is None
        assert response.result is not None
        assert "Message sent" in response.result["content"][0]["text"]

        # Allow message processing
        await asyncio.sleep(0.1)

        # Verify message was sent via XMPP adapter
        sent_messages = server.xmpp_adapter.sent_messages
        assert len(sent_messages) == 1
        assert sent_messages[0]["to"] == "friend@example.com"
        assert sent_messages[0]["body"] == "Hello from integration test!"

    async def test_ping_integration(self, mcp_system):
        """Test ping command integration."""
        server = mcp_system

        # Create ping request
        request = JsonRpcMessage(
            id="ping-1", method="tools/call", params={"name": "ping", "arguments": {}}
        )

        # Handle the request
        response = await server.handle_request(request)

        # Verify response
        assert response.error is None
        assert "PONG" in response.result["content"][0]["text"]
        assert "connected: True" in response.result["content"][0]["text"]

    async def test_incoming_message_handling(self, mcp_system):
        """Test handling incoming XMPP messages."""
        server = mcp_system

        # Simulate incoming message
        server.xmpp_adapter.simulate_incoming_message(
            "sender@example.com", "Hello from XMPP!", "chat"
        )

        # Allow processing
        await asyncio.sleep(0.1)

        # Verify message was processed
        processed = server.mcp_bridge.processed_messages
        incoming_messages = [
            msg for msg in processed if msg.get("type") == "received_message"
        ]

        assert len(incoming_messages) == 1
        assert incoming_messages[0]["from_jid"] == "sender@example.com"
        assert incoming_messages[0]["body"] == "Hello from XMPP!"

    async def test_bidirectional_message_flow(self, mcp_system):
        """Test bidirectional message flow."""
        server = mcp_system

        # Send outbound message
        send_request = JsonRpcMessage(
            id="out-1",
            method="tools/call",
            params={
                "name": "send_message",
                "arguments": {
                    "recipient": "contact@example.com",
                    "message": "Outbound message",
                },
            },
        )

        await server.handle_request(send_request)

        # Simulate incoming message
        server.xmpp_adapter.simulate_incoming_message(
            "contact@example.com", "Reply message", "chat"
        )

        # Allow processing
        await asyncio.sleep(0.1)

        # Verify outbound message
        sent_messages = server.xmpp_adapter.sent_messages
        assert len(sent_messages) == 1
        assert sent_messages[0]["body"] == "Outbound message"

        # Verify incoming message
        processed = server.mcp_bridge.processed_messages
        incoming = [msg for msg in processed if msg.get("type") == "received_message"]
        assert len(incoming) == 1
        assert incoming[0]["body"] == "Reply message"

    async def test_connection_management(self, mcp_system):
        """Test XMPP connection management."""
        server = mcp_system

        # Verify initial connection
        assert server.xmpp_adapter.connected
        assert server.xmpp_adapter.connection_attempts == 1

        # Test disconnection
        await server.xmpp_adapter.disconnect()
        assert not server.xmpp_adapter.connected
        assert server.xmpp_adapter.disconnect_calls == 1

        # Test reconnection
        await server.xmpp_adapter.connect_and_wait()
        assert server.xmpp_adapter.connected
        assert server.xmpp_adapter.connection_attempts == 2

    async def test_error_handling_integration(self, mcp_system):
        """Test error handling in integration scenarios."""
        server = mcp_system

        # Disconnect XMPP to cause send error
        await server.xmpp_adapter.disconnect()

        # Try to send message while disconnected
        request = JsonRpcMessage(
            id="error-1",
            method="tools/call",
            params={
                "name": "send_message",
                "arguments": {
                    "recipient": "test@example.com",
                    "message": "Should fail",
                },
            },
        )

        response = await server.handle_request(request)

        # Verify error response
        assert response.error is not None
        assert "Send failed" in response.error["message"]

    async def test_invalid_request_handling(self, mcp_system):
        """Test handling of invalid MCP requests."""
        server = mcp_system

        # Missing recipient parameter
        request = JsonRpcMessage(
            id="invalid-1",
            method="tools/call",
            params={"name": "send_message", "arguments": {"message": "No recipient"}},
        )

        response = await server.handle_request(request)

        # Verify error response
        assert response.error is not None
        assert "Missing required parameters" in response.error["message"]

    async def test_high_load_integration(self, mcp_system):
        """Test system behavior under high load."""
        server = mcp_system

        # Send many messages concurrently
        tasks = []
        for i in range(20):
            request = JsonRpcMessage(
                id=f"load-{i}",
                method="tools/call",
                params={
                    "name": "send_message",
                    "arguments": {
                        "recipient": f"user{i}@example.com",
                        "message": f"Load test message {i}",
                    },
                },
            )
            tasks.append(server.handle_request(request))

        # Execute all requests
        responses = await asyncio.gather(*tasks)

        # Verify all succeeded
        for response in responses:
            assert response.error is None

        # Allow processing
        await asyncio.sleep(0.2)

        # Verify all messages were sent
        assert len(server.xmpp_adapter.sent_messages) == 20

        # Verify no errors occurred
        assert len(server.mcp_bridge.errors) == 0
