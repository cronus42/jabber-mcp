"""Tests for inbox limits and message management functionality."""

import asyncio
import uuid
from collections import deque

import pytest

from jabber_mcp.xmpp_mcp_server import XmppMcpBridge


@pytest.fixture
def bridge():
    """Create XmppMcpBridge with small inbox for testing."""
    return XmppMcpBridge(queue_size=10, inbox_maxlen=3)


@pytest.mark.asyncio
async def test_inbox_maxlen_enforcement(bridge):
    """Test that inbox enforces maximum length by dropping oldest messages."""
    # Fill inbox beyond capacity
    for i in range(5):
        message = {
            "uuid": str(uuid.uuid4()),
            "from_jid": f"test{i}@example.org",
            "body": f"Message {i}",
            "ts": 1000 + i,
        }
        async with bridge._inbox_lock:
            bridge.inbox.append(message)

    # Should only keep the last 3 messages
    assert len(bridge.inbox) == 3

    # Check that only the newest messages remain
    inbox_list = await bridge.get_inbox_list()
    assert len(inbox_list) == 3
    assert inbox_list[0]["body"] == "Message 4"  # newest first
    assert inbox_list[1]["body"] == "Message 3"
    assert inbox_list[2]["body"] == "Message 2"


@pytest.mark.asyncio
async def test_get_inbox_list_limit(bridge):
    """Test that get_inbox_list respects limit parameter."""
    # Add some messages
    for i in range(3):
        message = {
            "uuid": str(uuid.uuid4()),
            "from_jid": f"test{i}@example.org",
            "body": f"Message {i}",
            "ts": 1000 + i,
        }
        async with bridge._inbox_lock:
            bridge.inbox.append(message)

    # Test limit functionality
    inbox_list = await bridge.get_inbox_list(limit=2)
    assert len(inbox_list) == 2
    assert inbox_list[0]["body"] == "Message 2"  # newest first


@pytest.mark.asyncio
async def test_get_inbox_message_by_uuid(bridge):
    """Test fetching specific message by UUID."""
    message_uuid = str(uuid.uuid4())
    message = {
        "uuid": message_uuid,
        "from_jid": "test@example.org",
        "body": "Test message",
        "ts": 1000,
    }

    async with bridge._inbox_lock:
        bridge.inbox.append(message)

    # Test successful retrieval
    found = await bridge.get_inbox_message(message_uuid)
    assert found is not None
    assert found["body"] == "Test message"

    # Test non-existent UUID
    not_found = await bridge.get_inbox_message("non-existent-uuid")
    assert not_found is None


@pytest.mark.asyncio
async def test_inbox_stats(bridge):
    """Test inbox statistics functionality."""
    # Start with empty inbox
    stats = await bridge.get_inbox_stats()
    assert stats["total_messages"] == 0
    assert stats["max_capacity"] == 3
    assert stats["capacity_used_percent"] == 0

    # Add messages and check stats
    for i in range(2):
        message = {
            "uuid": str(uuid.uuid4()),
            "from_jid": f"test{i}@example.org",
            "body": f"Message {i}",
            "ts": 1000 + i,
        }
        async with bridge._inbox_lock:
            bridge.inbox.append(message)

    stats = await bridge.get_inbox_stats()
    assert stats["total_messages"] == 2
    assert stats["max_capacity"] == 3
    assert abs(stats["capacity_used_percent"] - 66.67) < 0.01


@pytest.mark.asyncio
async def test_clear_inbox(bridge):
    """Test clearing the inbox."""
    # Add some messages
    for i in range(2):
        message = {
            "uuid": str(uuid.uuid4()),
            "from_jid": f"test{i}@example.org",
            "body": f"Message {i}",
            "ts": 1000 + i,
        }
        async with bridge._inbox_lock:
            bridge.inbox.append(message)

    # Clear inbox
    cleared_count = await bridge.clear_inbox()
    assert cleared_count == 2
    assert len(bridge.inbox) == 0

    # Test clearing empty inbox
    cleared_count = await bridge.clear_inbox()
    assert cleared_count == 0


@pytest.mark.asyncio
async def test_thread_safety(bridge):
    """Test thread safety of inbox operations."""

    async def add_message(i):
        message = {
            "uuid": str(uuid.uuid4()),
            "from_jid": f"test{i}@example.org",
            "body": f"Message {i}",
            "ts": 1000 + i,
        }
        async with bridge._inbox_lock:
            bridge.inbox.append(message)

    # Add messages concurrently
    tasks = [add_message(i) for i in range(5)]
    await asyncio.gather(*tasks)

    # Should have at most 3 messages due to maxlen
    assert len(bridge.inbox) <= 3

    # All operations should be consistent
    inbox_list = await bridge.get_inbox_list()
    stats = await bridge.get_inbox_stats()
    assert len(inbox_list) == stats["total_messages"]


@pytest.mark.asyncio
async def test_inbox_deque_behavior():
    """Test the underlying deque behavior for inbox."""
    # Test deque maxlen behavior directly
    inbox = deque(maxlen=3)

    # Add more items than maxlen
    for i in range(5):
        inbox.append(f"item_{i}")

    # Should contain only the last 3 items
    assert len(inbox) == 3
    assert list(inbox) == ["item_2", "item_3", "item_4"]

    # Adding one more should drop the oldest
    inbox.append("item_5")
    assert list(inbox) == ["item_3", "item_4", "item_5"]
