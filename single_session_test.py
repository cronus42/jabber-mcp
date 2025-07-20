#!/usr/bin/env python3
"""
Single session integration test for MCP server functionality.
This test sends multiple commands to one server session to verify functionality.
"""

import asyncio
import json
import os
import subprocess
import sys


class McpSingleSessionTest:
    """Single session integration test for MCP server."""

    def __init__(self):
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = (
            f"/home/cronus/jabber-mcp/src:{self.env.get('PYTHONPATH', '')}"
        )

    async def run_server_session(self):
        """Run a server session with multiple commands."""
        print("MCP Single Session Integration Test")
        print("=" * 40)

        # Prepare sequence of commands
        commands = [
            # Initialize the server
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "integration-test", "version": "1.0.0"},
                },
            },
            # List tools
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            # List inbox
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "inbox/list"},
            },
            # Query address book for alice
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "address_book/query",
                    "arguments": {"query": "alice"},
                },
            },
            # Save new entry to address book
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "address_book/save",
                    "arguments": {"alias": "testuser", "jid": "test@example.com"},
                },
            },
            # Query for the new entry
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "address_book/query",
                    "arguments": {"query": "testuser"},
                },
            },
            # Test ping
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "ping"},
            },
            # Clear inbox
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "inbox/clear"},
            },
            # List inbox again (should be empty)
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "inbox/list"},
            },
        ]

        # Convert commands to newline-separated JSON
        input_data = "\n".join([json.dumps(cmd) for cmd in commands]) + "\n"

        # Run the server process
        process = subprocess.Popen(
            ["python3", "-m", "jabber_mcp.mcp_stdio_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd="/home/cronus/jabber-mcp",
            env=self.env,
            text=True,
        )

        try:
            stdout, stderr = process.communicate(input=input_data, timeout=10)

            # Process the output
            self.analyze_responses(stdout, stderr)

        except subprocess.TimeoutExpired:
            process.kill()
            print("❌ Server session timed out")
            return False

        return True

    def analyze_responses(self, stdout: str, stderr: str):
        """Analyze the server responses."""
        print("\nServer Output Analysis:")
        print("-" * 25)

        # Extract JSON responses from stdout
        lines = stdout.strip().split("\n")
        responses = []

        for line in lines:
            if line.startswith('{"jsonrpc"'):
                try:
                    response = json.loads(line)
                    responses.append(response)
                except json.JSONDecodeError:
                    continue

        print(f"Received {len(responses)} JSON responses")

        # Analyze each response
        test_results = []

        # Test 1: Initialization
        if len(responses) > 0 and "capabilities" in responses[0].get("result", {}):
            tools = responses[0]["result"]["capabilities"].get("tools", {})
            if "inbox/list" in tools and "address_book/query" in tools:
                test_results.append(
                    ("✓", "Initialization successful - all tools present")
                )
            else:
                test_results.append(("✗", "Initialization failed - missing tools"))
        else:
            test_results.append(("✗", "No initialization response"))

        # Test 2: Tools list
        if len(responses) > 1 and "tools" in responses[1].get("result", {}):
            tools_list = responses[1]["result"]["tools"]
            tool_names = [tool["name"] for tool in tools_list]
            expected_tools = [
                "inbox/list",
                "inbox/get",
                "inbox/clear",
                "address_book/query",
                "address_book/save",
            ]
            if all(tool in tool_names for tool in expected_tools):
                test_results.append(
                    ("✓", f"Tools list complete - {len(tools_list)} tools available")
                )
            else:
                test_results.append(("✗", "Tools list incomplete"))
        else:
            test_results.append(("✗", "No tools list response"))

        # Test 3: Inbox list
        if len(responses) > 2 and "messages" in responses[2].get("result", {}):
            messages = responses[2]["result"]["messages"]
            test_results.append(
                ("✓", f"Inbox list successful - {len(messages)} messages")
            )

            # Store a message ID for later testing
            if messages and len(responses) > 2:
                message_id = messages[0]["id"]
                # We could add an inbox/get test here if we modify the commands
        else:
            test_results.append(("✗", "Inbox list failed"))

        # Test 4: Address book query (alice)
        if len(responses) > 3 and "matches" in responses[3].get("result", {}):
            matches = responses[3]["result"]["matches"]
            if "alice" in matches:
                test_results.append(
                    (
                        "✓",
                        f"Address book query successful - found alice: {matches['alice']}",
                    )
                )
            else:
                test_results.append(
                    ("✗", "Address book query failed - alice not found")
                )
        else:
            test_results.append(("✗", "No address book query response"))

        # Test 5: Address book save
        if (
            len(responses) > 4
            and responses[4].get("result", {}).get("status") == "Entry saved"
        ):
            test_results.append(("✓", "Address book save successful"))
        else:
            test_results.append(("✗", "Address book save failed"))

        # Test 6: Address book query (testuser)
        if len(responses) > 5 and "matches" in responses[5].get("result", {}):
            matches = responses[5]["result"]["matches"]
            if "testuser" in matches and matches["testuser"] == "test@example.com":
                test_results.append(
                    ("✓", "Address book persistence verified - testuser found")
                )
            else:
                test_results.append(
                    ("✗", "Address book persistence failed - testuser not found")
                )
        else:
            test_results.append(("✗", "No testuser query response"))

        # Test 7: Ping
        if len(responses) > 6 and "content" in responses[6].get("result", {}):
            content = responses[6]["result"]["content"]
            if content and "PONG" in content[0].get("text", ""):
                test_results.append(("✓", "Ping successful"))
            else:
                test_results.append(("✗", "Ping failed"))
        else:
            test_results.append(("✗", "No ping response"))

        # Test 8: Inbox clear
        if (
            len(responses) > 7
            and responses[7].get("result", {}).get("status") == "Inbox cleared"
        ):
            test_results.append(("✓", "Inbox clear successful"))
        else:
            test_results.append(("✗", "Inbox clear failed"))

        # Test 9: Inbox list after clear
        if len(responses) > 8 and "messages" in responses[8].get("result", {}):
            messages = responses[8]["result"]["messages"]
            if len(messages) == 0:
                test_results.append(("✓", "Inbox cleared verified - no messages"))
            else:
                test_results.append(
                    (
                        "✗",
                        f"Inbox clear verification failed - {len(messages)} messages remaining",
                    )
                )
        else:
            test_results.append(("✗", "No inbox list after clear response"))

        # Print test results
        print("\nTest Results:")
        print("-" * 15)
        passed = 0
        total = len(test_results)

        for status, description in test_results:
            print(f"{status} {description}")
            if status == "✓":
                passed += 1

        print(f"\nOverall: {passed}/{total} tests passed")

        if passed == total:
            print(
                "\n🎉 All tests passed! MCP inbox and address-book capabilities are fully functional."
            )
        else:
            print(f"\n❌ {total - passed} tests failed. See details above.")

        if stderr.strip():
            print(f"\nServer Logs (stderr):\n{stderr}")


async def main():
    """Main test function."""
    test = McpSingleSessionTest()
    success = await test.run_server_session()

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
