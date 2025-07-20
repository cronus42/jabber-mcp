"""MCP Bridge implementation for XMPP-MCP message routing."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Constants for message truncation
_MESSAGE_TRUNCATE_LENGTH = 100


class McpBridge(ABC):
    """Abstract base class for MCP Bridge implementation.

    Provides async message queues and public API for bridging XMPP and MCP protocols.
    Implements back-pressure strategy with configurable queue sizes.
    """

    def __init__(self, queue_size: int = 100):
        """Initialize the MCP Bridge.

        Args:
            queue_size: Maximum size for async queues to implement back-pressure
        """
        self.queue_size = queue_size

        # Async queues for bidirectional message flow
        self.xmpp_to_mcp: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=queue_size
        )
        self.mcp_to_xmpp: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=queue_size
        )

        # Task management
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

        # Callbacks for incoming XMPP stanzas
        self._xmpp_message_callback: Optional[Callable[[dict[str, Any]], None]] = None
        self._xmpp_presence_callback: Optional[Callable[[dict[str, Any]], None]] = None

    async def start(self) -> None:
        """Launch async tasks for message processing.

        Starts the bridge tasks that process messages between XMPP and MCP queues.
        """
        if self._running:
            logger.warning("MCP Bridge is already running")
            return

        logger.info("Starting MCP Bridge with queue size %d", self.queue_size)
        self._running = True

        # Start message processing tasks
        self._tasks = [
            asyncio.create_task(
                self._process_xmpp_to_mcp(), name="xmpp_to_mcp_processor"
            ),
            asyncio.create_task(
                self._process_mcp_to_xmpp(), name="mcp_to_xmpp_processor"
            ),
        ]

        # Allow subclasses to start additional tasks
        await self._start_additional_tasks()

        logger.info("MCP Bridge started successfully")

    async def stop(self) -> None:
        """Graceful shutdown of the bridge.

        Stops all running tasks and cleans up resources.
        """
        if not self._running:
            logger.warning("MCP Bridge is not running")
            return

        logger.info("Stopping MCP Bridge...")
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

        # Allow subclasses to clean up
        await self._stop_additional_cleanup()

        logger.info("MCP Bridge stopped successfully")

    async def send_to_jabber(self, jid: str, body: str) -> None:
        """Send a message to a Jabber/XMPP recipient.

        Args:
            jid: The Jabber ID of the recipient
            body: The message text to send

        Raises:
            asyncio.QueueFull: If the mcp_to_xmpp queue is full
            ValueError: If jid or body are invalid
        """
        if not jid or not isinstance(jid, str):
            msg = "JID must be a non-empty string"
            raise ValueError(msg)
        if not isinstance(body, str):
            msg = "Body must be a string"
            raise ValueError(msg)

        message = {
            "type": "send_message",
            "jid": jid,
            "body": body,
            "timestamp": asyncio.get_event_loop().time(),
        }

        try:
            self.mcp_to_xmpp.put_nowait(message)
            truncated_body = (
                body[:_MESSAGE_TRUNCATE_LENGTH] + "..."
                if len(body) > _MESSAGE_TRUNCATE_LENGTH
                else body
            )
            logger.debug("Queued message to %s: %s", jid, truncated_body)
        except asyncio.QueueFull:
            logger.error("MCP to XMPP queue is full, dropping message to %s", jid)
            raise

    def set_xmpp_message_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Set callback for incoming XMPP message stanzas.

        Args:
            callback: Function to call when XMPP messages are received
        """
        self._xmpp_message_callback = callback

    def set_xmpp_presence_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Set callback for incoming XMPP presence stanzas.

        Args:
            callback: Function to call when XMPP presence updates are received
        """
        self._xmpp_presence_callback = callback

    async def handle_incoming_xmpp_message(
        self, jid: str, body: str, message_type: str = "chat"
    ) -> None:
        """Handle an incoming XMPP message by queuing it for MCP processing.

        Args:
            jid: The sender's Jabber ID
            body: The message text
            message_type: The XMPP message type (chat, normal, etc.)
        """
        message = {
            "type": "received_message",
            "from_jid": jid,
            "body": body,
            "message_type": message_type,
            "timestamp": asyncio.get_event_loop().time(),
        }

        try:
            self.xmpp_to_mcp.put_nowait(message)
            truncated_body = (
                body[:_MESSAGE_TRUNCATE_LENGTH] + "..."
                if len(body) > _MESSAGE_TRUNCATE_LENGTH
                else body
            )
            logger.debug("Queued incoming message from %s: %s", jid, truncated_body)
        except asyncio.QueueFull:
            logger.warning("XMPP to MCP queue is full, dropping message from %s", jid)

    async def handle_incoming_xmpp_presence(
        self, jid: str, presence_type: str, status: Optional[str] = None
    ) -> None:
        """Handle an incoming XMPP presence update.

        Args:
            jid: The Jabber ID whose presence changed
            presence_type: The presence type (available, unavailable, etc.)
            status: Optional status message
        """
        presence = {
            "type": "presence_update",
            "jid": jid,
            "presence_type": presence_type,
            "status": status,
            "timestamp": asyncio.get_event_loop().time(),
        }

        try:
            self.xmpp_to_mcp.put_nowait(presence)
            logger.debug("Queued presence update from %s: %s", jid, presence_type)
        except asyncio.QueueFull:
            logger.warning(
                "XMPP to MCP queue is full, dropping presence update from %s", jid
            )

    @property
    def is_running(self) -> bool:
        """Check if the bridge is currently running."""
        return self._running

    @property
    def queue_stats(self) -> dict[str, int]:
        """Get current queue statistics."""
        return {
            "xmpp_to_mcp_size": self.xmpp_to_mcp.qsize(),
            "mcp_to_xmpp_size": self.mcp_to_xmpp.qsize(),
            "xmpp_to_mcp_maxsize": self.xmpp_to_mcp.maxsize,
            "mcp_to_xmpp_maxsize": self.mcp_to_xmpp.maxsize,
        }

    # Abstract methods for subclasses to implement

    @abstractmethod
    async def _process_xmpp_to_mcp(self) -> None:
        """Process messages from XMPP to MCP queue.

        This method should continuously process messages from the xmpp_to_mcp queue
        and handle them appropriately (e.g., send to MCP client, log, etc.).
        """

    @abstractmethod
    async def _process_mcp_to_xmpp(self) -> None:
        """Process messages from MCP to XMPP queue.

        This method should continuously process messages from the mcp_to_xmpp queue
        and handle them appropriately (e.g., send via XMPP client).
        """

    async def _start_additional_tasks(self) -> None:
        """Hook for subclasses to start additional tasks.

        Called during start() after core tasks are started.
        """

    async def _stop_additional_cleanup(self) -> None:
        """Hook for subclasses to perform additional cleanup.

        Called during stop() after core tasks are cancelled.
        """
