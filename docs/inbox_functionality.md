# Inbox Functionality in XmppMcpBridge

The XmppMcpBridge now includes an inbox feature that persists inbound XMPP messages for later retrieval by server tool handlers.

## Overview

The inbox is implemented as a `collections.deque` with configurable maximum length that automatically evicts old messages when the limit is reached. It stores concise records of received XMPP messages with the following fields:

- `uuid`: Unique identifier for the message
- `from_jid`: Sender's Jabber ID
- `body`: Message content
- `ts`: Timestamp when the message was received

## Configuration

The inbox can be configured when creating an XmppMcpBridge instance:

```python
from jabber_mcp.xmpp_mcp_server import XmppMcpBridge

# Create bridge with custom inbox size (default is 500)
bridge = XmppMcpBridge(
    queue_size=100,
    inbox_maxlen=1000  # Keep up to 1000 messages
)
```

## Usage

### Getting All Messages

```python
# Get all messages in inbox (newest first)
messages = await bridge.get_inbox_list()
```

### Getting Limited Messages

```python
# Get only the 10 most recent messages
recent_messages = await bridge.get_inbox_list(limit=10)
```

### Getting Specific Message by UUID

```python
# Fetch a specific message by its UUID
message = await bridge.get_inbox_message("some-uuid-here")
if message:
    print(f"Message from {message['from_jid']}: {message['body']}")
```

### Getting Inbox Statistics

```python
# Get inbox usage statistics
stats = await bridge.get_inbox_stats()
print(f"Total messages: {stats['total_messages']}")
print(f"Capacity: {stats['max_capacity']}")
print(f"Usage: {stats['capacity_used_percent']}%")
```

## Features

### Non-blocking Access
All inbox getter methods are async and designed to be non-blocking, making them safe to call from MCP tool handlers without interfering with message processing.

### Automatic Message Filtering
Only `received_message` events are added to the inbox. Other event types (like presence updates) are ignored.

### Thread-safe Concurrent Access
Multiple coroutines can access the inbox concurrently without blocking each other.

### Automatic Eviction
When the inbox reaches its maximum capacity, the oldest messages are automatically removed to make room for new ones.

## Example: Using Inbox in MCP Tools

```python
async def _tool_get_recent_messages(
    self, message: JsonRpcMessage, arguments: dict[str, Any]
) -> JsonRpcMessage:
    """MCP tool to get recent messages from inbox."""

    if not self.bridge:
        return JsonRpcMessage(
            id=message.id,
            error={"code": -32603, "message": "XMPP bridge not available"}
        )

    limit = arguments.get("limit", 10)
    messages = await self.bridge.get_inbox_list(limit=limit)

    # Format messages for response
    formatted_messages = []
    for msg in messages:
        formatted_messages.append({
            "from": msg["from_jid"],
            "body": msg["body"],
            "timestamp": msg["ts"],
            "id": msg["uuid"]
        })

    return JsonRpcMessage(
        id=message.id,
        result={
            "content": [{
                "type": "text",
                "text": f"Found {len(messages)} recent messages:\n" +
                        "\n".join([f"- {m['from']}: {m['body']}" for m in formatted_messages])
            }]
        }
    )
```

## Message Format

Each message record in the inbox contains:

```python
{
    "uuid": "48ad3788-6337-4ccb-adb7-f7a908a9c4f4",
    "from_jid": "alice@example.com",
    "body": "Hello everyone!",
    "ts": 32185.815624982  # Timestamp from asyncio.get_event_loop().time()
}
```

## Performance Considerations

- The inbox uses a deque for O(1) append and popleft operations
- Messages are stored in memory only (not persisted to disk)
- The configurable maximum length prevents unbounded memory growth
- Accessing the inbox does not block message processing
