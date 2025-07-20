"""Unit tests for queue operations, performance, and advanced MCP bridge functionality."""

import asyncio
import logging
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock

import pytest

from jabber_mcp.bridge.mcp_bridge import McpBridge, RetryConfig


class AdvancedMockMcpBridge(McpBridge):
    """Mock MCP bridge with advanced queue monitoring and testing capabilities."""

    def __init__(self, queue_size: int = 10):
        super().__init__(queue_size)
        self.xmpp_to_mcp_messages: List[Dict[str, Any]] = []
        self.mcp_to_xmpp_messages: List[Dict[str, Any]] = []
        self.processing_delays = {"xmpp_to_mcp": 0.0, "mcp_to_xmpp": 0.0}
        self.processing_errors = {"xmpp_to_mcp": None, "mcp_to_xmpp": None}
        self.call_counts = {"xmpp_to_mcp": 0, "mcp_to_xmpp": 0}

    def set_processing_delay(self, queue_name: str, delay: float):
        """Set artificial delay for testing performance."""
        self.processing_delays[queue_name] = delay

    def set_processing_error(self, queue_name: str, error: Exception):
        """Set error to be raised during processing."""
        self.processing_errors[queue_name] = error

    async def _process_xmpp_to_mcp(self) -> None:
        """Mock implementation with configurable behavior."""
        while self._running:
            self.call_counts["xmpp_to_mcp"] += 1
            try:
                if self.processing_errors["xmpp_to_mcp"]:
                    raise self.processing_errors["xmpp_to_mcp"]

                if self.processing_delays["xmpp_to_mcp"]:
                    await asyncio.sleep(self.processing_delays["xmpp_to_mcp"])

                message = await self._safe_queue_get(self.xmpp_to_mcp, timeout=0.1)
                if message:
                    self.xmpp_to_mcp_messages.append(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in xmpp_to_mcp processing: {e}")
                await asyncio.sleep(0.01)  # Brief delay before retry

    async def _process_mcp_to_xmpp(self) -> None:
        """Mock implementation with configurable behavior."""
        while self._running:
            self.call_counts["mcp_to_xmpp"] += 1
            try:
                if self.processing_errors["mcp_to_xmpp"]:
                    raise self.processing_errors["mcp_to_xmpp"]

                if self.processing_delays["mcp_to_xmpp"]:
                    await asyncio.sleep(self.processing_delays["mcp_to_xmpp"])

                message = await self._safe_queue_get(self.mcp_to_xmpp, timeout=0.1)
                if message:
                    self.mcp_to_xmpp_messages.append(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in mcp_to_xmpp processing: {e}")
                await asyncio.sleep(0.01)  # Brief delay before retry


class TestQueuePerformance:
    """Test queue performance and throughput."""

    @pytest.fixture
    def bridge(self):
        return AdvancedMockMcpBridge(queue_size=100)

    async def test_high_throughput_message_processing(self, bridge):
        """Test processing high volume of messages."""
        await bridge.start()

        # Send many messages rapidly
        message_count = 50
        start_time = time.time()

        tasks = []
        for i in range(message_count):
            tasks.append(bridge.send_to_jabber(f"user{i}@example.com", f"Message {i}"))

        await asyncio.gather(*tasks)
        send_time = time.time() - start_time

        # Allow processing time
        await asyncio.sleep(0.5)

        await bridge.stop()

        # Verify all messages were processed
        assert len(bridge.mcp_to_xmpp_messages) == message_count

        # Verify performance (should be much faster than 1 msg/sec)
        assert send_time < message_count * 0.1  # At least 10 msg/sec

        # Verify message ordering is preserved (first few and last few)
        assert bridge.mcp_to_xmpp_messages[0]["jid"] == "user0@example.com"
        assert "Message 0" in bridge.mcp_to_xmpp_messages[0]["body"]
        assert (
            f"user{message_count - 1}@example.com"
            in bridge.mcp_to_xmpp_messages[-1]["jid"]
        )

    async def test_concurrent_bidirectional_message_flow(self, bridge):
        """Test concurrent messages in both directions."""
        await bridge.start()

        # Send messages in both directions concurrently
        async def send_outbound():
            for i in range(25):
                await bridge.send_to_jabber(f"out{i}@example.com", f"Outbound {i}")

        async def send_inbound():
            for i in range(25):
                await bridge.handle_incoming_xmpp_message(
                    f"in{i}@example.com", f"Inbound {i}", "chat"
                )

        await asyncio.gather(send_outbound(), send_inbound())

        # Allow processing
        await asyncio.sleep(0.3)
        await bridge.stop()

        # Verify both directions processed correctly
        assert len(bridge.mcp_to_xmpp_messages) == 25
        assert len(bridge.xmpp_to_mcp_messages) == 25

        # Verify message types
        outbound_jids = [msg["jid"] for msg in bridge.mcp_to_xmpp_messages]
        inbound_jids = [msg["from_jid"] for msg in bridge.xmpp_to_mcp_messages]

        assert any("out" in jid for jid in outbound_jids)
        assert any("in" in jid for jid in inbound_jids)


class TestQueueErrorHandling:
    """Test queue error handling and recovery."""

    @pytest.fixture
    def bridge(self):
        return AdvancedMockMcpBridge(queue_size=10)

    async def test_processing_error_recovery(self, bridge, caplog):
        """Test that processing continues after errors."""
        # Set up to cause errors in processing
        bridge.set_processing_error("xmpp_to_mcp", ValueError("Test error"))

        await bridge.start()

        # Send some messages
        await bridge.handle_incoming_xmpp_message(
            "user1@example.com", "Message 1", "chat"
        )
        await bridge.handle_incoming_xmpp_message(
            "user2@example.com", "Message 2", "chat"
        )

        # Allow processing (with errors)
        with caplog.at_level(logging.ERROR):
            await asyncio.sleep(0.2)

        # Clear the error and send more messages
        bridge.set_processing_error("xmpp_to_mcp", None)
        await bridge.handle_incoming_xmpp_message(
            "user3@example.com", "Message 3", "chat"
        )

        # Allow recovery
        await asyncio.sleep(0.2)
        await bridge.stop()

        # Should have error logs
        assert any(
            "Error in xmpp_to_mcp processing" in record.message
            for record in caplog.records
            if record.levelno >= logging.ERROR
        )

        # Should continue calling processing method despite errors
        assert bridge.call_counts["xmpp_to_mcp"] > 1


class TestAdvancedQueueOperations:
    """Test advanced queue operations and edge cases."""

    @pytest.fixture
    def bridge(self):
        return AdvancedMockMcpBridge(queue_size=20)

    async def test_queue_stats_accuracy(self, bridge):
        """Test that queue statistics are accurate."""
        # Initially empty
        stats = bridge.queue_stats
        assert stats["xmpp_to_mcp_size"] == 0
        assert stats["mcp_to_xmpp_size"] == 0

        # Add some messages without processing
        await bridge.send_to_jabber("user1@example.com", "Test 1")
        await bridge.send_to_jabber("user2@example.com", "Test 2")
        await bridge.handle_incoming_xmpp_message("user3@example.com", "Test 3", "chat")

        # Check stats
        stats = bridge.queue_stats
        assert stats["mcp_to_xmpp_size"] == 2
        assert stats["xmpp_to_mcp_size"] == 1
        assert stats["xmpp_to_mcp_maxsize"] == 20
        assert stats["mcp_to_xmpp_maxsize"] == 20

        # Start processing and check stats change
        await bridge.start()
        await asyncio.sleep(0.1)

        stats = bridge.queue_stats
        assert stats["mcp_to_xmpp_size"] == 0  # Should be drained
        assert stats["xmpp_to_mcp_size"] == 0  # Should be drained

        await bridge.stop()
