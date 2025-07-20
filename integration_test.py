#!/usr/bin/env python3
"""
Integration test for MCP server functionality.
This test simulates a complete MCP interaction workflow.
"""

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional


class McpIntegrationTest:
    """Integration test for MCP server."""

    def __init__(self):
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = (
            f"/home/cronus/jabber-mcp/src:{self.env.get('PYTHONPATH', '')}"
        )

    def send_request(self, request: str) -> Dict[str, Any]:
        """Send a request to the MCP server and get response."""
        try:
            process = subprocess.Popen(
                ["python3", "-m", "jabber_mcp.mcp_stdio_server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd="/home/cronus/jabber-mcp",
                env=self.env,
                text=True,
            )

            stdout, stderr = process.communicate(input=request)

            # Find the JSON response in stdout (skip debug logs)
            lines = stdout.strip().split("\n")
            for line in lines:
                if line.startswith('{"jsonrpc"'):
                    return json.loads(line)

            raise ValueError(f"No valid JSON response found. Stderr: {stderr}")

        except Exception as e:
            print(f"Error running MCP server: {e}")
            return {}

    def test_initialization(self) -> bool:
        """Test MCP initialization."""
        print("Testing initialization...")

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "integration-test", "version": "1.0.0"},
                },
            }
        )

        response = self.send_request(request)

        if (
            response.get("result", {})
            .get("capabilities", {})
            .get("tools", {})
            .get("inbox/list")
        ):
            print("✓ Initialization successful - inbox tools found")
            return True
        else:
            print("✗ Initialization failed - inbox tools not found")
            print(f"Response: {response}")
            return False

    def test_inbox_workflow(self) -> bool:
        """Test inbox workflow: list -> get -> clear."""
        print("Testing inbox workflow...")

        # Test inbox/list
        list_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "inbox/list"},
            }
        )

        list_response = self.send_request(list_request)
        messages = list_response.get("result", {}).get("messages", [])

        if not messages:
            print("✗ No messages found in inbox")
            return False

        print(f"✓ Found {len(messages)} messages in inbox")

        # Test inbox/get with first message ID
        message_id = messages[0]["id"]
        get_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "inbox/get", "arguments": {"messageId": message_id}},
            }
        )

        get_response = self.send_request(get_request)
        message_body = get_response.get("result", {}).get("body")

        if message_body:
            print(f"✓ Retrieved message: {message_body[:50]}...")
        else:
            print("✗ Failed to retrieve message body")
            return False

        # Test inbox/clear
        clear_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "inbox/clear"},
            }
        )

        clear_response = self.send_request(clear_request)

        if clear_response.get("result", {}).get("status") == "Inbox cleared":
            print("✓ Inbox cleared successfully")
            return True
        else:
            print("✗ Failed to clear inbox")
            return False

    def test_address_book_workflow(self) -> bool:
        """Test address book workflow: query -> save -> query."""
        print("Testing address book workflow...")

        # Test initial query for alice
        query_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "address_book/query",
                    "arguments": {"query": "alice"},
                },
            }
        )

        query_response = self.send_request(query_request)
        matches = query_response.get("result", {}).get("matches", {})

        if "alice" in matches:
            print(f"✓ Found alice in address book: {matches['alice']}")
        else:
            print("✗ Alice not found in address book")
            return False

        # Test saving a new entry
        save_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "address_book/save",
                    "arguments": {"alias": "testuser", "jid": "test@example.com"},
                },
            }
        )

        save_response = self.send_request(save_request)

        if save_response.get("result", {}).get("status") == "Entry saved":
            print("✓ New entry saved to address book")
        else:
            print("✗ Failed to save new entry")
            return False

        # Test querying for the new entry
        query_new_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "address_book/query",
                    "arguments": {"query": "testuser"},
                },
            }
        )

        query_new_response = self.send_request(query_new_request)
        new_matches = query_new_response.get("result", {}).get("matches", {})

        if "testuser" in new_matches and new_matches["testuser"] == "test@example.com":
            print("✓ New entry found in address book query")
            return True
        else:
            print("✗ New entry not found in subsequent query")
            return False

    def run_all_tests(self) -> bool:
        """Run all integration tests."""
        print("MCP Integration Test Suite")
        print("=" * 30)

        tests = [
            ("Initialization", self.test_initialization),
            ("Inbox Workflow", self.test_inbox_workflow),
            ("Address Book Workflow", self.test_address_book_workflow),
        ]

        passed = 0
        total = len(tests)

        for test_name, test_func in tests:
            print(f"\n{test_name}:")
            try:
                if test_func():
                    passed += 1
                    print(f"✓ {test_name} PASSED")
                else:
                    print(f"✗ {test_name} FAILED")
            except Exception as e:
                print(f"✗ {test_name} ERROR: {e}")

        print("\n" + "=" * 30)
        print(f"Test Results: {passed}/{total} passed")

        return passed == total


async def main():
    """Main test function."""
    test = McpIntegrationTest()
    success = test.run_all_tests()

    if success:
        print(
            "\n🎉 All tests passed! MCP inbox and address-book capabilities are working correctly."
        )
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Check the output above for details.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
