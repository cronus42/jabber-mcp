# XMPP-MCP Bridge 🔗

A production-ready bridge that connects XMPP messaging to Warp IDE through the Model Context Protocol (MCP). Send messages, manage contacts, and communicate across XMPP networks directly from your development environment.

## 🌟 Features

- **XMPP Integration**: Full-featured XMPP client using slixmpp
- **MCP Protocol**: Native Warp IDE integration via Model Context Protocol
- **Async Processing**: High-performance async message handling with back-pressure management
- **Gateway Support**: Works with XMPP-to-SMS gateways (like Cheogram)
- **Resilient Connections**: Auto-reconnect and robust error handling
- **Type Safety**: Full mypy type checking and modern Python practices

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repository-url>
cd jabber-mcp

# Install in development mode
pip install -e .

# Or install from PyPI (when published)
# pip install jabber-mcp
```

### 2. Environment Setup

Create a `.env` file or set environment variables:

```bash
# Required: Your XMPP credentials
export XMPP_USER="your-username@xmpp-server.com"
export XMPP_PASSWORD="your-password"

# Optional: Custom XMPP server (defaults to user domain)
# export XMPP_SERVER="custom-server.com"
# export XMPP_PORT="5222"
```

### 3. Warp IDE Configuration

Add to your Warp IDE MCP configuration file (`~/.warp/mcp_servers.json`):

```json
{
  "mcpServers": {
    "jabber-mcp": {
      "command": "jabber-mcp-server",
      "args": [],
      "env": {
        "XMPP_USER": "your-username@xmpp-server.com",
        "XMPP_PASSWORD": "your-password"
      },
      "stdio": true
    }
  }
}
```

### 4. Start Using

In Warp IDE, use the MCP tools:

- `send_xmpp_message`: Send messages to any XMPP JID
- `ping`: Test server connectivity

## 📱 Usage Examples

### Basic XMPP Messaging

```bash
# In Warp IDE MCP interface:
Tool: send_xmpp_message
Parameters:
  jid: "friend@jabber.org"
  message: "Hello from Warp IDE!"
```

### SMS via XMPP Gateway (Cheogram)

```bash
# Send SMS through Cheogram gateway:
Tool: send_xmpp_message
Parameters:
  jid: "+1234567890@cheogram.com"
  message: "SMS from your development environment!"
```

### Group Chat/MUC

```bash
# Send to group chat:
Tool: send_xmpp_message
Parameters:
  jid: "room@conference.server.com"
  message: "Deployment complete! 🚀"
```

## 🏗️ Architecture

```
Warp IDE
    ↓ (MCP JSON-RPC)
 MCP Server (stdio)
    ↓ (Internal API)
 XMPP-MCP Bridge
    ↓ (slixmpp)
 XMPP Network
    ↓ (Various protocols)
Users, SMS Gateways, Bots
```

### Core Components

- **MCP Server** (`mcp_stdio_server.py`): JSON-RPC 2.0 server for Warp IDE
- **XMPP-MCP Bridge** (`xmpp_mcp_bridge.py`): Connects MCP to XMPP adapter
- **XMPP Adapter** (`xmpp_adapter.py`): slixmpp-based XMPP client
- **Message Queue System**: Async queues with back-pressure handling

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed component design and flow diagrams.

## 🔧 Development

### Setup Development Environment

```bash
# Install development dependencies
pip install -e .[dev]

# Install pre-commit hooks
pre-commit install

# Run tests
pytest

# Run with coverage
pytest --cov=src/jabber_mcp --cov-report=html

# Type checking
mypy src/

# Linting and formatting
ruff check src/ tests/
ruff format src/ tests/
```

### Test Coverage

Current test coverage: **83%+**

- Unit tests for all core components
- Integration tests with mocked XMPP
- End-to-end tests for message delivery
- Performance and stress testing

### Running Tests

```bash
# All tests
pytest

# Specific test categories
pytest tests/test_unit/          # Unit tests
pytest tests/test_integration/   # Integration tests
pytest tests/test_e2e/          # End-to-end tests

# With real XMPP server (requires credentials)
XMPP_USER=test@server.com XMPP_PASSWORD=pass pytest tests/test_e2e/
```

## 🌐 XMPP Server Compatibility

Tested with:

- **ejabberd** ✅
- **Prosody** ✅ 
- **OpenFire** ✅
- **Tigase** ✅
- **MongooseIM** ✅

Supported features:
- SASL PLAIN authentication
- TLS/SSL connections
- Message carbons
- Message delivery receipts
- Multi-User Chat (MUC) basic support

## 🛡️ Security

- **Credential Management**: Environment variables only, never hardcoded
- **TLS Encryption**: All XMPP connections use TLS
- **Input Validation**: All MCP inputs validated and sanitized
- **Error Isolation**: Failures don't expose sensitive information

## 🐛 Troubleshooting

### Connection Issues

```bash
# Test XMPP connection directly
python -c "from src.jabber_mcp.test_xmpp_connection import main; main()"

# Check MCP server logs
jabber-mcp-server --debug
```

### Common Problems

1. **"Authentication failed"**
   - Verify XMPP_USER and XMPP_PASSWORD
   - Check if server requires app-specific passwords
   - Ensure account exists and is enabled

2. **"Connection timeout"**
   - Verify network connectivity to XMPP server
   - Check firewall settings (port 5222/5223)
   - Try different XMPP_SERVER if using custom server

3. **"Message not delivered"**
   - Verify recipient JID format
   - Check if recipient is online/reachable
   - For gateways, ensure proper number format

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Make your changes with tests
4. Ensure all tests pass and coverage ≥90%
5. Run pre-commit hooks (`pre-commit run --all-files`)
6. Submit a pull request

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/your-org/jabber-mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/jabber-mcp/discussions)
- **XMPP**: Send a message via the bridge! 😄

---

**Made with ❤️ for the Warp IDE community**
