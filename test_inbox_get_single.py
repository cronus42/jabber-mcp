#!/usr/bin/env python3
"""
Single process test for inbox/get functionality.
This test uses a single server session to test inbox/get with a valid message ID.
"""

import asyncio
import json
import os
import subprocess
import sys


async def test_inbox_get_single_session():
    """Test inbox/get in a single server session."""
    print("Testing inbox/get in single session")
    print("=" * 38)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"/home/cronus/jabber-mcp/src:{env.get('PYTHONPATH', '')}"

    # We'll construct the commands dynamically
    # First, get the inbox list and use the first message ID for inbox/get
    commands = [
        # List inbox
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
        # Send the first command and read the response
        process.stdin.write(input_data)
        process.stdin.flush()

        # Read lines until we get a JSON response
        output_lines = []
        while True:
            line = process.stdout.readline()
            if not line:
                break
            output_lines.append(line.strip())
            if line.strip().startswith('{"jsonrpc"'):
                response = json.loads(line.strip())
                messages = response.get("result", {}).get("messages", [])

                if messages:
                    message_id = messages[0]["id"]
                    print(f"✓ Found {len(messages)} messages in inbox")
                    print(f"✓ Using message ID: {message_id[:20]}...")

                    # Now send inbox/get command with the valid message ID
                    get_command = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "inbox/get",
                            "arguments": {"messageId": message_id},
                        },
                    }

                    get_input = json.dumps(get_command) + "\n"
                    process.stdin.write(get_input)
                    process.stdin.flush()

                    # Read the response for inbox/get
                    get_line = process.stdout.readline()
                    if get_line.strip().startswith('{"jsonrpc"'):
                        get_response = json.loads(get_line.strip())

                        if "result" in get_response:
                            message = get_response["result"]
                            print("✓ Successfully retrieved message:")
                            print(f"  ID: {message.get('id', '')[:20]}...")
                            print(f"  From: {message.get('from')}")
                            print(f"  Body: {message.get('body', '')}")
                            print(f"  Timestamp: {message.get('timestamp')}")
                            print("\n🎉 inbox/get functionality verified!")
                        else:
                            print(
                                f"✗ Failed to get message: {get_response.get('error', {}).get('message')}"
                            )
                else:
                    print("✗ No messages found in inbox")
                break

        # Close the process
        process.stdin.close()
        process.wait(timeout=2)

    except subprocess.TimeoutExpired:
        process.kill()
        print("❌ Server session timed out")
        return False

    except Exception as e:
        print(f"❌ Error: {e}")
        process.kill()
        return False


if __name__ == "__main__":
    asyncio.run(test_inbox_get_single_session())
