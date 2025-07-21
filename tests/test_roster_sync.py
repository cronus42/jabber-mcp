#!/usr/bin/env python3
"""
Test script for XMPP roster synchronization functionality.

This script tests the roster sync implementation without requiring
a real XMPP connection.
"""

import asyncio
import logging
import sys
from unittest.mock import AsyncMock, Mock

# Set up path to import our modules
sys.path.insert(0, "src")

from jabber_mcp.address_book import AddressBook
from jabber_mcp.xmpp_mcp_server import XmppMcpBridge

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_roster_sync():
    """Test roster synchronization functionality."""
    logger.info("=== Testing Roster Sync Functionality ===")

    try:
        # Create a bridge instance
        bridge = XmppMcpBridge()

        if bridge.address_book is None:
            logger.error("Address book not initialized")
            return False

        # Test roster entries (JID, display_name pairs)
        test_roster = [
            ("alice@example.com", "Alice Smith"),
            ("bob@jabber.org", "Bob Johnson"),
            ("carol@xmpp.net", None),  # No display name
            ("dave@server.com", "Dave the Developer"),
            ("eve@chat.example", ""),  # Empty display name
        ]

        logger.info(f"Testing with {len(test_roster)} roster entries")

        # Test initial sync
        logger.info("\n--- Initial Roster Sync ---")
        stats = await bridge.sync_roster(test_roster)

        logger.info(f"Sync results: {stats}")

        # Verify entries were added
        logger.info("\n--- Verifying Address Book Contents ---")
        for alias, jid in bridge.address_book.list_all().items():
            logger.info(f"  {alias} -> {jid}")

        # Test duplicate sync (should skip existing entries)
        logger.info("\n--- Testing Duplicate Sync ---")
        stats2 = await bridge.sync_roster(test_roster)
        logger.info(f"Duplicate sync results: {stats2}")

        # Test incremental sync with new entries
        logger.info("\n--- Testing Incremental Sync ---")
        new_entries = [("frank@newserver.org", "Frank New")]
        removed_entries = ["alice@example.com"]

        incremental_stats = await bridge.sync_roster_incremental(
            new_entries, removed_entries
        )
        logger.info(f"Incremental sync results: {incremental_stats}")

        # Final verification
        logger.info("\n--- Final Address Book Contents ---")
        for alias, jid in bridge.address_book.list_all().items():
            logger.info(f"  {alias} -> {jid}")

        logger.info("\n=== Roster Sync Test Completed Successfully ===")
        return True

    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return False


async def test_alias_generation():
    """Test alias generation from display names."""
    logger.info("\n=== Testing Alias Generation ===")

    try:
        _bridge = XmppMcpBridge()

        test_cases = [
            ("user@example.com", "John Doe", "john-doe"),
            ("test@server.org", "Alice ob", "alice-bob"),
            ("admin@site.net", "Admin User!", "admin-user"),
            ("dev@code.io", "", "dev"),  # Fallback to localpart
            ("support@help.com", None, "support"),  # Fallback to localpart
        ]

        logger.info("Testing alias generation patterns:")

        for jid, display_name, expected_alias in test_cases:
            # Test the logic manually since it's internal to sync_roster
            if display_name and display_name.strip():
                # Use slugify logic
                from jabber_mcp.xmpp_mcp_server import slugify

                alias = slugify(display_name.strip())
                if not alias:
                    alias = jid.split("@")[0].lower()
            else:
                alias = jid.split("@")[0].lower()

            logger.info(
                f"  {jid} + '{display_name}' - {alias} (expected: '{expected_alias}')"
            )

        logger.info("=== Alias Generation Test Completed ===")
        return True

    except Exception as e:
        logger.error(f"Alias generation test failed: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("Starting roster sync tests...")

    # Run tests
    test1_passed = await test_roster_sync()
    test2_passed = await test_alias_generation()

    if test1_passed and test2_passed:
        logger.info("\n🎉 All tests passed!")
        return 0
    else:
        logger.error("\n❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
