import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import slixmpp
from slixmpp import JID
from slixmpp.xmlstream import ElementBase

from jabber_mcp.bridge.mcp_bridge import ConnectionState, McpBridge, RetryConfig

logger = logging.getLogger(__name__)


class XmppAdapter(slixmpp.ClientXMPP):
    def __init__(self, jid: str, password: str, mcp_bridge: Optional[McpBridge] = None):
        super().__init__(jid, password)
        self.mcp_bridge = mcp_bridge
        self._outbound_task: Optional[asyncio.Task] = None
        self._connection_state = ConnectionState.DISCONNECTED
        self._reconnect_attempts = 0
        self._retry_config = RetryConfig()
        self._auto_reconnect = True
        self._connection_task: Optional[asyncio.Task] = None

        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("message", self.message_received)
        self.add_event_handler("disconnected", self.on_disconnected)
        self.add_event_handler("connection_failed", self.on_connection_failed)

        # Start outbound message processing if bridge is provided
        if self.mcp_bridge:
            self._start_outbound_processing()

    async def session_start(self, _event: Dict[str, Any]) -> None:
        """Handle session start event."""
        self._connection_state = ConnectionState.CONNECTED
        self._reconnect_attempts = 0
        logging.info("XMPP session started")
        self.send_presence()
        await self.get_roster()

    def message_received(self, msg: ElementBase):
        if msg["type"] in ("chat", "normal"):
            logging.debug(f"Message received from {msg['from']}: {msg['body']}")

            # Enqueue to xmpp_to_mcp if bridge is available
            if self.mcp_bridge and msg["body"]:
                asyncio.create_task(self._enqueue_to_mcp(msg))

            task = asyncio.create_task(self.process_message(msg))
            # Store task reference to prevent it from being garbage collected
            task.add_done_callback(lambda _: None)

    async def process_message(self, msg: ElementBase):
        # TODO: Implement message processing logic
        logging.info(f"Processing message from {msg['from']}: {msg['body']}")

    async def normalize_format(self, content: str) -> str:
        # Placeholder for normalization logic
        normalized_content = content.strip()
        logging.debug(f"Normalized content: {normalized_content}")
        return normalized_content

    async def send_message_to_jid(self, to_jid: str, content: str):
        normalized_content = await self.normalize_format(content)
        try:
            self.send_message(mto=JID(to_jid), mbody=normalized_content, mtype="chat")
            logging.info(f"Sent message to {to_jid}: {normalized_content}")
        except Exception as e:
            logging.error(f"Failed to send message to {to_jid}: {e}")

    def _start_outbound_processing(self):
        """Start the outbound message processing task."""
        if self._outbound_task is None or self._outbound_task.done():
            self._outbound_task = asyncio.create_task(self._process_outbound_messages())
            self._outbound_task.add_done_callback(lambda _: None)

    async def _enqueue_to_mcp(self, msg: ElementBase):
        """Enqueue incoming XMPP message to MCP bridge with error handling."""
        if self.mcp_bridge:
            try:
                await self.mcp_bridge.handle_incoming_xmpp_message(
                    jid=str(msg["from"]),
                    body=str(msg["body"]),
                    message_type=str(msg["type"]),
                )
            except asyncio.TimeoutError:
                # NACK due to back-pressure - message dropped with warning
                logging.warning(
                    f"Message from {msg['from']} dropped due to queue back-pressure"
                )
            except Exception as e:
                logging.error(f"Failed to enqueue message to MCP bridge: {e}")

    async def _process_outbound_messages(self):
        """Process outbound messages from MCP to XMPP queue."""
        if not self.mcp_bridge:
            return

        while True:
            try:
                # Wait for messages in the mcp_to_xmpp queue with timeout
                message = await self.mcp_bridge._safe_queue_get(
                    self.mcp_bridge.mcp_to_xmpp, timeout=5.0
                )

                if message is None:
                    # Timeout occurred, continue loop
                    continue

                if message.get("type") == "send_message":
                    jid = message.get("jid")
                    body = message.get("body")

                    if jid and body:
                        # Use slixmpp.ClientXMPP.send_message to send the message
                        await self.send_message_to_jid(jid, body)
                        logging.debug(f"Sent outbound message to {jid}")
                    else:
                        logging.warning(f"Invalid outbound message format: {message}")

                # Mark task as done
                self.mcp_bridge.mcp_to_xmpp.task_done()

            except asyncio.CancelledError:
                logging.info("Outbound message processing cancelled")
                break
            except Exception as e:
                logging.error(f"Error processing outbound message: {e}")
                await asyncio.sleep(1)  # Brief delay on error

    async def on_disconnected(self, event):
        """Handle disconnection events."""
        if self._connection_state != ConnectionState.DISCONNECTED:
            logger.warning("XMPP connection lost")
            self._connection_state = ConnectionState.DISCONNECTED
            if self._auto_reconnect:
                await self._attempt_reconnect()

    async def on_connection_failed(self, event):
        """Handle connection failure events."""
        logger.error("XMPP connection failed")
        self._connection_state = ConnectionState.FAILED
        if self._auto_reconnect:
            await self._attempt_reconnect()

    async def connect_and_wait(self) -> None:
        """Attempt to connect and handle auto-reconnect logic."""
        if self._connection_task and not self._connection_task.done():
            logger.debug("Connection attempt already in progress")
            return

        self._connection_task = asyncio.create_task(self._do_connect())
        try:
            await self._connection_task
        finally:
            self._connection_task = None

    async def _do_connect(self) -> None:
        """Internal connection method with retry logic."""
        retry_config = RetryConfig(max_attempts=3, initial_delay=1.0)

        async def connect_operation():
            self._connection_state = ConnectionState.CONNECTING
            logger.info("Attempting XMPP connection...")

            if self.mcp_bridge:
                await self.mcp_bridge._retry_with_backoff(
                    self._connect_once, retry_config, "xmpp_connection"
                )
            else:
                await self._connect_once()

        try:
            await connect_operation()
        except Exception as e:
            logger.error(f"Connection failed after all retries: {e}")
            self._connection_state = ConnectionState.FAILED
            if self._auto_reconnect:
                await self._attempt_reconnect()

    async def _connect_once(self) -> None:
        """Single connection attempt."""
        # Connect to the server
        if self.connect():
            # Run the XMPP client until disconnected
            await self.process(forever=False)
        else:
            msg = "Failed to connect to XMPP server"
            raise Exception(msg)

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect with back-off."""
        self._connection_state = ConnectionState.RECONNECTING
        self._reconnect_attempts += 1
        # Use static method directly as mcp_bridge may not exist
        delay = McpBridge._calculate_retry_delay(
            self._reconnect_attempts, self._retry_config
        )
        logger.warning(
            "Reconnect attempt %d after %.2fs", self._reconnect_attempts, delay
        )
        await asyncio.sleep(delay)
        await self.connect_and_wait()

    async def disconnect(self, *args, **kwargs):
        """Override disconnect to clean up outbound processing task."""
        self._connection_state = ConnectionState.DISCONNECTED
        if self._outbound_task and not self._outbound_task.done():
            self._outbound_task.cancel()
            try:
                await self._outbound_task
            except asyncio.CancelledError:
                pass

        return await super().disconnect(*args, **kwargs)
