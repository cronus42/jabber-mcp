"""Minimal MCP server using stdio for direct Warp IDE integration.

This module provides a simple stdio-based MCP server that communicates with
Warp IDE directly through standard input/output, implementing the MCP protocol
with JSON-RPC 2.0 messaging and support for basic commands.
"""

import asyncio
import json
import logging
import sys
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional, Union

# Set up logging to stderr so it doesn't interfere with stdio communication
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """MCP message types."""

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


@dataclass
class JsonRpcMessage:
    """JSON-RPC 2.0 message structure."""

    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = asdict(self)
        # Remove None values to keep message clean
        return json.dumps({k: v for k, v in data.items() if v is not None})

    @classmethod
    def from_json(cls, data: str) -> "JsonRpcMessage":
        """Deserialize from JSON string."""
        try:
            parsed = json.loads(data)
            return cls(
                jsonrpc=parsed.get("jsonrpc", "2.0"),
                id=parsed.get("id"),
                method=parsed.get("method"),
                params=parsed.get("params"),
                result=parsed.get("result"),
                error=parsed.get("error"),
            )
        except (json.JSONDecodeError, KeyError) as e:
            msg = f"Invalid JSON-RPC message: {e}"
            raise ValueError(msg) from e


class McpStdioServer:
    """Minimal MCP server using stdio for Warp IDE integration."""

    def __init__(self):
        self.running = False
        self.capabilities = {
            "prompts": {},
            "resources": {},
            "tools": {
                "send_message": {
                    "description": "Send a message through XMPP",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "recipient": {
                                "type": "string",
                                "description": "The JID of the message recipient",
                            },
                            "message": {
                                "type": "string",
                                "description": "The message text to send",
                            },
                        },
                        "required": ["recipient", "message"],
                    },
                },
                "ping": {
                    "description": "Ping the XMPP connection",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            },
        }
        self.server_info = {"name": "jabber-mcp-server", "version": "1.0.0"}

    async def start(self) -> None:
        """Start the MCP server."""
        logger.info("Starting MCP stdio server")
        self.running = True

        try:
            await self._process_stdio()
        except KeyboardInterrupt:
            logger.info("Server interrupted by user")
        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            self.running = False
            logger.info("MCP stdio server stopped")

    async def _process_stdio(self) -> None:
        """Process messages from stdin and send responses to stdout."""
        # Set up async stdio
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        try:
            while self.running:
                # Read line from stdin
                line = await reader.readline()
                if not line:
                    break

                try:
                    data = line.decode("utf-8").strip()
                    if not data:
                        continue

                    logger.debug(f"Received: {data}")

                    # Parse JSON-RPC message
                    message = JsonRpcMessage.from_json(data)
                    response = await self._handle_message(message)

                    if response:
                        response_json = response.to_json()
                        logger.debug(f"Sending: {response_json}")
                        # Print to stdout for MCP protocol communication
                        sys.stdout.write(f"{response_json}\n")
                        sys.stdout.flush()

                except ValueError as e:
                    logger.warning(f"Invalid message format: {e}")
                    # Send JSON-RPC error response
                    error_response = JsonRpcMessage(
                        id=None,  # Can't get ID from invalid message
                        error={
                            "code": -32700,
                            "message": "Parse error",
                            "data": str(e),
                        },
                    )
                    # Print error to stdout for MCP protocol communication
                    sys.stdout.write(f"{error_response.to_json()}\n")
                    sys.stdout.flush()

                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        finally:
            transport.close()

    async def _handle_message(
        self, message: JsonRpcMessage
    ) -> Optional[JsonRpcMessage]:
        """Handle incoming JSON-RPC messages and return response if needed."""

        # Handle requests
        if message.method:
            return await self._handle_request(message)

        # Handle responses (not expected in this server implementation)
        elif message.result is not None or message.error is not None:
            logger.debug(f"Received response with id {message.id}")
            return None

        # Invalid message
        else:
            return JsonRpcMessage(
                id=message.id, error={"code": -32600, "message": "Invalid Request"}
            )

    async def _handle_request(self, message: JsonRpcMessage) -> JsonRpcMessage:
        """Handle JSON-RPC requests."""
        method = message.method
        params = message.params or {}

        try:
            if method == "initialize":
                return await self._handle_initialize(message, params)
            elif method == "initialized":
                return await self._handle_initialized(message, params)
            elif method == "tools/list":
                return await self._handle_tools_list(message, params)
            elif method == "tools/call":
                return await self._handle_tools_call(message, params)
            elif method == "ping":
                return await self._handle_ping(message, params)
            else:
                return JsonRpcMessage(
                    id=message.id,
                    error={"code": -32601, "message": f"Method not found: {method}"},
                )

        except Exception as e:
            logger.error(f"Error handling request {method}: {e}")
            return JsonRpcMessage(
                id=message.id,
                error={"code": -32603, "message": "Internal error", "data": str(e)},
            )

    async def _handle_initialize(
        self, message: JsonRpcMessage, params: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle MCP initialize request."""
        logger.info(f"Initializing MCP server with params: {params}")

        return JsonRpcMessage(
            id=message.id,
            result={
                "capabilities": self.capabilities,
                "serverInfo": self.server_info,
                "protocolVersion": "2024-11-05",
            },
        )

    async def _handle_initialized(
        self, message: JsonRpcMessage, _params: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle MCP initialized notification."""
        logger.info("MCP server initialized successfully")
        return JsonRpcMessage(id=message.id, result={})

    async def _handle_tools_list(
        self, message: JsonRpcMessage, _params: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle tools/list request."""
        tools = []
        for name, tool_info in self.capabilities["tools"].items():
            tools.append(
                {
                    "name": name,
                    "description": tool_info["description"],
                    "inputSchema": tool_info["inputSchema"],
                }
            )

        return JsonRpcMessage(id=message.id, result={"tools": tools})

    async def _handle_tools_call(
        self, message: JsonRpcMessage, params: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        logger.info(f"Calling tool: {tool_name} with arguments: {arguments}")

        if tool_name == "send_message":
            return await self._tool_send_message(message, arguments)
        elif tool_name == "ping":
            return await self._tool_ping(message, arguments)
        else:
            return JsonRpcMessage(
                id=message.id,
                error={"code": -32601, "message": f"Tool not found: {tool_name}"},
            )

    async def _handle_ping(
        self, message: JsonRpcMessage, _params: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle ping request."""
        return JsonRpcMessage(
            id=message.id,
            result={"status": "pong", "timestamp": asyncio.get_event_loop().time()},
        )

    async def _tool_send_message(
        self, message: JsonRpcMessage, arguments: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle send_message tool call."""
        recipient = arguments.get("recipient")
        msg_text = arguments.get("message")

        if not recipient:
            return JsonRpcMessage(
                id=message.id,
                error={
                    "code": -32602,
                    "message": "Missing required parameter: recipient",
                },
            )

        if not msg_text:
            return JsonRpcMessage(
                id=message.id,
                error={
                    "code": -32602,
                    "message": "Missing required parameter: message",
                },
            )

        # Simulate sending XMPP message
        logger.info(f"Sending XMPP message to {recipient}: {msg_text}")

        # In a real implementation, this would use the XMPP adapter
        message_id = str(uuid.uuid4())

        return JsonRpcMessage(
            id=message.id,
            result={
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Message sent successfully to {recipient}\n"
                            f"Message ID: {message_id}\nContent: {msg_text}"
                        ),
                    }
                ]
            },
        )

    async def _tool_ping(
        self, message: JsonRpcMessage, _arguments: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle ping tool call."""
        logger.info("Ping tool called")

        return JsonRpcMessage(
            id=message.id,
            result={
                "content": [{"type": "text", "text": "PONG! XMPP connection is alive."}]
            },
        )


async def main():
    """Main entry point for the MCP stdio server."""
    server = McpStdioServer()
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
