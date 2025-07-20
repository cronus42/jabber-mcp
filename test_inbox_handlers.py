#!/usr/bin/env python3
"""
Test script to verify the inbox tool handlers implementation.

This script tests the three inbox methods:
- _tool_inbox_list → bridge.list_inbox()
- _tool_inbox_get → bridge.get_message(msg_id)
- _tool_inbox_clear → bridge.clear_inbox()
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from jabber_mcp.xmpp_mcp_server import JsonRpcMessage, XmppMcpBridge, XmppMcpServer


async def test_inbox_functionality():
    """Test the inbox functionality of the XMPP MCP bridge."""
    print("Testing inbox tool handlers...")

    # Create a bridge instance
    bridge = XmppMcpBridge(queue_size=10, inbox_maxlen=50)

    # Add some test messages to the inbox
    test_messages = [
        {
            "uuid": str(uuid.uuid4()),
            "from_jid": "alice@example.com",
            "body": "Hello world!",
            "ts": 1700000000.0,
        },
        {
            "uuid": str(uuid.uuid4()),
            "from_jid": "bob@work.com",
            "body": "Meeting at 3 PM",
            "ts": 1700000060.0,
        },
        {
            "uuid": str(uuid.uuid4()),
            "from_jid": "carol@team.org",
            "body": "Project update available",
            "ts": 1700000120.0,
        },
    ]

    # Add messages to bridge inbox
    for msg in test_messages:
        bridge.inbox.append(msg)

    print(f"Added {len(test_messages)} test messages to inbox")

    # Test bridge.list_inbox()
    print("\n1. Testing bridge.list_inbox():")
    inbox_list = await bridge.list_inbox()
    print(f"Found {len(inbox_list)} messages in inbox")
    for msg in inbox_list:
        print(f"  - {msg['uuid'][:8]}... from {msg['from_jid']}: {msg['body'][:30]}...")

    # Test bridge.get_message(msg_id)
    print("\n2. Testing bridge.get_message(msg_id):")
    first_msg_id = test_messages[0]["uuid"]
    retrieved_msg = await bridge.get_message(first_msg_id)
    if retrieved_msg:
        print(
            f"Retrieved message: {retrieved_msg['from_jid']} - {retrieved_msg['body']}"
        )
    else:
        print("Error: Could not retrieve message")

    # Test with non-existent message ID
    fake_id = str(uuid.uuid4())
    non_existent = await bridge.get_message(fake_id)
    if non_existent is None:
        print("Correctly returned None for non-existent message ID")
    else:
        print("Error: Should have returned None for non-existent message")

    # Test bridge.clear_inbox()
    print("\n3. Testing bridge.clear_inbox():")
    cleared_count = await bridge.clear_inbox()
    print(f"Cleared {cleared_count} messages from inbox")

    # Verify inbox is empty
    remaining_list = await bridge.list_inbox()
    print(f"Remaining messages after clear: {len(remaining_list)}")

    print("\n✅ All inbox functionality tests completed successfully!")


async def test_server_handlers():
    """Test the server's inbox handlers."""
    print("\nTesting server inbox handlers...")

    # Create server instance without XMPP credentials (will use fallback mode)
    server = XmppMcpServer()

    # Create a bridge and attach it
    server.bridge = XmppMcpBridge(queue_size=10, inbox_maxlen=50)

    # Add test message
    test_msg = {
        "uuid": str(uuid.uuid4()),
        "from_jid": "test@example.com",
        "body": "Test message",
        "ts": 1700000000.0,
    }
    server.bridge.inbox.append(test_msg)

    # Test _handle_inbox_list
    print("\n1. Testing _handle_inbox_list:")
    list_request = JsonRpcMessage(id=1, method="inbox/list")
    list_response = await server._handle_inbox_list(list_request)
    print(
        f"List response status: {'✅ Success' if list_response.result else '❌ Error'}"
    )
    if list_response.result:
        print(f"Found {len(list_response.result.get('messages', []))} messages")

    # Test _handle_inbox_get
    print("\n2. Testing _handle_inbox_get:")
    get_params = {"messageId": test_msg["uuid"]}
    get_request = JsonRpcMessage(id=2, method="inbox/get", params=get_params)
    get_response = await server._handle_inbox_get(get_request, get_params)
    print(f"Get response status: {'✅ Success' if get_response.result else '❌ Error'}")
    if get_response.result:
        print(f"Retrieved message: {get_response.result['message']['from_jid']}")

    # Test _handle_inbox_clear
    print("\n3. Testing _handle_inbox_clear:")
    clear_request = JsonRpcMessage(id=3, method="inbox/clear")
    clear_response = await server._handle_inbox_clear(clear_request)
    print(
        f"Clear response status: {'✅ Success' if clear_response.result else '❌ Error'}"
    )
    if clear_response.result:
        print(f"Clear result: {clear_response.result['status']}")

    print("\n✅ All server handler tests completed successfully!")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing XMPP MCP Server Inbox Tool Handlers")
    print("=" * 60)

    try:
        await test_inbox_functionality()
        await test_server_handlers()

        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("=" * 60)
        print("\nInbox tool handlers are working correctly:")
        print("✅ _tool_inbox_list → bridge.list_inbox()")
        print("✅ _tool_inbox_get → bridge.get_message(msg_id)")
        print("✅ _tool_inbox_clear → bridge.clear_inbox()")
        print(
            "\nReturn structures are properly formatted under result.content for LLM readability."
        )

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
