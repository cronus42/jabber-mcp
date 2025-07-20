"""Integrated XMPP-MCP server that connects MCP stdio to real XMPP functionality."""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional

from jabber_mcp.bridge.mcp_bridge import McpBridge
from jabber_mcp.mcp_stdio_server import JsonRpcMessage, McpStdioServer
from jabber_mcp.xmpp_adapter import XmppAdapter

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


class XmppMcpBridge(McpBridge):
    """Bridge implementation that connects MCP to XMPP."""

    def __init__(
        self, xmpp_adapter: Optional[XmppAdapter] = None, queue_size: int = 100
    ):
        super().__init__(queue_size)
        self.xmpp_adapter = xmpp_adapter
        self.received_messages = []
        self.sent_messages = []

    def set_xmpp_adapter(self, adapter: XmppAdapter):
        """Set the XMPP adapter for this bridge."""
        self.xmpp_adapter = adapter

    async def _process_xmpp_to_mcp(self) -> None:
        """Process messages from XMPP to MCP queue."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.xmpp_to_mcp, timeout=1.0)
                if message:
                    self.received_messages.append(message)
                    logger.info(f"Received XMPP message: {message}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing XMPP to MCP: {e}")

    async def _process_mcp_to_xmpp(self) -> None:
        """Process messages from MCP to XMPP queue."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.mcp_to_xmpp, timeout=1.0)
                if message and self.xmpp_adapter:
                    self.sent_messages.append(message)
                    if message.get("type") == "send_message":
                        jid = message.get("jid")
                        body = message.get("body")
                        if jid and body:
                            await self.xmpp_adapter.send_message_to_jid(jid, body)
                            logger.info(f"Sent XMPP message to {jid}: {body}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing MCP to XMPP: {e}")


class XmppMcpServer(McpStdioServer):
    """MCP Server with integrated XMPP functionality."""

    def __init__(
        self, xmpp_jid: Optional[str] = None, xmpp_password: Optional[str] = None
    ):
        super().__init__()
        self.xmpp_jid = xmpp_jid
        self.xmpp_password = xmpp_password
        self.bridge: Optional[XmppMcpBridge] = None
        self.xmpp_adapter: Optional[XmppAdapter] = None

    async def start(self) -> None:
        """Start the MCP server with XMPP integration."""
        # Initialize XMPP if credentials are provided
        if self.xmpp_jid and self.xmpp_password:
            logger.info(f"Initializing XMPP connection to {self.xmpp_jid}")
            self.bridge = XmppMcpBridge(queue_size=100)
            self.xmpp_adapter = XmppAdapter(
                self.xmpp_jid, self.xmpp_password, self.bridge
            )
            self.bridge.set_xmpp_adapter(self.xmpp_adapter)

            # Start the bridge
            await self.bridge.start()

            # Connect to XMPP server
            try:
                await self.xmpp_adapter.connect_and_wait()
                logger.info("XMPP connection established")
            except Exception as e:
                logger.error(f"Failed to connect to XMPP server: {e}")
                # Continue without XMPP

        # Start the stdio MCP server
        await super().start()

    async def _tool_send_message(
        self, message: JsonRpcMessage, arguments: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle send_message tool call with real XMPP integration."""
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

        # Try to send via XMPP if available
        if self.bridge and self.xmpp_adapter:
            try:
                await self.bridge.send_to_jabber(recipient, msg_text)
                logger.info(f"Sent XMPP message to {recipient}: {msg_text}")

                return JsonRpcMessage(
                    id=message.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Message sent successfully via XMPP to {recipient}\n"
                                    f"Content: {msg_text}"
                                ),
                            }
                        ]
                    },
                )
            except Exception as e:
                logger.error(f"Failed to send XMPP message: {e}")
                return JsonRpcMessage(
                    id=message.id,
                    error={
                        "code": -32603,
                        "message": "Failed to send XMPP message",
                        "data": str(e),
                    },
                )
        else:
            # Fallback to simulation
            logger.info(f"Simulating XMPP message to {recipient}: {msg_text}")
            return JsonRpcMessage(
                id=message.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Message simulated (no XMPP connection) to {recipient}\n"
                                f"Content: {msg_text}"
                            ),
                        }
                    ]
                },
            )

    async def _tool_ping(
        self, message: JsonRpcMessage, _arguments: Dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle ping tool call with XMPP status."""
        if self.xmpp_adapter and self.bridge:
            connection_state = self.bridge.get_connection_state()
            return JsonRpcMessage(
                id=message.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": f"PONG! XMPP connection status: {connection_state.value}",
                        }
                    ]
                },
            )
        else:
            return JsonRpcMessage(
                id=message.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": "PONG! No XMPP connection configured.",
                        }
                    ]
                },
            )


async def main():
    """Main entry point with environment variable configuration."""
    # Get XMPP credentials from environment variables
    xmpp_jid = os.getenv("XMPP_JID")
    xmpp_password = os.getenv("XMPP_PASSWORD")

    if xmpp_jid and xmpp_password:
        logger.info(f"Starting XMPP-MCP server with JID: {xmpp_jid}")
        server = XmppMcpServer(xmpp_jid, xmpp_password)
    else:
        logger.warning("No XMPP credentials found in environment variables")
        logger.info("Set XMPP_JID and XMPP_PASSWORD to enable XMPP functionality")
        server = XmppMcpServer()

    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
