#!/usr/bin/env python3
"""
Demonstration of inbox functionality in XmppMcpBridge.

This script shows how the inbox persists inbound messages and provides
async methods to access them without blocking.
"""

import asyncio
import json
import logging

from jabber_mcp.xmpp_mcp_server import XmppMcpBridge

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def demo_inbox_functionality():
    """Demonstrate the inbox functionality."""

    # Create bridge with small inbox for demonstration
    bridge = XmppMcpBridge(queue_size=10, inbox_maxlen=3)

    logger.info("Starting XmppMcpBridge...")
    await bridge.start()

    try:
        logger.info("=== Inbox Demonstration ===")

        # Simulate receiving some messages
        logger.info("\n1. Simulating incoming XMPP messages...")
        test_messages = [
            ("alice@example.com", "Hello everyone!"),
            ("bob@example.com", "How are you doing?"),
            ("charlie@example.com", "Anyone up for coffee?"),
            (
                "diana@example.com",
                "The meeting is at 3pm",
            ),  # This will evict the first message
            (
                "eve@example.com",
                "Don't forget about the deadline",
            ),  # This will evict the second message
        ]

        for jid, body in test_messages:
            await bridge.handle_incoming_xmpp_message(jid, body, "chat")
            logger.info(f"Received message from {jid}: {body}")

        # Give the processor time to handle all messages
        await asyncio.sleep(0.2)

        # Show inbox stats
        logger.info("\n2. Getting inbox statistics...")
        stats = await bridge.get_inbox_stats()
        logger.info(f"Inbox stats: {json.dumps(stats, indent=2)}")

        # Get all messages from inbox (newest first)
        logger.info("\n3. Getting all messages from inbox...")
        all_messages = await bridge.get_inbox_list()
        logger.info(f"Total messages in inbox: {len(all_messages)}")
        for i, msg in enumerate(all_messages):
            logger.info(f"Message {i + 1}: {msg['from_jid']} - {msg['body'][:30]}...")

        # Get limited messages
        logger.info("\n4. Getting last 2 messages...")
        recent_messages = await bridge.get_inbox_list(limit=2)
        for i, msg in enumerate(recent_messages):
            logger.info(f"Recent {i + 1}: {msg['from_jid']} - {msg['body']}")

        # Fetch a specific message by UUID
        logger.info("\n5. Fetching message by UUID...")
        if all_messages:
            target_uuid = all_messages[0]["uuid"]
            specific_message = await bridge.get_inbox_message(target_uuid)
            if specific_message:
                logger.info(
                    f"Found message: {specific_message['from_jid']} - {specific_message['body']}"
                )
            else:
                logger.error("Message not found!")

        # Test concurrent access
        logger.info("\n6. Testing concurrent inbox access...")

        async def concurrent_reader(reader_id):
            messages = await bridge.get_inbox_list(limit=1)
            stats = await bridge.get_inbox_stats()
            logger.info(
                f"Reader {reader_id}: Got {len(messages)} messages, {stats['total_messages']} total"
            )
            return len(messages)

        # Run multiple concurrent readers
        tasks = [concurrent_reader(i) for i in range(3)]
        results = await asyncio.gather(*tasks)
        logger.info(f"All readers completed successfully: {results}")

        # Demonstrate that non-message events are ignored
        logger.info("\n7. Testing that presence updates are not added to inbox...")
        initial_count = len(bridge.inbox)
        await bridge.handle_incoming_xmpp_presence(
            "test@example.com", "available", "Online"
        )
        await asyncio.sleep(0.1)
        final_count = len(bridge.inbox)
        logger.info(
            f"Inbox count before presence: {initial_count}, after: {final_count}"
        )

        logger.info("\n=== Demo Complete ===")

    finally:
        logger.info("Stopping bridge...")
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(demo_inbox_functionality())
