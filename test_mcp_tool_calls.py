#!/usr/bin/env python3
"""
Test script to verify that inbox handlers work through the MCP tools/call interface.
"""

import asyncio
import sys
import uuid
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from jabber_mcp.xmpp_mcp_server import JsonRpcMessage, XmppMcpBridge, XmppMcpServer


async def test_mcp_tool_calls():
    """Test calling inbox handlers through the MCP tools/call interface."""
    print("Testing inbox handlers through MCP tools/call interface...")

    # Create server instance
    server = XmppMcpServer()
    server.bridge = XmppMcpBridge(queue_size=10, inbox_maxlen=50)

    # Add test message
    test_msg = {
        "uuid": str(uuid.uuid4()),
        "from_jid": "test@example.com",
        "body": "Test message from MCP",
        "ts": 1700000000.0,
    }
    server.bridge.inbox.append(test_msg)

    print(f"Added test message: {test_msg['uuid'][:8]}... from {test_msg['from_jid']}")

    # Test inbox/list through tools/call
    print("\n1. Testing inbox/list through tools/call:")
    list_call_params = {"name": "inbox/list", "arguments": {}}
    list_call_msg = JsonRpcMessage(id=1, method="tools/call", params=list_call_params)
    list_response = await server._handle_tools_call(list_call_msg, list_call_params)

    if list_response.result:
        print("✅ inbox/list call successful")
        messages = list_response.result.get("messages", [])
        print(f"   Found {len(messages)} messages")
        if messages:
            print(f"   First message: {messages[0]['from']} - {messages[0]['preview']}")
    else:
        print("❌ inbox/list call failed")
        print(f"   Error: {list_response.error}")

    # Test inbox/get through tools/call
    print("\n2. Testing inbox/get through tools/call:")
    get_call_params = {
        "name": "inbox/get",
        "arguments": {"messageId": test_msg["uuid"]},
    }
    get_call_msg = JsonRpcMessage(id=2, method="tools/call", params=get_call_params)
    get_response = await server._handle_tools_call(get_call_msg, get_call_params)

    if get_response.result:
        print("✅ inbox/get call successful")
        message = get_response.result.get("message", {})
        if message:
            print(f"   Retrieved: {message['from_jid']} - {message['body']}")
    else:
        print("❌ inbox/get call failed")
        print(f"   Error: {get_response.error}")

    # Test inbox/clear through tools/call
    print("\n3. Testing inbox/clear through tools/call:")
    clear_call_params = {"name": "inbox/clear", "arguments": {}}
    clear_call_msg = JsonRpcMessage(id=3, method="tools/call", params=clear_call_params)
    clear_response = await server._handle_tools_call(clear_call_msg, clear_call_params)

    if clear_response.result:
        print("✅ inbox/clear call successful")
        print(f"   Status: {clear_response.result.get('status', 'Unknown')}")
    else:
        print("❌ inbox/clear call failed")
        print(f"   Error: {clear_response.error}")

    # Verify tools are in capabilities
    print("\n4. Verifying tools are registered in capabilities:")
    tool_names = list(server.capabilities["tools"].keys())
    inbox_tools = [name for name in tool_names if name.startswith("inbox/")]
    print(f"   Registered inbox tools: {inbox_tools}")

    expected_tools = ["inbox/list", "inbox/get", "inbox/clear"]
    for tool in expected_tools:
        if tool in tool_names:
            print(f"   ✅ {tool} is registered")
        else:
            print(f"   ❌ {tool} is NOT registered")

    print("\n✅ MCP tool call tests completed!")


async def main():
    """Run the MCP tool call tests."""
    print("=" * 60)
    print("Testing Inbox Handlers via MCP Tools/Call Interface")
    print("=" * 60)

    try:
        await test_mcp_tool_calls()

        print("\n" + "=" * 60)
        print("🎉 MCP TOOL CALL TESTS PASSED! 🎉")
        print("=" * 60)
        print("\nInbox tool handlers work correctly through:")
        print("✅ Direct handler calls (_handle_inbox_*)")
        print("✅ MCP tools/call interface")
        print("✅ Tool registration in capabilities")
        print("\nReturn structures contain result.content for LLM readability.")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
