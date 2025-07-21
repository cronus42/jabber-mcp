import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import slixmpp
from slixmpp import JID
from slixmpp.xmlstream import ElementBase

from jabber_mcp.bridge.mcp_bridge import ConnectionState, McpBridge, RetryConfig

logger = logging.getLogger(__name__)


class XmppAdapter(slixmpp.ClientXMPP):
    def __init__(self, jid: str, password: str, mcp_bridge: McpBridge | None = None):
        super().__init__(jid, password)
        self.mcp_bridge = mcp_bridge
        self._outbound_task: asyncio.Task | None = None
        self._connection_state = ConnectionState.DISCONNECTED
        self._reconnect_attempts = 0
        self._retry_config = RetryConfig(
            max_attempts=5, initial_delay=3.0, max_delay=120.0
        )
        self._auto_reconnect = True
        self._connection_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._is_intentionally_disconnecting = False
        self._session_started = False

        # Set reasonable connection timeout and SASL configuration
        self.ca_certs = None  # Don't verify SSL certs for now
        self.use_tls = True
        self.use_ssl = False

        # Disable problematic SASL mechanisms that cause "Invalid channel binding" errors
        self.disable_starttls = False
        self.use_tls = True

        # Set whitespace keepalive to None to prevent scheduling conflicts
        self.whitespace_keepalive = True
        self.whitespace_keepalive_interval = 30

        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("message", self.message_received)
        self.add_event_handler("disconnected", self.on_disconnected)
        self.add_event_handler("connection_failed", self.on_connection_failed)
        self.add_event_handler("failed_auth", self.on_failed_auth)
        self.add_event_handler("stream_error", self.on_stream_error)

        # Configure SASL mechanisms to avoid "Invalid channel binding" errors
        # Disable SCRAM-SHA-*-PLUS mechanisms that require channel binding
        try:
            if hasattr(self, "register_sasl_mechanism"):
                # Remove problematic SASL mechanisms
                self.sasl_mech = None  # Let slixmpp choose appropriate mechanism

                # Register a handler to modify SASL mechanisms during auth
                self.add_event_handler(
                    "sasl_auth_start", self._configure_sasl_mechanisms
                )
        except Exception as e:
            logger.warning(f"Could not configure SASL mechanisms: {e}")

        # Add roster event handlers
        self.add_event_handler("roster_update", self.on_roster_update)
        self.add_event_handler("roster_subscription", self.on_roster_subscription)

        # Start outbound message processing if bridge is provided
        if self.mcp_bridge:
            self._start_outbound_processing()

    async def session_start(self, _event: dict[str, Any]) -> None:
        """Handle session start event."""
        self._connection_state = ConnectionState.CONNECTED
        self._reconnect_attempts = (
            0  # Reset reconnect attempts on successful connection
        )
        self._is_intentionally_disconnecting = False
        self._session_started = True
        logger.info(f"XMPP session started successfully for {self.boundjid}")

        try:
            self.send_presence()
            logger.info("Presence sent successfully")

            await self.get_roster()
            logger.info("Roster retrieved successfully")

            # Sync roster with bridge after successful session start
            await self._sync_roster_with_bridge()
            logger.info("Session startup completed successfully")
        except Exception as e:
            logger.error(f"Error during session startup: {e}")
            # Don't disconnect on roster sync errors, session is still valid
            if "roster" not in str(e).lower():
                raise

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
        # Reduced log level to INFO for normalized content
        logging.info(f"Normalized content: {normalized_content}")
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
                        logging.info(f"Sent outbound message to {jid}")
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
        # Skip if we're intentionally disconnecting
        if self._is_intentionally_disconnecting:
            logger.info("XMPP disconnected intentionally")
            self._connection_state = ConnectionState.DISCONNECTED
            self._session_started = False
            return

        # Log details about the disconnection
        logger.warning(
            f"XMPP connection lost - Event: {event}, Session was started: {self._session_started}"
        )

        if self._connection_state != ConnectionState.DISCONNECTED:
            self._connection_state = ConnectionState.DISCONNECTED
            self._session_started = False

            # Only attempt reconnect if auto-reconnect is enabled and we're not already reconnecting
            if self._auto_reconnect and (
                not self._reconnect_task or self._reconnect_task.done()
            ):
                logger.info("Scheduling reconnection attempt")
                self._reconnect_task = asyncio.create_task(self._attempt_reconnect())

    async def on_connection_failed(self, event):
        """Handle connection failure events."""
        # Log more details about the connection failure
        logger.warning(
            f"XMPP connection failed (attempt {self._reconnect_attempts + 1}) - Event: {event}"
        )
        self._connection_state = ConnectionState.FAILED
        self._session_started = False

        # Only attempt reconnect if auto-reconnect is enabled and we're not already reconnecting
        if self._auto_reconnect and (
            not self._reconnect_task or self._reconnect_task.done()
        ):
            logger.info("Scheduling reconnection attempt after connection failure")
            self._reconnect_task = asyncio.create_task(self._attempt_reconnect())

    async def connect_and_wait(self) -> None:
        """Attempt to connect and handle auto-reconnect logic."""
        if self._connection_task and not self._connection_task.done():
            # Lift level to INFO for connection in progress
            logger.info("Connection attempt already in progress")
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
        try:
            # Clean up any existing scheduled events to prevent conflicts
            if hasattr(self, "scheduler") and self.scheduler:
                try:
                    # Remove existing keepalive events
                    self.scheduler.remove("Whitespace Keepalive")
                except (ValueError, KeyError):
                    # Event doesn't exist, which is fine
                    pass

            # Connect to the server
            if self.connect():
                logger.info("XMPP connection established")
            else:
                msg = "Failed to connect to XMPP server"
                raise Exception(msg)

        except Exception as e:
            logger.error(f"Error during connection attempt: {e}")
            raise

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect with back-off."""
        try:
            # Check if we've exceeded max reconnect attempts
            if self._reconnect_attempts >= self._retry_config.max_attempts:
                logger.error(
                    f"Max reconnection attempts ({self._retry_config.max_attempts}) exceeded, disabling auto-reconnect"
                )
                self._auto_reconnect = False
                return

            self._connection_state = ConnectionState.RECONNECTING
            self._reconnect_attempts += 1

            # Use static method directly as mcp_bridge may not exist
            delay = McpBridge._calculate_retry_delay(
                self._reconnect_attempts, self._retry_config
            )

            # Log reconnect attempts less frequently to reduce noise
            max_frequent_logs = 3
            log_every_n_attempts = 5
            if (
                self._reconnect_attempts <= max_frequent_logs
                or self._reconnect_attempts % log_every_n_attempts == 0
            ):
                logger.info(
                    "Reconnect attempt %d/%d after %.1fs",
                    self._reconnect_attempts,
                    self._retry_config.max_attempts,
                    delay,
                )

            await asyncio.sleep(delay)
            await self.connect_and_wait()
        except asyncio.CancelledError:
            logger.info("Reconnection cancelled")
            raise
        except Exception as e:
            logger.error(f"Error during reconnection attempt: {e}")

    async def on_failed_auth(self, event):
        """Handle authentication failure events."""
        logger.error(f"XMPP authentication failed - Event: {event}")
        # Don't auto-reconnect on auth failures - likely credential issue
        self._auto_reconnect = False
        self._connection_state = ConnectionState.FAILED

    async def on_stream_error(self, error):
        """Handle XMPP stream errors."""
        logger.error(f"XMPP stream error: {error}")
        # Stream errors often require reconnection
        self._connection_state = ConnectionState.FAILED

    async def disconnect(self, *args, **kwargs):
        """Override disconnect to clean up outbound processing task."""
        self._is_intentionally_disconnecting = True
        self._auto_reconnect = (
            False  # Disable auto-reconnect when manually disconnecting
        )
        self._connection_state = ConnectionState.DISCONNECTED

        # Cancel any ongoing reconnection attempts
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        # Cancel outbound processing task
        if self._outbound_task and not self._outbound_task.done():
            self._outbound_task.cancel()
            try:
                await self._outbound_task
            except asyncio.CancelledError:
                pass

        # Clean up scheduled events to prevent conflicts on reconnection
        try:
            if hasattr(self, "scheduler") and self.scheduler:
                self.scheduler.remove("Whitespace Keepalive")
        except (ValueError, KeyError):
            # Event doesn't exist, which is fine
            pass

        return await super().disconnect(*args, **kwargs)

    # Roster management methods

    async def _sync_roster_with_bridge(self) -> None:
        """Sync current roster with the MCP bridge.

        Called after successful session start to initialize the bridge
        with the current roster state.
        """
        if not self.mcp_bridge:
            # Removed unnecessary log for MCP bridge unavailability
            # logger.info("No MCP bridge available, skipping roster sync")
            return

        try:
            logger.info("Syncing roster with MCP bridge")
            roster_entries = self._parse_roster()

            if not roster_entries:
                logger.info("Roster is empty, nothing to sync")
                return

            logger.info(f"Found {len(roster_entries)} roster entries to sync")

            # Call the sync_roster method if the bridge supports it
            if hasattr(self.mcp_bridge, "sync_roster"):
                stats = await self.mcp_bridge.sync_roster(roster_entries)
                logger.info(f"Roster sync completed: {stats}")
            else:
                logger.warning("MCP bridge does not support roster sync")
                # Fall back to logging
                for jid, name in roster_entries:
                    logger.info(f"Roster entry: {jid} (name: {name})")

        except Exception as e:
            logger.error(f"Failed to sync roster with bridge: {e}")

    def _parse_roster(self) -> List[Tuple[str, Optional[str]]]:
        """Parse the current roster and return list of (jid, name) tuples.

        Returns:
            List of tuples containing (jid_string, display_name_or_none)

        Raises:
            Exception: If roster parsing fails
        """
        try:
            roster_entries: List[Tuple[str, Optional[str]]] = []

            if not hasattr(self, "client_roster") or self.client_roster is None:
                logger.warning("Client roster is not available")
                return roster_entries

            # Removed debugging info for parsing roster entries
            # logger.info("Parsing roster entries")

            # Iterate through roster items
            for jid_str in self.client_roster:
                try:
                    roster_item = self.client_roster[jid_str]

                    # Get the display name (if available) using direct attribute access
                    name = getattr(roster_item, "name", None) if roster_item else None

                    # Add to our list
                    roster_entries.append((jid_str, name))
                    logger.info(f"Added roster entry: {jid_str} (name: {name})")

                except Exception as item_error:
                    logger.warning(
                        f"Failed to parse roster item {jid_str}: {item_error}"
                    )
                    # Continue processing other items
                    continue

            logger.info(f"Successfully parsed {len(roster_entries)} roster entries")
            return roster_entries

        except Exception as e:
            logger.error(f"Error parsing roster: {e}")
            raise

    async def on_roster_update(self, event: dict[str, Any]) -> None:
        """Handle roster update events.

        Called when the roster is updated (contacts added/removed/modified).

        Args:
            event: Roster update event data
        """
        try:
            logger.info(f"Roster update event received: {event}")

            if not self.mcp_bridge:
                # Removed unnecessary log for skipped roster update
                # logger.info("No MCP bridge available, skipping roster update")
                return

            # Re-sync the entire roster after update
            await self._sync_roster_with_bridge()

        except Exception as e:
            logger.error(f"Failed to handle roster update: {e}")

    async def on_roster_subscription(self, event: dict[str, Any]) -> None:
        """Handle roster subscription events.

        Called when subscription status changes (subscribe/unsubscribe/etc).

        Args:
            event: Roster subscription event data
        """
        try:
            logger.info(f"Roster subscription event received: {event}")

            if not self.mcp_bridge:
                logger.debug("No MCP bridge available, skipping subscription event")
                return

            # Re-sync the entire roster after subscription change
            await self._sync_roster_with_bridge()

        except Exception as e:
            logger.error(f"Failed to handle roster subscription: {e}")

    async def _configure_sasl_mechanisms(self, event):
        """Configure SASL mechanisms to avoid channel binding issues."""
        try:
            # If we have access to the mechanism list, remove PLUS variants
            if hasattr(self, "features") and hasattr(self.features, "mechanisms"):
                mechanisms = self.features.mechanisms
                if mechanisms and hasattr(mechanisms, "mechanisms"):
                    # Remove SCRAM-SHA-*-PLUS mechanisms that require channel binding
                    problematic_mechs = [
                        "SCRAM-SHA-1-PLUS",
                        "SCRAM-SHA-256-PLUS",
                        "SCRAM-SHA-512-PLUS",
                    ]

                    for mech in problematic_mechs:
                        if mech in mechanisms.mechanisms:
                            logger.info(f"Removing problematic SASL mechanism: {mech}")
                            mechanisms.mechanisms.remove(mech)

                    logger.info(
                        f"Available SASL mechanisms: {list(mechanisms.mechanisms.keys()) if mechanisms.mechanisms else 'None'}"
                    )
        except Exception as e:
            logger.warning(f"Could not configure SASL mechanisms: {e}")
