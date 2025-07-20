"""Unit tests for inbox functionality in XmppMcpBridge."""

import asyncio
import uuid
from typing import Any

import pytest

from jabber_mcp.xmpp_mcp_server import XmppMcpBridge


class TestInboxFunctionality:
    """Test suite for inbox functionality in XmppMcpBridge."""

    @pytest.fixture
    def bridge(self):
        """Create a XmppMcpBridge instance for testing."""
        return XmppMcpBridge(queue_size=10, inbox_maxlen=5)

    def test_inbox_initialization(self, bridge):
        """Test that inbox initializes with correct configuration."""
        assert len(bridge.inbox) == 0
        assert bridge.inbox.maxlen == 5

    async def test_inbox_persistence_on_received_message(self, bridge):
        """Test that received messages are persisted to inbox."""
        # Start the bridge
        await bridge.start()

        try:
            # Simulate an incoming XMPP message
            await bridge.handle_incoming_xmpp_message(
                "sender@example.com", "Hello, this is a test message!", "chat"
            )

            # Give the processor a moment to handle the message
            await asyncio.sleep(0.1)

            # Check that the message was added to inbox
            assert len(bridge.inbox) == 1

            inbox_record = bridge.inbox[0]
            assert "uuid" in inbox_record
            assert inbox_record["from_jid"] == "sender@example.com"
            assert inbox_record["body"] == "Hello, this is a test message!"
            assert "ts" in inbox_record

        finally:
            await bridge.stop()

    async def test_inbox_deque_maxlen_behavior(self, bridge):
        """Test that inbox respects maxlen and evicts old messages."""
        # Start the bridge
        await bridge.start()

        try:
            # Send more messages than the maxlen
            for i in range(7):  # maxlen is 5, so last 5 should be kept
                await bridge.handle_incoming_xmpp_message(
                    f"user{i}@example.com", f"Message number {i}", "chat"
                )

            # Give the processor time to handle all messages
            await asyncio.sleep(0.2)

            # Should only have 5 messages (maxlen)
            assert len(bridge.inbox) == 5

            # Should have messages 2-6 (oldest two evicted)
            bodies = [record["body"] for record in bridge.inbox]
            expected_bodies = [f"Message number {i}" for i in range(2, 7)]
            assert bodies == expected_bodies

        finally:
            await bridge.stop()

    async def test_get_inbox_list(self, bridge):
        """Test getting list of inbox messages."""
        # Add some test messages directly to inbox
        for i in range(3):
            bridge.inbox.append(
                {
                    "uuid": str(uuid.uuid4()),
                    "from_jid": f"user{i}@example.com",
                    "body": f"Message {i}",
                    "ts": 1000 + i,
                }
            )

        # Test getting all messages (should be newest first)
        messages = await bridge.get_inbox_list()
        assert len(messages) == 3
        assert messages[0]["body"] == "Message 2"  # Newest first
        assert messages[1]["body"] == "Message 1"
        assert messages[2]["body"] == "Message 0"

    async def test_get_inbox_list_with_limit(self, bridge):
        """Test getting limited list of inbox messages."""
        # Add some test messages directly to inbox
        for i in range(5):
            bridge.inbox.append(
                {
                    "uuid": str(uuid.uuid4()),
                    "from_jid": f"user{i}@example.com",
                    "body": f"Message {i}",
                    "ts": 1000 + i,
                }
            )

        # Test getting limited messages
        messages = await bridge.get_inbox_list(limit=2)
        assert len(messages) == 2
        assert messages[0]["body"] == "Message 4"  # Newest first
        assert messages[1]["body"] == "Message 3"

    async def test_get_inbox_message_by_uuid(self, bridge):
        """Test fetching specific message by UUID."""
        test_uuid = str(uuid.uuid4())

        # Add test messages
        bridge.inbox.append(
            {
                "uuid": test_uuid,
                "from_jid": "test@example.com",
                "body": "Target message",
                "ts": 1000,
            }
        )
        bridge.inbox.append(
            {
                "uuid": str(uuid.uuid4()),
                "from_jid": "other@example.com",
                "body": "Other message",
                "ts": 1001,
            }
        )

        # Test fetching by UUID
        message = await bridge.get_inbox_message(test_uuid)
        assert message is not None
        assert message["uuid"] == test_uuid
        assert message["body"] == "Target message"

        # Test fetching non-existent UUID
        missing_message = await bridge.get_inbox_message("non-existent-uuid")
        assert missing_message is None

    async def test_get_inbox_stats(self, bridge):
        """Test getting inbox statistics."""
        # Empty inbox
        stats = await bridge.get_inbox_stats()
        assert stats["total_messages"] == 0
        assert stats["max_capacity"] == 5
        assert stats["capacity_used_percent"] == 0

        # Partially filled inbox
        for i in range(3):
            bridge.inbox.append(
                {
                    "uuid": str(uuid.uuid4()),
                    "from_jid": f"user{i}@example.com",
                    "body": f"Message {i}",
                    "ts": 1000 + i,
                }
            )

        stats = await bridge.get_inbox_stats()
        assert stats["total_messages"] == 3
        assert stats["max_capacity"] == 5
        assert stats["capacity_used_percent"] == 60.0  # 3/5 * 100

    async def test_inbox_non_received_message_types_ignored(self, bridge):
        """Test that non-received_message types don't get added to inbox."""
        await bridge.start()

        try:
            # Simulate a presence update (should not be added to inbox)
            await bridge.handle_incoming_xmpp_presence(
                "user@example.com", "available", "I'm online"
            )

            # Give the processor time
            await asyncio.sleep(0.1)

            # Inbox should still be empty
            assert len(bridge.inbox) == 0

        finally:
            await bridge.stop()

    async def test_concurrent_inbox_access(self, bridge):
        """Test that inbox can be accessed concurrently without blocking."""
        # Add some test data
        for i in range(3):
            bridge.inbox.append(
                {
                    "uuid": str(uuid.uuid4()),
                    "from_jid": f"user{i}@example.com",
                    "body": f"Message {i}",
                    "ts": 1000 + i,
                }
            )

        # Simulate concurrent access
        async def access_inbox():
            messages = await bridge.get_inbox_list()
            stats = await bridge.get_inbox_stats()
            return len(messages), stats["total_messages"]

        # Run multiple concurrent accesses
        tasks = [access_inbox() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All should return the same result
        for msg_count, stats_count in results:
            assert msg_count == 3
            assert stats_count == 3

    def test_custom_inbox_maxlen(self):
        """Test creating bridge with custom inbox maxlen."""
        custom_bridge = XmppMcpBridge(inbox_maxlen=100)
        assert custom_bridge.inbox.maxlen == 100

        default_bridge = XmppMcpBridge()
        assert default_bridge.inbox.maxlen == 500  # default value
