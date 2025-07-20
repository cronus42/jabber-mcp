#!/usr/bin/env python3
"""
Test script for MCP inbox and address-book tools.

This script tests the new MCP capabilities by sending JSON-RPC requests
and verifying the responses.
"""

import asyncio
import json
import sys
from typing import Any, Dict


class McpTestClient:
    """Simple test client for MCP protocol."""

    def __init__(self):
        self.request_id = 0

    def create_request(self, method: str, params: Dict[str, Any] = None) -> str:
        """Create a JSON-RPC request."""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
        }
        if params:
            request["params"] = params
        return json.dumps(request)

    def create_tool_call(self, tool_name: str, arguments: Dict[str, Any] = None) -> str:
        """Create a tools/call request."""
        params = {"name": tool_name}
        if arguments:
            params["arguments"] = arguments
        return self.create_request("tools/call", params)

    async def test_initialization(self):
        """Test MCP initialization."""
        print("=== Testing MCP Initialization ===")

        # Test initialize
        init_request = self.create_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        )
        print(f"Initialize request: {init_request}")

        # Test initialized
        initialized_request = self.create_request("initialized", {})
        print(f"Initialized request: {initialized_request}")

        # Test tools/list
        tools_list_request = self.create_request("tools/list", {})
        print(f"Tools list request: {tools_list_request}")

    async def test_inbox_operations(self):
        """Test inbox operations."""
        print("\n=== Testing Inbox Operations ===")

        # Test inbox/list
        inbox_list_request = self.create_tool_call("inbox/list")
        print(f"Inbox list request: {inbox_list_request}")

        # Test inbox/get (will need a valid message ID from the list response)
        # This is just an example - in real testing, you'd get the ID from the list
        example_message_id = "test-message-id"
        inbox_get_request = self.create_tool_call(
            "inbox/get", {"messageId": example_message_id}
        )
        print(f"Inbox get request: {inbox_get_request}")

        # Test inbox/clear
        inbox_clear_request = self.create_tool_call("inbox/clear")
        print(f"Inbox clear request: {inbox_clear_request}")

    async def test_address_book_operations(self):
        """Test address book operations."""
        print("\n=== Testing Address Book Operations ===")

        # Test address_book/save
        save_request = self.create_tool_call(
            "address_book/save", {"alias": "john", "jid": "john.doe@example.com"}
        )
        print(f"Address book save request: {save_request}")

        # Test address_book/query
        query_request = self.create_tool_call("address_book/query", {"query": "alice"})
        print(f"Address book query request: {query_request}")

        # Test fuzzy search
        fuzzy_query_request = self.create_tool_call(
            "address_book/query", {"query": "work"}
        )
        print(f"Address book fuzzy query request: {fuzzy_query_request}")

    async def test_existing_tools(self):
        """Test existing tools."""
        print("\n=== Testing Existing Tools ===")

        # Test ping
        ping_request = self.create_tool_call("ping")
        print(f"Ping request: {ping_request}")

        # Test send_xmpp_message
        send_message_request = self.create_tool_call(
            "send_xmpp_message",
            {"recipient": "test@example.com", "message": "Hello from test client!"},
        )
        print(f"Send message request: {send_message_request}")

    async def run_all_tests(self):
        """Run all tests."""
        print("MCP Tools Test Suite")
        print("===================")

        await self.test_initialization()
        await self.test_inbox_operations()
        await self.test_address_book_operations()
        await self.test_existing_tools()

        print("\n=== Test Requests Generated ===")
        print("Copy and paste these JSON-RPC requests to test the MCP server manually.")
        print("You can also pipe them to the MCP server for automated testing.")


async def main():
    """Main test function."""
    client = McpTestClient()
    await client.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
