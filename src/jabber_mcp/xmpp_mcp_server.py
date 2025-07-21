"""Integrated XMPP-MCP server that connects MCP stdio to real XMPP functionality."""

import asyncio
import logging
import os
import re
import sys
import uuid
from collections import deque
from typing import Any, Dict, Optional

# Import for slug generation
try:
    from slugify import slugify
except ImportError:
    # Fallback implementation if python-slugify not available
    def slugify(text: str) -> str:
        """Simple fallback slugify implementation."""
        import re

        # Convert to lowercase and replace non-alphanumeric with dashes
        text = re.sub(r"[^\w\s-]", "", text).strip().lower()
        return re.sub(r"[\s_-]+", "-", text)


from jabber_mcp.address_book import AddressBook, AddressBookError
from jabber_mcp.bridge.mcp_bridge import McpBridge
from jabber_mcp.mcp_stdio_server import JsonRpcMessage, McpStdioServer
from jabber_mcp.xmpp_adapter import XmppAdapter

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

# Reduce verbosity of specific loggers to prevent log spam
logging.getLogger("slixmpp.xmlstream.xmlstream").setLevel(logging.WARNING)
logging.getLogger("slixmpp.xmlstream.resolver").setLevel(logging.WARNING)
logging.getLogger("slixmpp.features").setLevel(logging.INFO)
logging.getLogger("slixmpp.plugins").setLevel(logging.INFO)
logging.getLogger("slixmpp.clientxmpp").setLevel(logging.INFO)
logging.getLogger("slixmpp.basexmpp").setLevel(logging.INFO)
# Additional slixmpp loggers to quiet down
logging.getLogger("slixmpp").setLevel(logging.WARNING)  # Catch-all for slixmpp
logging.getLogger("root").setLevel(logging.WARNING)  # Root logger warnings

logger = logging.getLogger(__name__)

# Security validation patterns
_JID_REGEX = re.compile(r"^[^@/]+@[^@/]+(?:/.*)?$")
_ALIAS_REGEX = re.compile(
    r"^[a-zA-Z0-9_.-]+$"
)  # Alphanumeric, underscore, dot, dash only
_MAX_ALIAS_LENGTH = 50
_MAX_JID_LENGTH = 200
_MAX_MESSAGE_LENGTH = 8192  # 8KB message limit
_DANGEROUS_CHARS = {
    "<",
    ">",
    "&",
    '"',
    "'",
    ";",
    "|",
    "`",
    "$",
    "(",
    ")",
    "{",
    "}",
    "[",
    "]",
    "\\",
}


def _validate_jid_input(jid: str) -> bool:
    """Validate JID input to prevent injection attacks.

    Args:
        jid: The JID string to validate

    Returns:
        True if valid, False otherwise
    """
    if not jid or not isinstance(jid, str):
        return False

    jid = jid.strip()

    # Check length limits
    if len(jid) > _MAX_JID_LENGTH:
        return False

    # Check for dangerous characters
    if any(char in jid for char in _DANGEROUS_CHARS):
        return False

    # Check basic JID format
    return bool(_JID_REGEX.match(jid))


def _validate_alias_input(alias: str) -> bool:
    """Validate alias input to prevent injection attacks.

    Args:
        alias: The alias string to validate

    Returns:
        True if valid, False otherwise
    """
    if not alias or not isinstance(alias, str):
        return False

    alias = alias.strip()

    # Check length limits
    if len(alias) > _MAX_ALIAS_LENGTH:
        return False

    # Check for dangerous characters
    if any(char in alias for char in _DANGEROUS_CHARS):
        return False

    # Check allowed characters pattern
    return bool(_ALIAS_REGEX.match(alias))


def _validate_message_input(message: str) -> bool:
    """Validate message input to prevent injection attacks.

    Args:
        message: The message string to validate

    Returns:
        True if valid, False otherwise
    """
    if not isinstance(message, str):
        return False

    # Check length limits
    if len(message) > _MAX_MESSAGE_LENGTH:
        return False

    # Messages allow more characters but still check for dangerous patterns
    # Allow normal punctuation but block dangerous shell/injection chars
    dangerous_subset = {"<", ">", "`", "$", "{", "}", "\\", ";", "|"}
    if any(char in message for char in dangerous_subset):
        return False

    return True


class XmppMcpBridge(McpBridge):
    """Bridge implementation that connects MCP to XMPP."""

    def __init__(
        self,
        xmpp_adapter: XmppAdapter | None = None,
        queue_size: int = 100,
        inbox_maxlen: int = 500,
    ):
        super().__init__(queue_size)
        self.xmpp_adapter = xmpp_adapter
        self.received_messages: list[dict[str, Any]] = []
        self.sent_messages: list[dict[str, Any]] = []
        # Inbox to persist inbound messages with configurable max length
        self.inbox: deque[dict[str, Any]] = deque(maxlen=inbox_maxlen)

        # Thread safety: asyncio lock for protecting the inbox deque
        self._inbox_lock = asyncio.Lock()

        # Initialize address book with error handling
        try:
            self.address_book: Optional[AddressBook] = AddressBook()
        except AddressBookError as e:
            logger.warning(f"Address book initialization failed: {e}")
            self.address_book = None

    def set_xmpp_adapter(self, adapter: XmppAdapter):
        """Set the XMPP adapter for this bridge."""
        self.xmpp_adapter = adapter

    async def get_inbox_list(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Get a list of messages from the inbox with thread-safe access.

        Args:
            limit: Optional maximum number of messages to return (newest first)

        Returns:
            List of inbox message records (newest first)
        """
        # Thread-safe read operation
        async with self._inbox_lock:
            messages = list(reversed(self.inbox))

        if limit is not None and limit > 0:
            messages = messages[:limit]

        return messages

    async def get_inbox_message(self, message_uuid: str) -> Optional[dict[str, Any]]:
        """Fetch a specific message from the inbox by UUID with thread-safe access.

        Args:
            message_uuid: UUID of the message to fetch

        Returns:
            Message record if found, None otherwise
        """
        # Thread-safe read operation
        async with self._inbox_lock:
            for message in self.inbox:
                if message.get("uuid") == message_uuid:
                    return message
        return None

    async def get_inbox_stats(self) -> dict[str, Any]:
        """Get statistics about the inbox with thread-safe access.

        Returns:
            Dictionary with inbox statistics
        """
        # Thread-safe read operation
        async with self._inbox_lock:
            total_messages = len(self.inbox)
            max_capacity = self.inbox.maxlen

        return {
            "total_messages": total_messages,
            "max_capacity": max_capacity,
            "capacity_used_percent": (total_messages / max_capacity * 100)
            if max_capacity
            else 0,
        }

    async def list_inbox(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """List inbox messages (alias for get_inbox_list for bridge interface).

        Args:
            limit: Optional maximum number of messages to return (newest first)

        Returns:
            List of inbox message records (newest first)
        """
        return await self.get_inbox_list(limit)

    async def get_message(self, message_id: str) -> Optional[dict[str, Any]]:
        """Get a specific message by ID (alias for get_inbox_message for bridge interface).

        Args:
            message_id: UUID of the message to fetch

        Returns:
            Message record if found, None otherwise
        """
        return await self.get_inbox_message(message_id)

    async def clear_inbox(self) -> int:
        """Clear all messages from the inbox with thread-safe locking.

        Returns:
            Number of messages that were cleared
        """
        # Thread-safe clear operation
        async with self._inbox_lock:
            cleared_count = len(self.inbox)
            self.inbox.clear()

        logger.info(f"Cleared {cleared_count} messages from inbox")
        return cleared_count

    async def save_alias(self, alias: str, jid: str) -> bool:
        """Store an alias->JID mapping in the address book.

        Args:
            alias: The alias/nickname for the contact
            jid: The XMPP JID of the contact

        Returns:
            True if saved successfully, False otherwise

        Raises:
            ValueError: If alias or JID are invalid
        """
        if self.address_book is None:
            logger.warning("Address book not available")
            return False

        try:
            changed = await self.address_book.save_alias(alias, jid)
            if changed:
                # Auto-save after changes
                self.address_book.save()
            return changed
        except ValueError as e:
            logger.error(f"Failed to save alias '{alias}': {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error saving alias '{alias}': {e}")
            return False

    async def query(self, term: str) -> list[tuple[str, str, int]]:
        """Search address book using fuzzy matching.

        Args:
            term: Search term to match against aliases and JIDs

        Returns:
            List of tuples (alias, jid, score) sorted by relevance score (highest first)
        """
        if self.address_book is None:
            logger.warning("Address book not available")
            return []

        try:
            return await self.address_book.query(term)
        except Exception as e:
            logger.error(f"Error querying address book with term '{term}': {e}")
            return []

    async def sync_roster(
        self, entries: list[tuple[str, str | None]]
    ) -> dict[str, Any]:
        """Synchronize roster entries with the address book.

        Args:
            entries: List of tuples (jid, display_name) from XMPP roster

        Returns:
            Dictionary with sync statistics: {"added": int, "skipped": int, "errors": int}
        """
        if self.address_book is None:
            logger.warning("Address book not available for roster sync")
            return {"added": 0, "skipped": 0, "errors": 0}

        stats = {"added": 0, "skipped": 0, "errors": 0}
        logger.info(f"Starting roster sync with {len(entries)} entries")

        for jid, display_name in entries:
            try:
                # Validate JID
                if not _validate_jid_input(jid):
                    logger.warning(f"Invalid JID format, skipping: {jid}")
                    stats["errors"] += 1
                    continue

                # Generate alias from display name or JID localpart
                if display_name and display_name.strip():
                    # Use display name, slugified for safety
                    alias = slugify(display_name.strip())
                    if not alias:  # fallback if slugify produces empty string
                        alias = self._sanitize_alias_from_jid(jid)
                else:
                    # Use JID localpart (part before @) as alias, sanitized
                    alias = self._sanitize_alias_from_jid(jid)

                # Validate generated alias
                if not _validate_alias_input(alias):
                    logger.warning(
                        f"Generated invalid alias '{alias}' for JID {jid}, skipping"
                    )
                    stats["errors"] += 1
                    continue

                # Check if alias or JID already exists
                existing_jid = self.address_book.get_exact(alias)
                if existing_jid:
                    if existing_jid == jid:
                        logger.info(f"Roster entry already exists: {alias} - {jid}")
                        stats["skipped"] += 1
                        continue
                    else:
                        # Alias exists but points to different JID
                        # Check if this might be an auto-generated alias we can overwrite
                        # or if it's a manual entry we should preserve
                        potential_auto_alias = existing_jid.split("@")[0].lower()
                        if alias == potential_auto_alias:
                            # This looks like it might be an auto-generated alias, safe to update
                            logger.info(
                                f"Updating auto-generated alias '{alias}': {existing_jid} -> {jid}"
                            )
                        else:
                            # This looks like a manual alias, don't overwrite
                            # Generate alternative alias by appending domain
                            domain_part = jid.split("@")[1].split(".")[
                                0
                            ]  # first part of domain
                            alternative_alias = f"{alias}-{domain_part}"

                            # Check if alternative alias is available
                            if self.address_book.get_exact(alternative_alias):
                                logger.warning(
                                    f"Cannot create alias for {jid}: both '{alias}' and '{alternative_alias}' exist"
                                )
                                stats["skipped"] += 1
                                continue

                            alias = alternative_alias
                            logger.info(
                                f"Using alternative alias '{alias}' for {jid} to avoid conflict"
                            )

                # Check if JID already exists with a different alias
                existing_aliases = [
                    a for a, j in self.address_book.list_all().items() if j == jid
                ]
                if existing_aliases:
                    logger.info(
                        f"JID {jid} already exists with alias(es): {existing_aliases}"
                    )
                    stats["skipped"] += 1
                    continue

                # Add the new entry
                try:
                    changed = await self.address_book.save_alias(alias, jid)
                    if changed:
                        logger.info(f"Added roster entry: {alias} - {jid}")
                        if display_name:
                            logger.info(f"  (from display name: '{display_name}')")
                        stats["added"] += 1
                        # Auto-save after changes
                        self.address_book.save()
                    else:
                        stats["skipped"] += 1
                except ValueError as e:
                    logger.error(
                        f"Failed to save roster entry '{alias}' -> '{jid}': {e}"
                    )
                    stats["errors"] += 1

            except Exception as e:
                logger.error(f"Error processing roster entry {jid}: {e}")
                stats["errors"] += 1

        logger.info(
            f"Roster sync completed: {stats['added']} added, {stats['skipped']} skipped, {stats['errors']} errors"
        )
        return stats

    def _sanitize_alias_from_jid(self, jid: str) -> str:
        """Generate a valid alias from a JID localpart, handling special cases like phone numbers.

        Args:
            jid: The full JID

        Returns:
            A sanitized alias that passes validation
        """
        # Get the localpart (part before @)
        localpart = jid.split("@")[0].lower()

        # Handle phone numbers (remove + prefix and any special chars)
        if localpart.startswith("+"):
            # Phone number: strip + and keep only digits
            sanitized = re.sub(r"[^0-9]", "", localpart)
            # Prepend 'phone' to make it clear and valid
            if sanitized:
                return f"phone{sanitized}"

        # For other JIDs, remove any invalid characters and replace with dashes
        sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", localpart)

        # Remove leading/trailing dashes and collapse multiple dashes
        sanitized = re.sub(r"^-+|-+$", "", sanitized)  # Remove leading/trailing
        sanitized = re.sub(r"-+", "-", sanitized)  # Collapse multiple dashes

        # Ensure we have something valid
        if not sanitized or not sanitized.replace("-", "").replace("_", "").replace(
            ".", ""
        ):
            # Fallback: use 'contact' plus secure hash of original JID
            import hashlib

            hash_suffix = hashlib.sha256(jid.encode()).hexdigest()[:8]
            sanitized = f"contact-{hash_suffix}"
            sanitized = f"contact-{hash_suffix}"

        return sanitized

    async def sync_roster_incremental(
        self, added: list[tuple[str, str | None]], removed: list[str]
    ) -> dict[str, Any]:
        """Handle incremental roster updates.

        Args:
            added: List of tuples (jid, display_name) for new roster entries
            removed: List of JIDs that were removed from the roster

        Returns:
            Dictionary with sync statistics: {"added": int, "removed": int, "errors": int}
        """
        if self.address_book is None:
            logger.warning("Address book not available for incremental roster sync")
            return {"added": 0, "removed": 0, "errors": 0}

        stats = {"added": 0, "removed": 0, "errors": 0}
        logger.info(
            f"Starting incremental roster sync: {len(added)} added, {len(removed)} removed"
        )

        # Handle added entries
        if added:
            add_stats = await self.sync_roster(added)
            stats["added"] = add_stats["added"]
            stats["errors"] += add_stats["errors"]

        # Handle removed entries
        for jid in removed:
            try:
                # Find aliases that point to this JID
                aliases_to_remove = [
                    alias
                    for alias, stored_jid in self.address_book.list_all().items()
                    if stored_jid == jid
                ]

                for alias in aliases_to_remove:
                    try:
                        success = self.address_book.remove_alias(alias)
                        if success:
                            logger.info(f"Removed roster entry: {alias} -> {jid}")
                            stats["removed"] += 1
                    except Exception as e:
                        logger.error(f"Failed to remove alias '{alias}': {e}")
                        stats["errors"] += 1

                # Save changes if any removals occurred
                if aliases_to_remove:
                    self.address_book.save()

            except Exception as e:
                logger.error(f"Error processing removed roster entry {jid}: {e}")
                stats["errors"] += 1

        logger.info(
            f"Incremental roster sync completed: {stats['added']} added, {stats['removed']} removed, {stats['errors']} errors"
        )
        return stats

    async def _start_additional_tasks(self) -> None:
        """Load address book on startup."""
        if self.address_book:
            logger.info("Loading address book from storage...")
            success = self.address_book.load()
            if success:
                logger.info(
                    f"Address book loaded with {len(self.address_book)} contacts"
                )
            else:
                logger.warning("Failed to load address book, starting with empty book")

    async def _stop_additional_cleanup(self) -> None:
        """Save address book on shutdown."""
        if self.address_book:
            logger.info("Saving address book to storage...")
            success = self.address_book.save()
            if success:
                logger.info(
                    f"Address book saved with {len(self.address_book)} contacts"
                )
            else:
                logger.error("Failed to save address book!")

    async def _process_xmpp_to_mcp(self) -> None:
        """Process messages from XMPP to MCP queue."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.xmpp_to_mcp, timeout=1.0)
                if message:
                    self.received_messages.append(message)
                    logger.info(f"Received XMPP message: {message}")

                    # If this is a received_message event, append concise record to inbox
                    if message.get("type") == "received_message":
                        from_jid = message.get("from_jid")
                        body = message.get("body")

                        # Validate input to prevent injection
                        if (
                            from_jid
                            and _validate_jid_input(from_jid)
                            and body
                            and _validate_message_input(body)
                        ):
                            inbox_record = {
                                "uuid": str(uuid.uuid4()),
                                "from_jid": from_jid,
                                "body": body,
                                "ts": message.get("timestamp"),
                            }
                            # Thread-safe inbox append operation
                            async with self._inbox_lock:
                                self.inbox.append(inbox_record)
                            # Lower log level to INFO for inbox messages
                            logger.info(
                                f"Added message to inbox: {inbox_record['uuid']} from {inbox_record['from_jid']}"
                            )
                        else:
                            logger.warning(
                                f"Skipped invalid message from {from_jid}: validation failed"
                            )
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

    def __init__(self, xmpp_jid: str | None = None, xmpp_password: str | None = None):
        super().__init__()
        self.xmpp_jid = xmpp_jid
        self.xmpp_password = xmpp_password
        self.bridge: XmppMcpBridge | None = None
        self.xmpp_adapter: XmppAdapter | None = None
        self._last_processed_message_count = 0
        self._notification_task: asyncio.Task | None = None

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification to stdout."""
        notification = JsonRpcMessage(method=method, params=params)
        notification_json = notification.to_json()
        # Reduced log level for notifications to INFO
        logger.info(f"Sending notification: {notification_json}")
        # Send notification via stdout for MCP protocol
        sys.stdout.write(f"{notification_json}\n")
        sys.stdout.flush()

    async def _watch_for_new_messages(self) -> None:
        """Background task that watches for new XMPP messages and sends notifications."""
        logger.info("Starting message notification watcher")
        while True:
            try:
                await asyncio.sleep(0.5)  # Check every 500ms

                if not self.bridge:
                    continue

                # Check if we have new messages
                current_count = len(self.bridge.received_messages)
                if current_count > self._last_processed_message_count:
                    # Get the new messages
                    new_messages = self.bridge.received_messages[
                        self._last_processed_message_count :
                    ]

                    for message in new_messages:
                        # Only notify for received_message events
                        if message.get("type") == "received_message":
                            # Create minimal payload for notification
                            payload = {
                                "from": message.get("from_jid"),
                                "body": message.get("body", "")[
                                    :100
                                ],  # Truncate to 100 chars
                                "timestamp": message.get("timestamp"),
                            }

                            # Send the notification
                            self._send_notification("inbox/new", payload)
                            logger.info(
                                f"Sent inbox/new notification for message from {payload['from']}"
                            )

                    self._last_processed_message_count = current_count

            except asyncio.CancelledError:
                logger.info("Message notification watcher cancelled")
                break
            except Exception as e:
                logger.error(f"Error in message notification watcher: {e}")
                await asyncio.sleep(1)  # Wait before retrying

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

        # Start the notification watcher task
        if self.bridge:
            self._notification_task = asyncio.create_task(
                self._watch_for_new_messages(), name="message_notification_watcher"
            )
            logger.info("Started message notification watcher")

        # Start the stdio MCP server
        await super().start()

    async def stop(self) -> None:
        """Stop the server and clean up resources."""
        logger.info("Stopping XMPP-MCP server...")

        # Cancel notification task
        if self._notification_task and not self._notification_task.done():
            logger.info("Cancelling message notification watcher")
            self._notification_task.cancel()
            try:
                await self._notification_task
            except asyncio.CancelledError:
                pass

        # Stop XMPP bridge
        if self.bridge:
            await self.bridge.stop()

        # Disconnect XMPP adapter
        if self.xmpp_adapter:
            await self.xmpp_adapter.disconnect()

        logger.info("XMPP-MCP server stopped")

    async def _tool_send_message(
        self, message: JsonRpcMessage, arguments: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle send_message tool call with real XMPP integration and alias resolution."""
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
            if self.bridge and self.bridge.address_book:
                try:
                    # First try exact match
                    exact_jid = self.bridge.address_book.get_exact(recipient)
                    if exact_jid:
                        resolved_recipient = exact_jid
                        logger.info(
                            f"Resolved alias '{recipient}' to exact JID '{exact_jid}'"
                        )
                    else:
                        # Try fuzzy search
                        matches = await self.bridge.query(recipient)
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
                                [
                                    f"  {alias} -> {jid} (score: {score})"
                                    for alias, jid, score in matches
                                ]
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
                            alias, jid, score = matches[0]
                            resolved_recipient = jid
                            logger.info(
                                f"Resolved alias '{recipient}' to JID '{jid}' via fuzzy match (score: {score})"
                            )
                except Exception as e:
                    logger.error(f"Error resolving alias '{recipient}': {e}")
                    return JsonRpcMessage(
                        id=message.id,
                        error={
                            "code": -32603,
                            "message": f"Failed to resolve alias '{recipient}': {e!s}",
                        },
                    )
            else:
                return JsonRpcMessage(
                    id=message.id,
                    error={
                        "code": -32603,
                        "message": f"Cannot resolve alias '{recipient}': address book not available",
                    },
                )

        # Try to send via XMPP if available
        if self.bridge and self.xmpp_adapter:
            try:
                await self.bridge.send_to_jabber(resolved_recipient, msg_text)
                logger.info(f"Sent XMPP message to {resolved_recipient}: {msg_text}")

                result_text = f"Message sent successfully via XMPP to {resolved_recipient}\nContent: {msg_text}"
                if resolved_recipient != recipient:
                    result_text = f"Message sent successfully via XMPP to {resolved_recipient} (resolved from alias '{recipient}')\nContent: {msg_text}"

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
            result_text = f"Message simulated (no XMPP connection) to {resolved_recipient}\nContent: {msg_text}"
            if resolved_recipient != recipient:
                result_text = f"Message simulated (no XMPP connection) to {resolved_recipient} (resolved from alias '{recipient}')\nContent: {msg_text}"

            logger.info(f"Simulating XMPP message to {resolved_recipient}: {msg_text}")
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

    async def _handle_inbox_list(self, message: JsonRpcMessage) -> JsonRpcMessage:
        """Handle inbox/list request using bridge."""
        if self.bridge:
            try:
                inbox_messages = await self.bridge.list_inbox()
                # Format messages for MCP response
                summary = [
                    {
                        "id": msg["uuid"],
                        "from": msg["from_jid"],
                        "preview": msg["body"][:50] if msg["body"] else "",
                        "timestamp": msg["ts"],
                    }
                    for msg in inbox_messages
                ]

                # Create detailed text output showing all messages
                if summary:
                    import datetime

                    text_lines = [f"Found {len(summary)} messages in inbox:"]
                    text_lines.append("=" * 60)

                    for i, msg in enumerate(summary, 1):
                        # Convert timestamp to readable format
                        if msg["timestamp"]:
                            try:
                                dt = datetime.datetime.fromtimestamp(
                                    msg["timestamp"], tz=datetime.timezone.utc
                                )
                                time_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                            except (ValueError, TypeError):
                                time_str = str(msg["timestamp"])
                        else:
                            time_str = "Unknown time"

                        preview_max_len = 50  # Max length for preview text
                        text_lines.append(f"{i}. From: {msg['from']}")
                        text_lines.append(f"   Time: {time_str}")
                        text_lines.append(
                            f"   Preview: {msg['preview']}{'...' if len(str(msg.get('preview', ''))) >= preview_max_len else ''}"
                        )
                        text_lines.append(f"   ID: {msg['id']}")
                        text_lines.append("-" * 40)

                    detailed_text = "\n".join(text_lines)
                else:
                    detailed_text = "No messages in inbox"

                return JsonRpcMessage(
                    id=message.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": detailed_text,
                            }
                        ],
                        "messages": summary,
                    },
                )
            except Exception as e:
                logger.error(f"Error getting inbox list: {e}")
                return JsonRpcMessage(
                    id=message.id,
                    error={"code": -32603, "message": f"Failed to get inbox list: {e}"},
                )
        else:
            # Fall back to parent implementation if no bridge
            return await super()._handle_inbox_list(message)

    async def _handle_inbox_get(
        self, message: JsonRpcMessage, params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle inbox/get request using bridge."""
        if self.bridge:
            try:
                message_id = params.get("messageId")
                if not message_id:
                    return JsonRpcMessage(
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": "Missing required parameter: messageId",
                        },
                    )

                inbox_message = await self.bridge.get_message(message_id)
                if inbox_message:
                    return JsonRpcMessage(
                        id=message.id,
                        result={
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Message from {inbox_message['from_jid']}: {inbox_message['body']}",
                                }
                            ],
                            "message": inbox_message,
                        },
                    )
                else:
                    return JsonRpcMessage(
                        id=message.id,
                        error={"code": -32602, "message": "Message not found"},
                    )
            except Exception as e:
                logger.error(
                    f"Error getting inbox message {params.get('messageId')}: {e}"
                )
                return JsonRpcMessage(
                    id=message.id,
                    error={
                        "code": -32603,
                        "message": f"Failed to get inbox message: {e}",
                    },
                )
        else:
            # Fall back to parent implementation if no bridge
            return await super()._handle_inbox_get(message, params)

    async def _handle_inbox_clear(self, message: JsonRpcMessage) -> JsonRpcMessage:
        """Handle inbox/clear request using bridge."""
        if self.bridge:
            try:
                # Use the bridge method to clear inbox and get count
                cleared_count = await self.bridge.clear_inbox()

                return JsonRpcMessage(
                    id=message.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": f"Cleared {cleared_count} messages from inbox",
                            }
                        ],
                        "status": f"Inbox cleared - removed {cleared_count} messages",
                    },
                )
            except Exception as e:
                logger.error(f"Error clearing inbox: {e}")
                return JsonRpcMessage(
                    id=message.id,
                    error={"code": -32603, "message": f"Failed to clear inbox: {e}"},
                )
        else:
            # Fall back to parent implementation if no bridge
            return await super()._handle_inbox_clear(message)

    async def _handle_address_book_query(
        self, message: JsonRpcMessage, params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle address_book/query request using bridge address book."""
        if self.bridge and self.bridge.address_book:
            try:
                query = params.get("query", "")
                if not query:
                    return JsonRpcMessage(
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": "Missing required parameter: query",
                        },
                    )

                results = await self.bridge.query(query)

                # Format results as list of dictionaries for better JSON compatibility
                matches = [
                    {"alias": alias, "jid": jid, "score": score}
                    for alias, jid, score in results
                ]

                return JsonRpcMessage(
                    id=message.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": f"Found {len(matches)} matches for query '{query}'",
                            }
                        ],
                        "matches": matches,
                    },
                )
            except Exception as e:
                logger.error(f"Error querying address book: {e}")
                return JsonRpcMessage(
                    id=message.id,
                    error={
                        "code": -32603,
                        "message": f"Failed to query address book: {e}",
                    },
                )
        else:
            # Fall back to parent implementation if no bridge
            return await super()._handle_address_book_query(message, params)

    async def _handle_address_book_save(
        self, message: JsonRpcMessage, params: dict[str, Any]
    ) -> JsonRpcMessage:
        """Handle address_book/save request using bridge address book."""
        if self.bridge and self.bridge.address_book:
            try:
                alias = params.get("alias")
                jid = params.get("jid")

                if not alias:
                    return JsonRpcMessage(
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": "Missing required parameter: alias",
                        },
                    )

                if not jid:
                    return JsonRpcMessage(
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": "Missing required parameter: jid",
                        },
                    )

                try:
                    changed = await self.bridge.save_alias(alias, jid)
                    status = "updated" if changed else "no change"

                    return JsonRpcMessage(
                        id=message.id,
                        result={
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Address book entry {status}: {alias} -> {jid}",
                                }
                            ],
                            "status": f"Entry {status}",
                            "alias": alias,
                            "jid": jid,
                        },
                    )
                except ValueError as e:
                    return JsonRpcMessage(
                        id=message.id, error={"code": -32602, "message": str(e)}
                    )

            except Exception as e:
                logger.error(f"Error saving to address book: {e}")
                return JsonRpcMessage(
                    id=message.id,
                    error={
                        "code": -32603,
                        "message": f"Failed to save address book entry: {e}",
                    },
                )
        else:
            # Fall back to parent implementation if no bridge
            return await super()._handle_address_book_save(message, params)


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
