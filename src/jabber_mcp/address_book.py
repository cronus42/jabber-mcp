"""Address Book implementation with fuzzy search functionality for XMPP-MCP Bridge.

This module provides an AddressBook class that stores alias->JID mappings with
fuzzy search capabilities. It enforces the no-PII rule by only storing aliases
and JIDs, nothing more.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from fuzzywuzzy import fuzz
    from fuzzywuzzy import process as fuzzy_process

    FUZZYWUZZY_AVAILABLE = True
except ImportError:
    FUZZYWUZZY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Configuration constants
_DEFAULT_CONFIG_DIR = Path.home() / ".jabber_mcp"
_DEFAULT_ADDRESS_BOOK_FILE = _DEFAULT_CONFIG_DIR / "address_book.json"
_DEFAULT_FUZZY_THRESHOLD = 60  # Minimum fuzzy match score
_DEFAULT_MAX_RESULTS = 10  # Maximum number of search results
_MAX_ALIAS_LENGTH = 100  # Maximum allowed alias length

# JID validation regex (basic XMPP JID format)
_JID_REGEX = re.compile(r"^[^@/]+@[^@/]+(?:/.*)?$")


class AddressBookError(Exception):
    """Base exception for AddressBook errors."""

    pass


class AddressBook:
    """Address book for storing alias->JID mappings with fuzzy search.

    This class provides functionality to store and search contact aliases with
    their corresponding JIDs. It enforces the no-PII rule by only storing
    aliases and JIDs.

    Features:
    - Fuzzy search using fuzzywuzzy library
    - Persistent storage to JSON file
    - JID validation
    - Case-insensitive search
    - Ranked search results
    """

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        fuzzy_threshold: int = _DEFAULT_FUZZY_THRESHOLD,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ):
        """Initialize the address book.

        Args:
            storage_path: Path to the JSON storage file
            fuzzy_threshold: Minimum fuzzy match score (0-100)
            max_results: Maximum number of search results to return

        Raises:
            AddressBookError: If fuzzy search is not available
        """
        if not FUZZYWUZZY_AVAILABLE:
            raise AddressBookError(
                "fuzzywuzzy library is required but not available. "
                "Install with: pip install fuzzywuzzy[speedup]"
            )

        self.storage_path = storage_path or _DEFAULT_ADDRESS_BOOK_FILE
        self.fuzzy_threshold = max(0, min(100, fuzzy_threshold))
        self.max_results = max(1, max_results)

        # Internal storage: alias -> jid mapping
        self._contacts: Dict[str, str] = {}

        # Thread safety: asyncio lock for protecting the contacts dict
        self._lock = asyncio.Lock()

        # Ensure storage directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"AddressBook initialized with storage at {self.storage_path}")

    def _validate_jid(self, jid: str) -> bool:
        """Validate JID format.

        Args:
            jid: The JID to validate

        Returns:
            True if valid, False otherwise
        """
        if not jid or not isinstance(jid, str):
            return False
        return bool(_JID_REGEX.match(jid.strip()))

    def _validate_alias(self, alias: str) -> bool:
        """Validate alias format.

        Args:
            alias: The alias to validate

        Returns:
            True if valid, False otherwise
        """
        if not alias or not isinstance(alias, str):
            return False
        # Aliases should be non-empty strings with reasonable length
        alias = alias.strip()
        return len(alias) > 0 and len(alias) <= _MAX_ALIAS_LENGTH

    async def save_alias(self, alias: str, jid: str) -> bool:
        """Store an alias->JID mapping with thread-safe locking.

        Args:
            alias: The alias/nickname for the contact
            jid: The XMPP JID of the contact

        Returns:
            True if saved successfully, False otherwise

        Raises:
            ValueError: If alias or JID are invalid
        """
        if not self._validate_alias(alias):
            msg = f"Invalid alias: '{alias}'. Must be non-empty string."
            raise ValueError(msg)

        if not self._validate_jid(jid):
            msg = f"Invalid JID: '{jid}'. Must be valid XMPP JID format."
            raise ValueError(msg)

        # Normalize inputs
        alias = alias.strip()
        jid = jid.strip().lower()  # JIDs are case-insensitive

        # Thread-safe store operation
        async with self._lock:
            old_jid = self._contacts.get(alias)
            self._contacts[alias] = jid

        if old_jid != jid:
            logger.info(
                f"Saved alias '{alias}' -> '{jid}'"
                + (f" (updated from '{old_jid}')" if old_jid else "")
            )
            return True
        else:
            # Lowered log level from DEBUG to INFO for less verbosity
            logger.info(f"Alias '{alias}' already maps to '{jid}', no change")
            return False

    async def query(self, term: str) -> List[Tuple[str, str, int]]:
        """Search for contacts using fuzzy matching with thread-safe access.

        Args:
            term: Search term to match against aliases and JIDs

        Returns:
            List of tuples (alias, jid, score) sorted by relevance score (highest first)
        """
        if not term or not isinstance(term, str):
            return []

        term = term.strip().lower()
        if not term:
            return []

        # Thread-safe read operation
        async with self._lock:
            contacts_copy = self._contacts.copy()

        results = []

        for alias, jid in contacts_copy.items():
            # Calculate fuzzy scores for both alias and JID
            alias_score = fuzz.partial_ratio(term, alias.lower())
            jid_score = fuzz.partial_ratio(term, jid.lower())

            # Use the higher of the two scores
            max_score = max(alias_score, jid_score)

            # Include result if it meets threshold
            if max_score >= self.fuzzy_threshold:
                results.append((alias, jid, max_score))

        # Sort by score (highest first) and limit results
        results.sort(key=lambda x: x[2], reverse=True)
        return results[: self.max_results]

    def get_exact(self, alias: str) -> Optional[str]:
        """Get JID for exact alias match.

        Args:
            alias: The exact alias to look up

        Returns:
            JID if found, None otherwise
        """
        return self._contacts.get(alias.strip()) if alias else None

    def remove_alias(self, alias: str) -> bool:
        """Remove an alias from the address book.

        Args:
            alias: The alias to remove

        Returns:
            True if removed, False if not found
        """
        alias = alias.strip() if alias else ""
        if alias in self._contacts:
            jid = self._contacts.pop(alias)
            logger.info(f"Removed alias '{alias}' (was '{jid}')")
            return True
        return False

    def list_all(self) -> Dict[str, str]:
        """Get all alias->JID mappings.

        Returns:
            Dictionary of all contacts (copy, safe to modify)
        """
        return self._contacts.copy()

    def count(self) -> int:
        """Get number of stored contacts.

        Returns:
            Number of contacts in the address book
        """
        return len(self._contacts)

    def clear(self) -> int:
        """Clear all contacts from the address book.

        Returns:
            Number of contacts that were cleared
        """
        count = len(self._contacts)
        self._contacts.clear()
        logger.info(f"Cleared {count} contacts from address book")
        return count

    def load(self) -> bool:
        """Load address book from storage file.

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            if not self.storage_path.exists():
                logger.info(
                    f"Address book file {self.storage_path} doesn't exist, starting empty"
                )
                return True

            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)

            # Validate and load data
            if not isinstance(data, dict):
                logger.error("Address book file contains invalid data format")
                return False

            loaded_count = 0
            for alias, jid in data.items():
                if self._validate_alias(alias) and self._validate_jid(jid):
                    self._contacts[alias] = jid.strip().lower()
                    loaded_count += 1
                else:
                    logger.warning(
                        f"Skipping invalid entry: alias='{alias}', jid='{jid}'"
                    )

            logger.info(f"Loaded {loaded_count} contacts from {self.storage_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load address book from {self.storage_path}: {e}")
            return False

    def save(self) -> bool:
        """Save address book to storage file.

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Ensure directory exists
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            # Write atomically using temporary file
            temp_path = self.storage_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    self._contacts, f, indent=2, sort_keys=True, ensure_ascii=False
                )

            # Atomic rename
            temp_path.replace(self.storage_path)

            logger.debug(f"Saved {len(self._contacts)} contacts to {self.storage_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save address book to {self.storage_path}: {e}")
            return False

    def __len__(self) -> int:
        """Return number of contacts."""
        return len(self._contacts)

    def __contains__(self, alias: str) -> bool:
        """Check if alias exists in address book."""
        return alias.strip() in self._contacts if alias else False

    def __repr__(self) -> str:
        """String representation of address book."""
        return f"AddressBook(contacts={len(self._contacts)}, path={self.storage_path})"
