"""Integration tests for XmppAdapter with McpBridge wiring."""

import asyncio
import unittest
from unittest.mock import MagicMock, Mock

import pytest

from jabber_mcp.bridge.mcp_bridge import McpBridge
from jabber_mcp.xmpp_adapter import XmppAdapter


class MockMcpBridge(McpBridge):
    """Mock implementation of McpBridge for testing."""

    def __init__(self, queue_size: int = 100):
        super().__init__(queue_size)
        self.processed_xmpp_messages = []
        self.processed_mcp_messages = []

    async def _process_xmpp_to_mcp(self) -> None:
        """Process messages from XMPP to MCP queue."""
        while self._running:
            try:
                message = await self.xmpp_to_mcp.get()
                self.processed_xmpp_messages.append(message)
                self.xmpp_to_mcp.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _process_mcp_to_xmpp(self) -> None:
        """Process messages from MCP to XMPP queue."""
        while self._running:
            try:
                message = await self.mcp_to_xmpp.get()
                self.processed_mcp_messages.append(message)
                self.mcp_to_xmpp.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                pass


class TestXmppMcpIntegration:
    """Test integration between XmppAdapter and McpBridge."""

    @pytest.mark.asyncio
    async def test_xmpp_adapter_with_mcp_bridge_initialization(self):
        """Test XmppAdapter initialization with McpBridge."""
        mock_bridge = MockMcpBridge()
        adapter = XmppAdapter("test@example.com", "password", mcp_bridge=mock_bridge)

        assert adapter.mcp_bridge is mock_bridge
        assert adapter._outbound_task is not None

        # Clean up
        if adapter._outbound_task and not adapter._outbound_task.done():
            adapter._outbound_task.cancel()
            try:
                await adapter._outbound_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_incoming_message_enqueued_to_mcp(self):
        """Test that incoming XMPP messages are enqueued to MCP bridge."""
        mock_bridge = MockMcpBridge()
        await mock_bridge.start()

        adapter = XmppAdapter("test@example.com", "password", mcp_bridge=mock_bridge)

        # Create mock message
        mock_msg = Mock()
        mock_msg.__getitem__ = Mock(
            side_effect=lambda key: {
                "from": "sender@example.com",
                "body": "Hello, world!",
                "type": "chat",
            }[key]
        )

        # Process the message
        await adapter._enqueue_to_mcp(mock_msg)

        # Wait a bit for async processing
        await asyncio.sleep(0.1)

        # Verify message was enqueued
        assert len(mock_bridge.processed_xmpp_messages) == 1
        processed_msg = mock_bridge.processed_xmpp_messages[0]
        assert processed_msg["type"] == "received_message"
        assert processed_msg["from_jid"] == "sender@example.com"
        assert processed_msg["body"] == "Hello, world!"
        assert processed_msg["message_type"] == "chat"

        await mock_bridge.stop()

    @pytest.mark.asyncio
    async def test_outbound_message_processed_from_mcp(self):
        """Test that outbound MCP messages are sent via XMPP."""

        class NoOpMcpBridge(McpBridge):
            """MCP Bridge that doesn't interfere with the adapter's outbound processing."""

            async def _process_xmpp_to_mcp(self) -> None:
                # Just consume messages but don't do anything
                while self._running:
                    try:
                        await self.xmpp_to_mcp.get()
                        self.xmpp_to_mcp.task_done()
                    except asyncio.CancelledError:
                        break

            async def _process_mcp_to_xmpp(self) -> None:
                # Don't consume from mcp_to_xmpp - let the XmppAdapter handle it
                while self._running:
                    try:
                        await asyncio.sleep(0.1)
                    except asyncio.CancelledError:
                        break

        mock_bridge = NoOpMcpBridge(queue_size=100)

        # Create adapter
        adapter = XmppAdapter("test@example.com", "password", mcp_bridge=mock_bridge)

        # Mock the send_message_to_jid method (not send_message)
        from unittest.mock import AsyncMock

        adapter.send_message_to_jid = AsyncMock()

        # Queue a message in the MCP to XMPP queue
        await mock_bridge.send_to_jabber("recipient@example.com", "Hello from MCP!")

        # Allow some time for processing
        await asyncio.sleep(0.2)

        # Clean up outbound task
        if adapter._outbound_task and not adapter._outbound_task.done():
            adapter._outbound_task.cancel()
            try:
                await adapter._outbound_task
            except asyncio.CancelledError:
                pass

        # Verify that the XmppAdapter's outbound processor handled the message
        adapter.send_message_to_jid.assert_called_once_with(
            "recipient@example.com", "Hello from MCP!"
        )

    @pytest.mark.asyncio
    async def test_message_received_handler_with_bridge(self):
        """Test message_received handler with MCP bridge."""
        mock_bridge = MockMcpBridge()
        await mock_bridge.start()

        adapter = XmppAdapter("test@example.com", "password", mcp_bridge=mock_bridge)

        # Create mock message
        mock_msg = Mock()
        mock_msg.__getitem__ = Mock(
            side_effect=lambda key: {
                "from": "sender@example.com",
                "body": "Test message",
                "type": "chat",
            }[key]
        )

        # Call message_received handler
        adapter.message_received(mock_msg)

        # Wait for async processing
        await asyncio.sleep(0.1)

        # Verify message was enqueued to MCP bridge
        assert len(mock_bridge.processed_xmpp_messages) == 1

        await mock_bridge.stop()

    @pytest.mark.asyncio
    async def test_message_received_without_bridge(self):
        """Test message_received handler without MCP bridge."""
        adapter = XmppAdapter("test@example.com", "password")

        # Create mock message
        mock_msg = Mock()
        mock_msg.__getitem__ = Mock(
            side_effect=lambda key: {
                "from": "sender@example.com",
                "body": "Test message",
                "type": "chat",
            }[key]
        )

        # Call message_received handler - should not raise any errors
        adapter.message_received(mock_msg)

        # Wait for async processing
        await asyncio.sleep(0.1)

        # No exception should be raised
        assert adapter.mcp_bridge is None

    @pytest.mark.asyncio
    async def test_disconnect_cleanup(self):
        """Test that disconnect properly cleans up outbound processing task."""
        mock_bridge = MockMcpBridge()
        adapter = XmppAdapter("test@example.com", "password", mcp_bridge=mock_bridge)

        # Mock the parent disconnect method
        adapter.__class__.__bases__[0].disconnect = Mock(
            return_value=asyncio.create_task(asyncio.sleep(0))
        )

        # Ensure outbound task is running
        assert adapter._outbound_task is not None
        assert not adapter._outbound_task.done()

        # Call disconnect
        await adapter.disconnect()

        # Verify outbound task was cancelled
        assert adapter._outbound_task.done()
        assert adapter._outbound_task.cancelled()
