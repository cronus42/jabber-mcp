"""Converters for XMPP ↔ MCP message conversion.

This module provides type-safe dataclasses and conversion logic for
transforming MCP tool calls into XMPP stanzas and incoming XMPP
messages into MCP events.
"""

import html
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union
from xml.sax.saxutils import escape as xml_escape


@dataclass
class SendXmppMessage:
    """Payload for outgoing XMPP messages.

    Represents an MCP SEND command that needs to be converted
    to an XMPP <message> stanza.
    """

    jid: str
    body: str
    message_type: str = "chat"

    def to_stanza(self) -> str:
        """Convert to XMPP <message> stanza.

        Returns:
            XML string representation of the message stanza.
        """
        escaped_jid = xml_escape(self.jid)
        escaped_body = xml_escape(self.body)
        escaped_type = xml_escape(self.message_type)

        return (
            f'<message to="{escaped_jid}" type="{escaped_type}">'
            f"<body>{escaped_body}</body>"
            f"</message>"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary suitable for queue messaging.
        """
        return {
            "type": "send_message",
            "jid": self.jid,
            "body": self.body,
            "message_type": self.message_type,
        }


@dataclass
class ReceivedXmppMessage:
    """Payload for incoming XMPP messages.

    Represents an incoming XMPP message that needs to be converted
    to an MCP RECEIVED event.
    """

    jid: str
    body: str
    message_type: str = "chat"
    timestamp: Optional[float] = None

    @classmethod
    def from_stanza(
        cls,
        from_jid: str,
        body: str,
        message_type: str = "chat",
        timestamp: Optional[float] = None,
    ) -> "ReceivedXmppMessage":
        """Create from XMPP stanza data.

        Args:
            from_jid: The JID the message came from
            body: The message body text
            message_type: The XMPP message type
            timestamp: Optional timestamp

        Returns:
            ReceivedXmppMessage instance
        """
        # HTML unescape the body content if needed
        unescaped_body = html.unescape(body) if body else ""

        return cls(
            jid=from_jid,
            body=unescaped_body,
            message_type=message_type,
            timestamp=timestamp,
        )

    @classmethod
    def from_mcp_event(cls, data: Dict[str, Any]) -> "ReceivedXmppMessage":
        """Create from MCP event data.

        Args:
            data: MCP event dictionary

        Returns:
            ReceivedXmppMessage instance
        """
        jid = data.get("from_jid", data.get("jid", ""))
        body = data.get("body", "")
        message_type = data.get("message_type", "chat")
        timestamp = data.get("timestamp")

        # Ensure types are correct
        if not isinstance(jid, str):
            jid = str(jid) if jid is not None else ""
        if not isinstance(body, str):
            body = str(body) if body is not None else ""
        if not isinstance(message_type, str):
            message_type = "chat"
        if timestamp is not None and not isinstance(timestamp, (int, float)):
            timestamp = None

        return cls(
            jid=jid,
            body=body,
            message_type=message_type,
            timestamp=timestamp,
        )

    def to_mcp_event(self) -> Dict[str, Any]:
        """Convert to MCP RECEIVED event.

        Returns:
            Dictionary representing MCP RECEIVED event.
        """
        event: Dict[str, Any] = {
            "type": "received_message",
            "from_jid": self.jid,
            "body": self.body,
            "message_type": self.message_type,
        }

        if self.timestamp is not None:
            event["timestamp"] = self.timestamp

        return event


def convert_mcp_send_to_xmpp(mcp_data: Dict[str, Any]) -> SendXmppMessage:
    """Convert MCP SEND command to XMPP message.

    Args:
        mcp_data: MCP tool call data containing 'jid' and 'body'

    Returns:
        SendXmppMessage ready for XMPP transmission

    Raises:
        ValueError: If required fields are missing
    """
    jid = mcp_data.get("jid")
    body = mcp_data.get("body")

    if not jid:
        msg = "Missing required field: jid"
        raise ValueError(msg)
    if not isinstance(jid, str):
        msg = "Field 'jid' must be a string"
        raise ValueError(msg)
    if not body:
        msg = "Missing required field: body"
        raise ValueError(msg)
    if not isinstance(body, str):
        msg = "Field 'body' must be a string"
        raise ValueError(msg)

    message_type = mcp_data.get("message_type", "chat")
    if not isinstance(message_type, str):
        message_type = "chat"

    return SendXmppMessage(jid=jid, body=body, message_type=message_type)


def convert_xmpp_to_mcp_event(
    from_jid: str,
    body: str,
    message_type: str = "chat",
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """Convert incoming XMPP message to MCP RECEIVED event.

    Args:
        from_jid: The JID the message came from
        body: The message body text
        message_type: The XMPP message type
        timestamp: Optional timestamp

    Returns:
        Dictionary representing MCP RECEIVED event

    Raises:
        ValueError: If required fields are invalid
    """
    if not from_jid:
        msg = "Missing required field: from_jid"
        raise ValueError(msg)
    if not isinstance(from_jid, str):
        msg = "Field 'from_jid' must be a string"
        raise ValueError(msg)
    if not isinstance(body, str):
        msg = "Field 'body' must be a string"
        raise ValueError(msg)

    message = ReceivedXmppMessage.from_stanza(
        from_jid=from_jid, body=body, message_type=message_type, timestamp=timestamp
    )

    return message.to_mcp_event()
