"""Unit tests for MCP Bridge implementation."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from jabber_mcp.bridge.mcp_bridge import McpBridge


class ConcreteMcpBridge(McpBridge):
    """Concrete implementation of McpBridge for testing."""

    def __init__(self, queue_size: int = 100):
        super().__init__(queue_size)
        self.xmpp_to_mcp_messages: list[dict[str, Any]] = []
        self.mcp_to_xmpp_messages: list[dict[str, Any]] = []
        self._process_xmpp_to_mcp_mock = AsyncMock()
        self._process_mcp_to_xmpp_mock = AsyncMock()

    async def _process_xmpp_to_mcp(self) -> None:
        """Mock implementation that records processed messages."""
        await self._process_xmpp_to_mcp_mock()
        while self._running:
            try:
                message = await asyncio.wait_for(self.xmpp_to_mcp.get(), timeout=0.1)
                self.xmpp_to_mcp_messages.append(message)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _process_mcp_to_xmpp(self) -> None:
        """Mock implementation that records processed messages."""
        await self._process_mcp_to_xmpp_mock()
        while self._running:
            try:
                message = await asyncio.wait_for(self.mcp_to_xmpp.get(), timeout=0.1)
                self.mcp_to_xmpp_messages.append(message)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break


class TestMcpBridge:
    """Test suite for MCP Bridge functionality."""

    @pytest.fixture
    def bridge(self):
        """Create a concrete MCP Bridge instance for testing."""
        return ConcreteMcpBridge(queue_size=10)

    def test_bridge_initialization(self, bridge):
        """Test that bridge initializes with correct default values."""
        assert bridge.queue_size == 10
        assert bridge.xmpp_to_mcp.maxsize == 10
        assert bridge.mcp_to_xmpp.maxsize == 10
        assert not bridge.is_running
        assert bridge._tasks == []

    def test_queue_stats(self, bridge):
        """Test queue statistics reporting."""
        stats = bridge.queue_stats
        expected = {
            "xmpp_to_mcp_size": 0,
            "mcp_to_xmpp_size": 0,
            "xmpp_to_mcp_maxsize": 10,
            "mcp_to_xmpp_maxsize": 10,
        }
        assert stats == expected

    async def test_start_and_stop(self, bridge):
        """Test bridge start and stop lifecycle."""
        # Initially not running
        assert not bridge.is_running

        # Start bridge
        await bridge.start()
        assert bridge.is_running
        assert len(bridge._tasks) == 2

        # Give tasks a moment to start
        await asyncio.sleep(0.01)

        # Verify tasks were started
        bridge._process_xmpp_to_mcp_mock.assert_called_once()
        bridge._process_mcp_to_xmpp_mock.assert_called_once()

        # Stop bridge
        await bridge.stop()
        assert not bridge.is_running
        assert bridge._tasks == []

    async def test_start_when_already_running(self, bridge, caplog):
        """Test starting bridge when it's already running."""
        await bridge.start()

        # Try to start again
        with caplog.at_level("WARNING"):
            await bridge.start()

        assert "MCP Bridge is already running" in caplog.text
        await bridge.stop()

    async def test_stop_when_not_running(self, bridge, caplog):
        """Test stopping bridge when it's not running."""
        with caplog.at_level("WARNING"):
            await bridge.stop()

        assert "MCP Bridge is not running" in caplog.text

    async def test_send_to_jabber_valid_message(self, bridge):
        """Test sending valid message to Jabber."""
        await bridge.send_to_jabber("user@example.com", "Hello, World!")

        # Check message was queued
        assert bridge.mcp_to_xmpp.qsize() == 1

        message = await bridge.mcp_to_xmpp.get()
        assert message["type"] == "send_message"
        assert message["jid"] == "user@example.com"
        assert message["body"] == "Hello, World!"
        assert "timestamp" in message

    async def test_send_to_jabber_invalid_jid(self, bridge):
        """Test sending message with invalid JID."""
        with pytest.raises(ValueError, match="JID must be a non-empty string"):
            await bridge.send_to_jabber("", "Hello")

        with pytest.raises(ValueError, match="JID must be a non-empty string"):
            await bridge.send_to_jabber(None, "Hello")

    async def test_send_to_jabber_invalid_body(self, bridge):
        """Test sending message with invalid body."""
        with pytest.raises(ValueError, match="Body must be a string"):
            await bridge.send_to_jabber("user@example.com", None)

        with pytest.raises(ValueError, match="Body must be a string"):
            await bridge.send_to_jabber("user@example.com", 123)

    async def test_send_to_jabber_queue_full(self, bridge):
        """Test sending message when queue is full."""
        # Fill the queue
        for i in range(10):  # queue_size is 10
            await bridge.send_to_jabber("user@example.com", f"Message {i}")

        # Queue should be full, next message should raise QueueFull
        with pytest.raises(asyncio.QueueFull):
            bridge.mcp_to_xmpp.put_nowait({"test": "overflow"})

    async def test_handle_incoming_xmpp_message(self, bridge):
        """Test handling incoming XMPP messages."""
        await bridge.handle_incoming_xmpp_message(
            "sender@example.com", "Hello from XMPP!", "chat"
        )

        assert bridge.xmpp_to_mcp.qsize() == 1

        message = await bridge.xmpp_to_mcp.get()
        assert message["type"] == "received_message"
        assert message["from_jid"] == "sender@example.com"
        assert message["body"] == "Hello from XMPP!"
        assert message["message_type"] == "chat"
        assert "timestamp" in message

    async def test_handle_incoming_xmpp_presence(self, bridge):
        """Test handling incoming XMPP presence updates."""
        await bridge.handle_incoming_xmpp_presence(
            "user@example.com", "available", "I'm online!"
        )

        assert bridge.xmpp_to_mcp.qsize() == 1

        presence = await bridge.xmpp_to_mcp.get()
        assert presence["type"] == "presence_update"
        assert presence["jid"] == "user@example.com"
        assert presence["presence_type"] == "available"
        assert presence["status"] == "I'm online!"
        assert "timestamp" in presence

    async def test_callback_setters(self, bridge):
        """Test setting XMPP callbacks."""

        def message_callback(msg):
            pass

        def presence_callback(pres):
            pass

        bridge.set_xmpp_message_callback(message_callback)
        bridge.set_xmpp_presence_callback(presence_callback)

        assert bridge._xmpp_message_callback == message_callback
        assert bridge._xmpp_presence_callback == presence_callback

    async def test_long_message_truncation_in_logs(self, bridge, caplog):
        """Test that long messages are truncated in debug logs."""
        long_message = "x" * 200  # 200 characters

        with caplog.at_level("DEBUG"):
            await bridge.send_to_jabber("user@example.com", long_message)

        # Should truncate message in logs but preserve full message in queue
        message = await bridge.mcp_to_xmpp.get()
        assert message["body"] == long_message  # Full message preserved
        assert "xxx..." in caplog.text  # Truncated in logs

    async def test_message_processing_integration(self, bridge):
        """Test integration of message processing tasks."""
        await bridge.start()

        # Send some messages
        await bridge.send_to_jabber("user1@example.com", "Message 1")
        await bridge.handle_incoming_xmpp_message("user2@example.com", "Message 2")

        # Give tasks time to process
        await asyncio.sleep(0.2)

        # Check messages were processed
        assert len(bridge.mcp_to_xmpp_messages) == 1
        assert len(bridge.xmpp_to_mcp_messages) == 1

        assert bridge.mcp_to_xmpp_messages[0]["jid"] == "user1@example.com"
        assert bridge.xmpp_to_mcp_messages[0]["from_jid"] == "user2@example.com"

        await bridge.stop()

    def test_default_queue_size(self):
        """Test default queue size initialization."""
        bridge = ConcreteMcpBridge()  # No queue_size specified
        assert bridge.queue_size == 100
        assert bridge.xmpp_to_mcp.maxsize == 100
        assert bridge.mcp_to_xmpp.maxsize == 100
