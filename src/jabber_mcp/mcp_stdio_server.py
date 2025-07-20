"""Minimal MCP server using stdio for direct Warp IDE integration.

This module provides a simple stdio-based MCP server that communicates with
Warp IDE directly through standard input/output, implementing the MCP protocol
with JSON-RPC 2.0 messaging and support for basic commands.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
    id: str | int | None = None
    method: str | None = None
    params: dict[str, Any] | None = None
    result: Any | None = None
    error: dict[str, Any] | None = None

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
        self.inbox = []  # Store inbox messages as dictionaries
        self.address_book = {}  # Store alias → JID mapping
        self.running = False
        # Initialize with some sample data for testing
        self._populate_sample_data()
        self.capabilities = {
            "prompts": {},
            "resources": {},
            "tools": {
                "inbox/list": {
                    "description": "returns an ordered summary of received messages (id, from, preview, timestamp).",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                "inbox/get": {
                    "description": "returns full body for a given message id.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"messageId": {"type": "string"}},
                        "required": ["messageId"],
                    },
                },
                "inbox/clear": {
                    "description": "empties or prunes the inbox.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                "address_book/query": {
                    "description": "fuzzy-search by name or JID and return matches.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
                "address_book/save": {
                    "description": "store an alias→JID mapping.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "alias": {"type": "string"},
                            "jid": {"type": "string"},
                        },
                        "required": ["alias", "jid"],
                    },
                },
                "send_xmpp_message": {
                    "description": "Send a message through XMPP",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "recipient": {
                                "type": "string",
                                "description": "The JID of the message recipient or an alias to resolve from the address book",
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

    async def _handle_message(self, message: JsonRpcMessage) -> JsonRpcMessage | None:
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
            elif method == "inbox/list":
                return await self._handle_inbox_list(message)
            elif method == "inbox/get":
                return await self._handle_inbox_get(message, params)
            elif method == "inbox/clear":
                return await self._handle_inbox_clear(message)
            elif method == "address_book/query":
                return await self._handle_address_book_query(message, params)
            elif method == "address_book/save":
                return await self._handle_address_book_save(message, params)
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
        self, message: JsonRpcMessage, params: dict[str, Any]
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
        self, message: JsonRpcMessage, _params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle MCP initialized notification."""
        logger.info("MCP server initialized successfully")
        return JsonRpcMessage(id=message.id, result={})

    async def _handle_tools_list(
        self, message: JsonRpcMessage, _params: dict[str, Any]
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
        self, message: JsonRpcMessage, params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        logger.info(f"Calling tool: {tool_name} with arguments: {arguments}")

        if tool_name == "send_xmpp_message":
            return await self._tool_send_message(message, arguments)
        elif tool_name == "ping":
            return await self._tool_ping(message, arguments)
        elif tool_name == "inbox/list":
            return await self._handle_inbox_list(message)
        elif tool_name == "inbox/get":
            return await self._handle_inbox_get(message, arguments)
        elif tool_name == "inbox/clear":
            return await self._handle_inbox_clear(message)
        elif tool_name == "address_book/query":
            return await self._handle_address_book_query(message, arguments)
        elif tool_name == "address_book/save":
            return await self._handle_address_book_save(message, arguments)
        else:
            return JsonRpcMessage(
                id=message.id,
                error={"code": -32601, "message": f"Tool not found: {tool_name}"},
            )

    async def _handle_ping(
        self, message: JsonRpcMessage, _params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle ping request."""
        return JsonRpcMessage(
            id=message.id,
            result={"status": "pong", "timestamp": asyncio.get_event_loop().time()},
        )

    async def _handle_inbox_list(self, message: JsonRpcMessage) -> JsonRpcMessage:
        """Handle inbox/list request."""
        summary = [
            {
                "id": msg["id"],
                "from": msg["from"],
                "preview": msg["body"][:50],
                "timestamp": msg["timestamp"],
            }
            for msg in sorted(self.inbox, key=lambda x: x["timestamp"])
        ]
        return JsonRpcMessage(id=message.id, result={"messages": summary})

    async def _handle_inbox_get(
        self, message: JsonRpcMessage, params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle inbox/get request."""
        message_id = params.get("messageId")
        for msg in self.inbox:
            if msg["id"] == message_id:
                return JsonRpcMessage(id=message.id, result=msg)
        return JsonRpcMessage(
            id=message.id, error={"code": -32602, "message": "Message not found"}
        )

    async def _handle_inbox_clear(self, message: JsonRpcMessage) -> JsonRpcMessage:
        """Handle inbox/clear request."""
        self.inbox.clear()
        return JsonRpcMessage(id=message.id, result={"status": "Inbox cleared"})

    async def _handle_address_book_query(
        self, message: JsonRpcMessage, params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle address_book/query request."""
        query = params.get("query", "").lower()
        matches = {}
        for alias, jid in self.address_book.items():
            if query in alias.lower() or query in jid.lower():
                matches[alias] = jid
        return JsonRpcMessage(id=message.id, result={"matches": matches})

    async def _handle_address_book_save(
        self, message: JsonRpcMessage, params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle address_book/save request."""
        alias = params.get("alias")
        jid = params.get("jid")
        self.address_book[alias] = jid
        return JsonRpcMessage(id=message.id, result={"status": "Entry saved"})

    def _populate_sample_data(self):
        """Populate with sample messages and address book entries for testing."""
        # Sample inbox messages
        current_time = time.time()
        self.inbox = [
            {
                "id": str(uuid.uuid4()),
                "from": "alice@example.com",
                "body": "Hello! How are you doing today?",
                "timestamp": current_time - 3600,  # 1 hour ago
            },
            {
                "id": str(uuid.uuid4()),
                "from": "bob@work.com",
                "body": "The meeting has been rescheduled to 3 PM tomorrow. Please confirm your attendance.",
                "timestamp": current_time - 1800,  # 30 minutes ago
            },
            {
                "id": str(uuid.uuid4()),
                "from": "team@project.org",
                "body": "Project update: We've completed the first milestone ahead of schedule!",
                "timestamp": current_time - 300,  # 5 minutes ago
            },
        ]

        # Sample address book entries
        self.address_book = {
            "alice": "alice@example.com",
            "bob": "bob@work.com",
            "team": "team@project.org",
            "support": "help@company.com",
        }

    def add_message_to_inbox(
        self, from_jid: str, body: str, timestamp: Optional[float] = None
    ):
        """Add a new message to the inbox."""
        if timestamp is None:
            timestamp = time.time()

        message = {
            "id": str(uuid.uuid4()),
            "from": from_jid,
            "body": body,
            "timestamp": timestamp,
        }
        self.inbox.append(message)
        logger.info(f"Added message to inbox from {from_jid}: {body[:50]}...")

    async def _tool_send_message(
        self, message: JsonRpcMessage, arguments: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle send_message tool call with alias resolution."""
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

        # Check if recipient has '@' to determine if it's already a JID or an alias
        resolved_recipient = recipient
        if "@" not in recipient:
            # It's an alias, try to resolve it via address book
            if recipient in self.address_book:
                resolved_recipient = self.address_book[recipient]
                logger.info(
                    f"Resolved alias '{recipient}' to JID '{resolved_recipient}'"
                )
            else:
                # Try fuzzy search in the basic address book
                matches = {}
                query_lower = recipient.lower()
                for alias, jid in self.address_book.items():
                    if query_lower in alias.lower() or query_lower in jid.lower():
                        matches[alias] = jid

                if not matches:
                    return JsonRpcMessage(
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": f"No matches found for alias '{recipient}' in address book",
                        },
                    )
                elif len(matches) > 1:
                    # Multiple matches - show them to user for disambiguation
                    match_list = "\n".join(
                        [f"  {alias} -> {jid}" for alias, jid in matches.items()]
                    )
                    return JsonRpcMessage(
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": f"Ambiguous alias '{recipient}'. Multiple matches found:\n{match_list}\n\nPlease use the exact alias or JID.",
                        },
                    )
                else:
                    # Single match found
                    alias, jid = next(iter(matches.items()))
                    resolved_recipient = jid
                    logger.info(
                        f"Resolved alias '{recipient}' to JID '{jid}' via fuzzy match"
                    )

        # Simulate sending XMPP message
        logger.info(f"Sending XMPP message to {resolved_recipient}: {msg_text}")

        # In a real implementation, this would use the XMPP adapter
        message_id = str(uuid.uuid4())

        result_text = f"Message sent successfully to {resolved_recipient}\nMessage ID: {message_id}\nContent: {msg_text}"
        if resolved_recipient != recipient:
            result_text = f"Message sent successfully to {resolved_recipient} (resolved from alias '{recipient}')\nMessage ID: {message_id}\nContent: {msg_text}"

        return JsonRpcMessage(
            id=message.id,
            result={
                "content": [
                    {
                        "type": "text",
                        "text": result_text,
                    }
                ]
            },
        )

    async def _tool_ping(
        self, message: JsonRpcMessage, _arguments: dict[str, Any]
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
