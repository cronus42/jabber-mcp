"""Integration tests for XMPP-to-inbox message flow using fake XmppAdapter."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jabber_mcp.xmpp_adapter import XmppAdapter
from jabber_mcp.xmpp_mcp_server import XmppMcpBridge


class FakeXmppAdapter:
    """Fake XmppAdapter for testing message injection."""

    def __init__(self):
        self.connected = False
        self.messages_sent = []
        self.message_callback = None
        self.presence_callback = None

    def set_message_callback(self, callback):
        """Set callback for incoming messages."""
        self.message_callback = callback

    def set_presence_callback(self, callback):
        """Set callback for incoming presence updates."""
        self.presence_callback = callback

    async def connect(self):
        """Fake connect method."""
        self.connected = True

    async def disconnect(self):
        """Fake disconnect method."""
        self.connected = False

    async def send_message_to_jid(self, jid: str, body: str):
        """Fake send message method."""
        self.messages_sent.append({"jid": jid, "body": body})

    async def inject_incoming_message(self, from_jid: str, body: str):
        """Inject a fake incoming message for testing."""
        if self.message_callback:
            await self.message_callback(from_jid, body)

    async def inject_presence_update(
        self, from_jid: str, presence_type: str, status: str | None = None
    ):
        """Inject a fake presence update for testing."""
        if self.presence_callback:
            await self.presence_callback(from_jid, presence_type, status)


@pytest.fixture
async def fake_bridge():
    """Create XmppMcpBridge with fake XMPP adapter."""
    fake_adapter = FakeXmppAdapter()
    bridge = XmppMcpBridge(queue_size=10, inbox_maxlen=5)
    bridge.set_xmpp_adapter(fake_adapter)

    # Set up callbacks
    fake_adapter.set_message_callback(bridge.handle_incoming_xmpp_message)
    fake_adapter.set_presence_callback(bridge.handle_incoming_xmpp_presence)

    # Start the bridge
    await bridge.start()

    yield bridge, fake_adapter

    # Cleanup
    await bridge.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_injection_to_inbox(fake_bridge):
    """Test that injected XMPP messages appear in the inbox."""
    bridge, fake_adapter = fake_bridge

    # Initially inbox should be empty
    inbox_list = await bridge.get_inbox_list()
    assert len(inbox_list) == 0

    # Inject a message
    await fake_adapter.inject_incoming_message("test@example.org", "Hello from test!")

    # Give the bridge processing task time to handle the message
    await asyncio.sleep(0.1)

    # Check that message appears in inbox
    inbox_list = await bridge.get_inbox_list()
    assert len(inbox_list) == 1
    assert inbox_list[0]["from_jid"] == "test@example.org"
    assert inbox_list[0]["body"] == "Hello from test!"
    assert inbox_list[0]["uuid"] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multiple_message_injection(fake_bridge):
    """Test multiple message injections."""
    bridge, fake_adapter = fake_bridge

    # Inject multiple messages
    messages = [
        ("alice@example.org", "Message 1"),
        ("bob@example.org", "Message 2"),
        ("charlie@example.org", "Message 3"),
    ]

    for from_jid, body in messages:
        await fake_adapter.inject_incoming_message(from_jid, body)
        await asyncio.sleep(0.05)  # Small delay between injections

    # Give processing time
    await asyncio.sleep(0.1)

    # Check all messages are in inbox (newest first)
    inbox_list = await bridge.get_inbox_list()
    assert len(inbox_list) == 3

    # Messages should be in reverse order (newest first)
    assert inbox_list[0]["from_jid"] == "charlie@example.org"
    assert inbox_list[1]["from_jid"] == "bob@example.org"
    assert inbox_list[2]["from_jid"] == "alice@example.org"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_inbox_overflow_with_injection(fake_bridge):
    """Test that inbox respects maxlen when messages are injected."""
    bridge, fake_adapter = fake_bridge

    # Inject more messages than inbox capacity (maxlen=5)
    for i in range(7):
        await fake_adapter.inject_incoming_message(
            f"user{i}@example.org", f"Message {i}"
        )
        await asyncio.sleep(0.02)

    # Give processing time
    await asyncio.sleep(0.2)

    # Should only keep the last 5 messages
    inbox_list = await bridge.get_inbox_list()
    assert len(inbox_list) == 5

    # Should have messages 2-6 (newest first)
    for i, message in enumerate(inbox_list):
        expected_idx = 6 - i  # 6, 5, 4, 3, 2
        assert message["from_jid"] == f"user{expected_idx}@example.org"
        assert message["body"] == f"Message {expected_idx}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_retrieval_by_uuid(fake_bridge):
    """Test retrieving specific message by UUID after injection."""
    bridge, fake_adapter = fake_bridge

    # Inject a message
    await fake_adapter.inject_incoming_message("test@example.org", "Unique message")
    await asyncio.sleep(0.1)

    # Get the UUID from inbox list
    inbox_list = await bridge.get_inbox_list()
    assert len(inbox_list) == 1
    message_uuid = inbox_list[0]["uuid"]

    # Retrieve message by UUID
    retrieved = await bridge.get_inbox_message(message_uuid)
    assert retrieved is not None
    assert retrieved["from_jid"] == "test@example.org"
    assert retrieved["body"] == "Unique message"
    assert retrieved["uuid"] == message_uuid


@pytest.mark.asyncio
@pytest.mark.integration
async def test_send_message_via_fake_adapter(fake_bridge):
    """Test sending messages through the fake adapter."""
    bridge, fake_adapter = fake_bridge

    # Send a message through the bridge
    await bridge.send_to_jabber("recipient@example.org", "Hello from bridge!")

    # Give processing time
    await asyncio.sleep(0.1)

    # Check that fake adapter received the message
    assert len(fake_adapter.messages_sent) == 1
    sent_message = fake_adapter.messages_sent[0]
    assert sent_message["jid"] == "recipient@example.org"
    assert sent_message["body"] == "Hello from bridge!"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_presence_injection(fake_bridge):
    """Test that presence updates are handled correctly."""
    bridge, fake_adapter = fake_bridge

    # Inject a presence update
    await fake_adapter.inject_presence_update(
        "user@example.org", "available", "I'm online"
    )

    # Give processing time
    await asyncio.sleep(0.1)

    # Check that presence update was processed (should be in received_messages)
    assert len(bridge.received_messages) >= 1

    # Find the presence message
    presence_message = None
    for msg in bridge.received_messages:
        if msg.get("type") == "presence_update":
            presence_message = msg
            break

    assert presence_message is not None
    assert presence_message["jid"] == "user@example.org"
    assert presence_message["presence_type"] == "available"
    assert presence_message["status"] == "I'm online"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_message_injection(fake_bridge):
    """Test concurrent message injection for thread safety."""
    bridge, fake_adapter = fake_bridge

    async def inject_messages(sender_id: int, count: int):
        """Inject multiple messages from a sender."""
        for i in range(count):
            await fake_adapter.inject_incoming_message(
                f"sender{sender_id}@example.org", f"Message {i} from sender {sender_id}"
            )
            await asyncio.sleep(0.01)

    # Run multiple injection tasks concurrently
    tasks = [inject_messages(i, 3) for i in range(3)]
    await asyncio.gather(*tasks)

    # Give processing time
    await asyncio.sleep(0.2)

    # Should have received all 9 messages, but inbox limited to 5
    inbox_list = await bridge.get_inbox_list()
    assert len(inbox_list) == 5  # Limited by maxlen

    # All messages should have valid structure
    for message in inbox_list:
        assert "uuid" in message
        assert "from_jid" in message
        assert "body" in message
        assert "ts" in message
        assert "@example.org" in message["from_jid"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_inbox_stats_after_injection(fake_bridge):
    """Test inbox statistics after message injection."""
    bridge, fake_adapter = fake_bridge

    # Initially empty
    stats = await bridge.get_inbox_stats()
    assert stats["total_messages"] == 0

    # Inject some messages
    for i in range(3):
        await fake_adapter.inject_incoming_message(
            f"user{i}@example.org", f"Message {i}"
        )
        await asyncio.sleep(0.02)

    await asyncio.sleep(0.1)

    # Check stats
    stats = await bridge.get_inbox_stats()
    assert stats["total_messages"] == 3
    assert stats["max_capacity"] == 5
    assert stats["capacity_used_percent"] == 60.0  # 3/5 * 100
