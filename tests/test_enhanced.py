"""Enhanced tests for MCP stdio server and XMPP adapter."""

import asyncio
import json
import sys
from typing import Any, Dict
from unittest.mock import ANY, AsyncMock, Mock, patch

import pytest
from slixmpp import Message

from jabber_mcp.mcp_stdio_server import JsonRpcMessage, McpStdioServer
from jabber_mcp.xmpp_adapter import XmppAdapter


@pytest.mark.asyncio
class TestMcpStdioServer:
    """Test cases for MCP stdio server."""

    @patch("sys.stdout")
    async def test_server_initialization(self, mock_stdout):
        """Test server initialization and processing loop."""
        server = McpStdioServer()

        async def mock_stdio():
            server.running = False  # Stop server from running indefinitely

        # Patch the _process_stdio to prevent it from blocking
        with patch.object(server, "_process_stdio", new=mock_stdio):
            await server.start()

        assert not server.running, "Server should not be running"
        assert mock_stdout.write.called, "Output should be written to stdout"

    async def test_process_valid_message(self):
        """Test processing a valid JSON-RPC message."""
        server = McpStdioServer()
        json_message = json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1})

        msg = JsonRpcMessage.from_json(json_message)
        response = await server._handle_message(msg)
        assert response.result is not None, "Response should contain result"
        assert "tools" in response.result.keys(), "Response should contain tools list"

    async def test_handle_invalid_json(self):
        """Test handling of invalid JSON data."""
        from jabber_mcp.mcp_stdio_server import JsonRpcMessage

        McpStdioServer()
        invalid_json = "{ invalid: }"

        with pytest.raises(ValueError, match="Invalid JSON-RPC message"):
            JsonRpcMessage.from_json(invalid_json)

    async def test_initialize_request(self):
        """Test handling of initialize request."""
        server = McpStdioServer()
        message = JsonRpcMessage(
            id=1,
            method="initialize",
            params={"clientInfo": {"name": "mock-client", "version": "1.0"}},
        )

        response = await server._handle_initialize(message, message.params)
        assert response.result is not None
        assert "capabilities" in response.result
        assert "serverInfo" in response.result


@pytest.mark.asyncio
class TestXmppAdapter:
    """Enhanced tests for XMPP adapter edge cases."""

    async def test_initialization(self):
        """Test initialization and session start."""
        bridge = Mock()
        adapter = XmppAdapter("jid@example.com", "password", bridge)

        # Mock start function and event handlers
        with patch.object(adapter, "process") as mock_process:
            await adapter.connect_and_wait()
            mock_process.assert_called()

    async def test_send_message(self):
        """Test sending message using JID."""
        bridge = Mock()
        adapter = XmppAdapter("jid@example.com", "password", bridge)

        # Mock sending message
        with patch.object(adapter, "send_message") as mock_send:
            await adapter.send_message_to_jid("recipient@example.com", "Hello!")
            mock_send.assert_called_with(mto=ANY, mbody="Hello!", mtype="chat")

    async def test_incoming_message_processing(self):
        """Test processing incoming message via bridge."""
        bridge = Mock()
        adapter = XmppAdapter("jid@example.com", "password", bridge)

        # Mock incoming message
        mock_message = Mock(spec=Message)
        mock_message["from"].bare = "friend@example.com"
        mock_message["body"] = "Incoming message"
        mock_message["type"] = "chat"

        # Patch and verify message processing
        with patch.object(bridge, "handle_incoming_xmpp_message") as mock_handle:
            adapter.message_received(mock_message)
            mock_handle.assert_called_with(
                "friend@example.com", "Incoming message", "chat"
            )
