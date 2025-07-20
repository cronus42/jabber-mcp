"""Test configuration using environment variables to avoid committing credentials."""

import os
from typing import Optional


def get_test_jid() -> Optional[str]:
    """Get test JID from environment variable.

    Returns:
        Test JID if set, None otherwise
    """
    return os.getenv("TEST_XMPP_JID")


def get_test_password() -> Optional[str]:
    """Get test password from environment variable.

    Returns:
        Test password if set, None otherwise
    """
    return os.getenv("TEST_XMPP_PASSWORD")


def get_test_server() -> str:
    """Get test server from environment variable.

    Returns:
        Test server hostname, defaults to localhost
    """
    return os.getenv("TEST_XMPP_SERVER", "localhost")


def get_test_port() -> int:
    """Get test server port from environment variable.

    Returns:
        Test server port, defaults to 5222
    """
    return int(os.getenv("TEST_XMPP_PORT", "5222"))


def has_xmpp_credentials() -> bool:
    """Check if XMPP credentials are available for testing.

    Returns:
        True if both JID and password are set
    """
    return get_test_jid() is not None and get_test_password() is not None


def get_test_recipient_jid() -> Optional[str]:
    """Get test recipient JID from environment variable.

    Returns:
        Test recipient JID if set, None otherwise
    """
    return os.getenv("TEST_RECIPIENT_JID")


# Configuration constants for testing
DEFAULT_QUEUE_SIZE = 10
DEFAULT_INBOX_MAXLEN = 100
DEFAULT_FUZZY_THRESHOLD = 60
DEFAULT_MAX_RESULTS = 10


# Security validation for test environment
def validate_test_environment() -> bool:
    """Validate that test environment is properly configured.

    Returns:
        True if test environment is valid
    """
    # Check that no credentials are hardcoded in environment files
    sensitive_files = [".env", ".env.local", ".env.test"]
    for file in sensitive_files:
        if os.path.exists(file):
            with open(file) as f:
                content = f.read()
                if any(
                    keyword in content.lower()
                    for keyword in ["password", "secret", "token"]
                ):
                    print(f"Warning: Potential credentials found in {file}")
                    return False

    return True
