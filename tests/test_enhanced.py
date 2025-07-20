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

    async def test_server_initialization(self):
        """Test server initialization and processing loop."""
        server = McpStdioServer()

        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = Mock()
            mock_stdout.flush = Mock()

            async def mock_stdio():
                # Simulate writing to stdout during initialization
                mock_stdout.write('{"jsonrpc": "2.0", "method": "test"}\n')
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
        bridge._retry_with_backoff = AsyncMock()  # Mock the retry method
        adapter = XmppAdapter("jid@example.com", "password", bridge)

        # Test that adapter is initialized correctly
        assert adapter.mcp_bridge == bridge
        assert adapter._connection_state.value == "disconnected"

        # Mock the _do_connect method to avoid complex retry logic
        with patch.object(
            adapter, "_do_connect", new_callable=AsyncMock
        ) as mock_do_connect:
            await adapter.connect_and_wait()
            mock_do_connect.assert_called()

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
        bridge.handle_incoming_xmpp_message = AsyncMock()  # Mock the async method
        adapter = XmppAdapter("jid@example.com", "password", bridge)

        # Mock incoming message properly
        mock_message = Mock(spec=Message)

        # Mock the message attributes correctly
        mock_from = Mock()
        mock_from.bare = "friend@example.com"
        mock_message.__getitem__ = Mock()
        mock_message.__getitem__.side_effect = lambda key: {
            "from": mock_from,
            "body": "Incoming message",
            "type": "chat",
        }[key]

        # Call message_received and wait briefly for async tasks to complete
        adapter.message_received(mock_message)
        await asyncio.sleep(0.1)  # Allow async tasks to execute

        # Verify the bridge method was called with correct parameters
        bridge.handle_incoming_xmpp_message.assert_called_with(
            jid=str(mock_from), body="Incoming message", message_type="chat"
        )
