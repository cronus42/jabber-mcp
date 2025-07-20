#!/usr/bin/env python3
"""
Test inbox/get functionality with a dynamic message ID.
This demonstrates getting a message by ID after listing the inbox.
"""

import asyncio
import json
import os
import subprocess
import sys


async def test_inbox_get():
    """Test the inbox/get functionality with a real message ID."""
    print("Testing inbox/get functionality")
    print("=" * 35)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"/home/cronus/jabber-mcp/src:{env.get('PYTHONPATH', '')}"

    # First, get the message list
    commands = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "inbox/list"},
        },
    ]

    input_data = "\n".join([json.dumps(cmd) for cmd in commands]) + "\n"

    process = subprocess.Popen(
        ["python3", "-m", "jabber_mcp.mcp_stdio_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/home/cronus/jabber-mcp",
        env=env,
        text=True,
    )

    try:
        stdout, stderr = process.communicate(input=input_data, timeout=5)

        # Extract the JSON response
        lines = stdout.strip().split("\n")
        for line in lines:
            if line.startswith('{"jsonrpc"'):
                response = json.loads(line)
                messages = response.get("result", {}).get("messages", [])

                if messages:
                    message_id = messages[0]["id"]
                    print(f"Found {len(messages)} messages")
                    print(f"Testing inbox/get with message ID: {message_id}")

                    # Now test inbox/get with the actual message ID
                    await test_get_message(message_id, env)
                else:
                    print("No messages found in inbox")
                break

    except subprocess.TimeoutExpired:
        process.kill()
        print("❌ Server session timed out")
        return False


async def test_get_message(message_id: str, env: dict):
    """Test getting a specific message by ID."""

    commands = [
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "inbox/get", "arguments": {"messageId": message_id}},
        }
    ]

    input_data = "\n".join([json.dumps(cmd) for cmd in commands]) + "\n"

    process = subprocess.Popen(
        ["python3", "-m", "jabber_mcp.mcp_stdio_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/home/cronus/jabber-mcp",
        env=env,
        text=True,
    )

    try:
        stdout, stderr = process.communicate(input=input_data, timeout=5)

        # Extract the JSON response
        lines = stdout.strip().split("\n")
        for line in lines:
            if line.startswith('{"jsonrpc"'):
                response = json.loads(line)

                if "result" in response:
                    message = response["result"]
                    print("✓ Successfully retrieved message:")
                    print(f"  From: {message.get('from')}")
                    print(f"  Body: {message.get('body', '')[:100]}...")
                    print(f"  Timestamp: {message.get('timestamp')}")
                else:
                    print(
                        f"✗ Failed to get message: {response.get('error', {}).get('message')}"
                    )
                break

    except subprocess.TimeoutExpired:
        process.kill()
        print("❌ Get message session timed out")


if __name__ == "__main__":
    asyncio.run(test_inbox_get())
