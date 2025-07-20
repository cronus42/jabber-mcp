# MCP Server Integration with Warp IDE

This document explains how to set up and use the minimal MCP server for testing XMPP functionality directly with Warp IDE.

## Overview

The `jabber-mcp-server` provides a minimal Model Context Protocol (MCP) server that communicates with Warp IDE using JSON-RPC 2.0 over stdio. It currently supports:

- **SEND**: Send XMPP messages (simulated for testing)
- **ACK/NACK**: Acknowledge message delivery
- **PING/PONG**: Test connection health

## Installation

```bash
# Install in development mode
cd /home/cronus/jabber-mcp
pip install -e .

# Or install from package
pip install jabber-mcp
```

## Usage with Warp IDE

### 1. Configure MCP Server in Warp

Add the following configuration to your Warp IDE MCP settings:

```json
{
  "mcpServers": {
    "jabber-mcp": {
      "command": "jabber-mcp-server",
      "args": [],
      "env": {}
    }
  }
}
```

### 2. Available Tools

Once configured, the following tools will be available in Warp IDE:

#### `send_message`
Send a message through XMPP (simulated).

**Parameters:**
- `recipient` (string, required): The JID of the message recipient
- `message` (string, required): The message text to send

**Example:**
```
Use the send_message tool to send "Hello World!" to user@example.com
```

#### `ping`
Test the XMPP connection health.

**Parameters:** None

**Example:**
```
Use the ping tool to check XMPP connection
```

### 3. Testing the Integration

You can test the MCP server directly using the provided test script:

```bash
cd /home/cronus/jabber-mcp
python test_mcp_stdio.py
```

This will run through all the basic MCP protocol interactions to verify everything is working correctly.

### 4. Manual Testing

You can also run the server manually and interact with it:

```bash
# Run the server
python -m jabber_mcp

# Or use the installed script
jabber-mcp-server
```

Then send JSON-RPC messages via stdin:

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}}
```

## Protocol Details

### Message Format

The server uses JSON-RPC 2.0 over stdio with line-delimited framing:
- Each message is a complete JSON object on a single line
- Messages are terminated with `\n`
- Logging goes to stderr to avoid interfering with stdio communication

### Supported Methods

1. **initialize**: Initialize the MCP server
2. **tools/list**: List available tools
3. **tools/call**: Call a specific tool
4. **ping**: Basic ping/pong for health checks

### Error Handling

Standard JSON-RPC 2.0 error codes:
- `-32700`: Parse error
- `-32600`: Invalid Request
- `-32601`: Method not found
- `-32602`: Invalid params
- `-32603`: Internal error

## Architecture Integration

This minimal MCP server fits into the larger XMPP-MCP bridge architecture as defined in `ARCHITECTURE.md`:

```
┌──────────────┐    ┌─────────────┐    ┌──────────┐
│  Warp IDE    │◄──►│ MCP Server  │◄──►│ XMPP     │
│              │    │ (stdio)     │    │ Adapter  │
└──────────────┘    └─────────────┘    └──────────┘
```

Currently, the XMPP functionality is simulated for testing purposes. In the full implementation, the MCP server would integrate with the actual XMPP adapter and slixmpp library.

## Development

### Adding New Tools

To add new MCP tools:

1. Add the tool definition to `self.capabilities["tools"]` in `McpStdioServer.__init__`
2. Handle the tool call in `_handle_tools_call`
3. Implement the tool logic as a new method

### Testing Changes

Run the test suite:

```bash
python test_mcp_stdio.py
```

### Logging

The server logs to stderr with different levels:
- `DEBUG`: Protocol message details
- `INFO`: General operations and tool calls
- `WARNING`: Recoverable errors
- `ERROR`: Serious errors

Set the logging level by modifying the `logging.basicConfig()` call in the server code.

## Troubleshooting

### Server Won't Start
- Check Python version (requires 3.8+)
- Ensure all dependencies are installed
- Check for permission issues

### Warp IDE Can't Connect
- Verify the MCP server configuration in Warp IDE settings
- Check that `jabber-mcp-server` is in your PATH
- Look at stderr output for error messages

### Tools Not Working
- Use the test script to verify basic functionality
- Check the JSON-RPC message format
- Enable debug logging to see protocol details

## Future Enhancements

- Integration with actual XMPP server (slixmpp)
- Support for presence updates and roster management
- Message history and conversation threading
- End-to-end encryption (OMEMO) support
- Multi-user chat (MUC) functionality
