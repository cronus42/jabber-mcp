"""MCP Bridge implementation for XMPP-MCP message routing."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Constants for message truncation
_MESSAGE_TRUNCATE_LENGTH = 100

# Constants for error handling and back-pressure
_DEFAULT_QUEUE_TIMEOUT = 5.0  # seconds
_QUEUE_PUT_TIMEOUT = 2.0  # seconds for put operations with back-pressure
_MAX_RETRY_ATTEMPTS = 3
_INITIAL_RETRY_DELAY = 1.0  # seconds
_MAX_RETRY_DELAY = 30.0  # seconds


class ConnectionState(Enum):
    """Connection state for error handling and reconnection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = _MAX_RETRY_ATTEMPTS
    initial_delay: float = _INITIAL_RETRY_DELAY
    max_delay: float = _MAX_RETRY_DELAY
    backoff_multiplier: float = 2.0
    jitter: bool = True


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

    async def send_to_jabber(
        self, jid: str, body: str, timeout: float = _QUEUE_PUT_TIMEOUT
    ) -> None:
        """Send a message to a Jabber/XMPP recipient with back-pressure handling.

        Args:
            jid: The Jabber ID of the recipient
            body: The message text to send
            timeout: Maximum time to wait for queue space (seconds)

        Raises:
            asyncio.TimeoutError: If queue put times out due to back-pressure
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
            # First try immediate put
            self.mcp_to_xmpp.put_nowait(message)
            truncated_body = (
                body[:_MESSAGE_TRUNCATE_LENGTH] + "..."
                if len(body) > _MESSAGE_TRUNCATE_LENGTH
                else body
            )
            logger.debug("Queued message to %s: %s", jid, truncated_body)
        except asyncio.QueueFull:
            # Queue is full, try with timeout for back-pressure handling
            logger.warning(
                "MCP to XMPP queue is full (%d/%d), attempting timed put to %s",
                self.mcp_to_xmpp.qsize(),
                self.mcp_to_xmpp.maxsize,
                jid,
            )
            try:
                await asyncio.wait_for(self.mcp_to_xmpp.put(message), timeout=timeout)
                truncated_body = (
                    body[:_MESSAGE_TRUNCATE_LENGTH] + "..."
                    if len(body) > _MESSAGE_TRUNCATE_LENGTH
                    else body
                )
                logger.debug(
                    "Queued message to %s after back-pressure delay: %s",
                    jid,
                    truncated_body,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "MCP to XMPP queue timeout after %.2fs, dropping message to %s",
                    timeout,
                    jid,
                )
                # NACK - we log the drop and re-raise for upstream handling
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
        self,
        jid: str,
        body: str,
        message_type: str = "chat",
        timeout: float = _QUEUE_PUT_TIMEOUT,
    ) -> None:
        """Handle an incoming XMPP message by queuing it for MCP processing.

        Args:
            jid: The sender's Jabber ID
            body: The message text
            message_type: The XMPP message type (chat, normal, etc.)
            timeout: Maximum time to wait for queue space (seconds)

        Raises:
            asyncio.TimeoutError: If queue put times out due to back-pressure
        """
        message = {
            "type": "received_message",
            "from_jid": jid,
            "body": body,
            "message_type": message_type,
            "timestamp": asyncio.get_event_loop().time(),
        }

        try:
            # First try immediate put
            self.xmpp_to_mcp.put_nowait(message)
            truncated_body = (
                body[:_MESSAGE_TRUNCATE_LENGTH] + "..."
                if len(body) > _MESSAGE_TRUNCATE_LENGTH
                else body
            )
            logger.debug("Queued incoming message from %s: %s", jid, truncated_body)
        except asyncio.QueueFull:
            # Queue is full, try with timeout for back-pressure handling
            logger.warning(
                "XMPP to MCP queue is full (%d/%d), attempting timed put from %s",
                self.xmpp_to_mcp.qsize(),
                self.xmpp_to_mcp.maxsize,
                jid,
            )
            try:
                await asyncio.wait_for(self.xmpp_to_mcp.put(message), timeout=timeout)
                truncated_body = (
                    body[:_MESSAGE_TRUNCATE_LENGTH] + "..."
                    if len(body) > _MESSAGE_TRUNCATE_LENGTH
                    else body
                )
                logger.debug(
                    "Queued message from %s after back-pressure delay: %s",
                    jid,
                    truncated_body,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "XMPP to MCP queue timeout after %.2fs, dropping message from %s",
                    timeout,
                    jid,
                )
                # NACK - we log the drop and re-raise for upstream handling
                raise

    async def handle_incoming_xmpp_presence(
        self,
        jid: str,
        presence_type: str,
        status: Optional[str] = None,
        timeout: float = _QUEUE_PUT_TIMEOUT,
    ) -> None:
        """Handle an incoming XMPP presence update.

        Args:
            jid: The Jabber ID whose presence changed
            presence_type: The presence type (available, unavailable, etc.)
            status: Optional status message
            timeout: Maximum time to wait for queue space (seconds)

        Raises:
            asyncio.TimeoutError: If queue put times out due to back-pressure
        """
        presence = {
            "type": "presence_update",
            "jid": jid,
            "presence_type": presence_type,
            "status": status,
            "timestamp": asyncio.get_event_loop().time(),
        }

        try:
            # First try immediate put
            self.xmpp_to_mcp.put_nowait(presence)
            logger.debug("Queued presence update from %s: %s", jid, presence_type)
        except asyncio.QueueFull:
            # Queue is full, try with timeout for back-pressure handling
            logger.warning(
                "XMPP to MCP queue is full (%d/%d), attempting timed put for presence from %s",
                self.xmpp_to_mcp.qsize(),
                self.xmpp_to_mcp.maxsize,
                jid,
            )
            try:
                await asyncio.wait_for(self.xmpp_to_mcp.put(presence), timeout=timeout)
                logger.debug(
                    "Queued presence from %s after back-pressure delay: %s",
                    jid,
                    presence_type,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "XMPP to MCP queue timeout after %.2fs, dropping presence from %s",
                    timeout,
                    jid,
                )
                # NACK - we log the drop and re-raise for upstream handling
                raise

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

    # Utility methods for error handling and retry logic

    @staticmethod
    def _calculate_retry_delay(attempt: int, config: RetryConfig) -> float:
        """Calculate retry delay with exponential backoff and optional jitter.

        Args:
            attempt: Current retry attempt (0-based)
            config: Retry configuration

        Returns:
            Delay in seconds before next retry
        """
        if attempt == 0:
            return 0  # No delay for first attempt

        # Exponential backoff: initial_delay * (backoff_multiplier ^ (attempt - 1))
        delay = config.initial_delay * (config.backoff_multiplier ** (attempt - 1))
        delay = min(delay, config.max_delay)  # Cap at max_delay

        # Add jitter to avoid thundering herd
        if config.jitter:
            # Add up to 25% random jitter
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
            delay = max(0, delay)  # Ensure non-negative

        return delay

    async def _retry_with_backoff(
        self,
        operation: Callable[[], Any],
        config: RetryConfig,
        operation_name: str = "operation",
    ) -> Any:
        """Execute an operation with retry and exponential backoff.

        Args:
            operation: Async callable to retry
            config: Retry configuration
            operation_name: Name for logging purposes

        Returns:
            Result of the successful operation

        Raises:
            Exception: Last exception if all retries fail
        """
        last_exception = None

        for attempt in range(config.max_attempts):
            try:
                logger.debug(
                    "Attempting %s (attempt %d/%d)",
                    operation_name,
                    attempt + 1,
                    config.max_attempts,
                )
                result = await operation()
                if attempt > 0:
                    logger.info(
                        "%s succeeded after %d retries", operation_name, attempt
                    )
                return result

            except Exception as e:
                last_exception = e
                if attempt + 1 >= config.max_attempts:
                    logger.error(
                        "%s failed after %d attempts: %s",
                        operation_name,
                        config.max_attempts,
                        e,
                    )
                    break

                delay = self._calculate_retry_delay(attempt + 1, config)
                logger.warning(
                    "%s failed (attempt %d/%d): %s. Retrying in %.2fs...",
                    operation_name,
                    attempt + 1,
                    config.max_attempts,
                    e,
                    delay,
                )

                if delay > 0:
                    await asyncio.sleep(delay)

        # Re-raise the last exception if all retries failed
        if last_exception:
            raise last_exception

    async def _safe_queue_get(
        self,
        queue: asyncio.Queue[dict[str, Any]],
        timeout: float = _DEFAULT_QUEUE_TIMEOUT,
    ) -> Optional[dict[str, Any]]:
        """Safely get item from queue with timeout handling.

        Args:
            queue: The queue to get from
            timeout: Maximum time to wait for an item

        Returns:
            Queue item or None if timeout/cancelled
        """
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            # This is expected during normal operation - just return None
            return None
        except asyncio.CancelledError:
            logger.debug("Queue get operation cancelled")
            raise
        except Exception as e:
            logger.error("Unexpected error getting from queue: %s", e)
            return None

    def get_connection_state(self) -> ConnectionState:
        """Get current connection state. Default implementation returns CONNECTED if running."""
        return (
            ConnectionState.CONNECTED if self._running else ConnectionState.DISCONNECTED
        )
