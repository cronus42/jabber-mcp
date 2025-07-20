"""Entry point for jabber-mcp package when run as python -m jabber_mcp."""

import asyncio
import logging
import sys

from jabber_mcp.mcp_stdio_server import main

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        error_msg = f"Error: {e}"
        logger.error(error_msg)
        sys.exit(1)
