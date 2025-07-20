# XMPP ↔ MCP Message Converters

The `jabber_mcp.converters` module provides type-safe conversion logic between XMPP stanzas and MCP events.

## Overview

This module implements bidirectional message conversion:

1. **MCP SEND → XMPP**: Converts MCP tool calls into XMPP `<message>` stanzas
2. **XMPP → MCP RECEIVED**: Converts incoming XMPP messages into MCP events

## Dataclasses

### `SendXmppMessage`

Represents an outgoing XMPP message from an MCP SEND command.

**Fields:**
- `jid: str` - The recipient's Jabber ID
- `body: str` - The message text
- `message_type: str = "chat"` - XMPP message type (chat, normal, etc.)

**Methods:**
- `to_stanza() -> str` - Convert to XML XMPP stanza with proper escaping
- `to_dict() -> Dict[str, Any]` - Convert to dictionary for queue messaging

### `ReceivedXmppMessage`

Represents an incoming XMPP message that needs to become an MCP event.

**Fields:**
- `jid: str` - The sender's Jabber ID  
- `body: str` - The message text
- `message_type: str = "chat"` - XMPP message type
- `timestamp: Optional[float] = None` - Message timestamp

**Methods:**
- `from_stanza(from_jid, body, message_type, timestamp)` - Create from XMPP stanza data
- `from_mcp_event(data)` - Create from MCP event dictionary
- `to_mcp_event() -> Dict[str, Any]` - Convert to MCP RECEIVED event

## Converter Functions

### `convert_mcp_send_to_xmpp(mcp_data)`

Converts an MCP SEND command to an XMPP message object.

**Parameters:**
- `mcp_data: Dict[str, Any]` - Must contain 'jid' and 'body' fields

**Returns:**
- `SendXmppMessage` - Ready for XMPP transmission

**Raises:**
- `ValueError` - If required fields are missing or invalid

### `convert_xmpp_to_mcp_event(from_jid, body, message_type, timestamp)`

Converts an incoming XMPP message to an MCP RECEIVED event.

**Parameters:**
- `from_jid: str` - Sender's Jabber ID
- `body: str` - Message text
- `message_type: str = "chat"` - XMPP message type
- `timestamp: Optional[float] = None` - Message timestamp

**Returns:**
- `Dict[str, Any]` - MCP RECEIVED event dictionary

## Features

### Security & Safety
- **XML Escaping**: All XMPP stanzas properly escape XML entities to prevent injection
- **HTML Unescaping**: Incoming messages safely unescape HTML entities
- **Type Safety**: Full mypy strict mode compliance with runtime type validation
- **Input Validation**: Validates required fields and data types

### Robustness  
- **Type Coercion**: Gracefully handles invalid types from MCP events
- **Fallback Handling**: Uses sensible defaults for missing optional fields
- **Error Messages**: Clear, descriptive error messages for invalid inputs

## Usage Examples

### Basic MCP SEND → XMPP Conversion

```python
from jabber_mcp.converters import convert_mcp_send_to_xmpp

# MCP tool call data
mcp_data = {
    'jid': 'alice@example.com',
    'body': 'Hello, Alice!'
}

# Convert to XMPP message
send_msg = convert_mcp_send_to_xmpp(mcp_data)
print(send_msg.to_stanza())
# Output: <message to="alice@example.com" type="chat"><body>Hello, Alice!</body></message>
```

### XMPP → MCP RECEIVED Conversion

```python
from jabber_mcp.converters import convert_xmpp_to_mcp_event

# Convert incoming XMPP message
event = convert_xmpp_to_mcp_event(
    from_jid='bob@example.com',
    body='Hi there!', 
    timestamp=1234567890.0
)

print(event)
# Output: {
#   'type': 'received_message',
#   'from_jid': 'bob@example.com', 
#   'body': 'Hi there!',
#   'message_type': 'chat',
#   'timestamp': 1234567890.0
# }
```

### XML Security Example

```python
# Dangerous input is safely escaped
mcp_data = {
    'jid': 'user@example.com',
    'body': '<script>alert("XSS")</script>'
}

send_msg = convert_mcp_send_to_xmpp(mcp_data)
print(send_msg.to_stanza())
# Output: <message to="user@example.com" type="chat"><body>&lt;script&gt;alert("XSS")&lt;/script&gt;</body></message>
```

## Integration with Bridge

The converters are designed to work seamlessly with the MCP Bridge:

1. MCP tool calls are converted to `SendXmppMessage` objects
2. These are converted to XMPP stanzas for transmission  
3. Incoming XMPP messages are converted to MCP RECEIVED events
4. Events are queued for processing by MCP clients

This provides a clean separation between protocol-specific formatting and bridge message routing logic.
