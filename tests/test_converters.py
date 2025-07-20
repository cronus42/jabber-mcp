"""Tests for XMPP ↔ MCP message converters."""

import pytest

from jabber_mcp.converters import (
    ReceivedXmppMessage,
    SendXmppMessage,
    convert_mcp_send_to_xmpp,
    convert_xmpp_to_mcp_event,
)


class TestSendXmppMessage:
    """Test cases for SendXmppMessage dataclass."""

    def test_basic_creation(self):
        """Test basic message creation."""
        msg = SendXmppMessage(jid="user@example.com", body="Hello world")
        assert msg.jid == "user@example.com"
        assert msg.body == "Hello world"
        assert msg.message_type == "chat"

    def test_custom_message_type(self):
        """Test message with custom type."""
        msg = SendXmppMessage(
            jid="user@example.com", body="Hello world", message_type="normal"
        )
        assert msg.message_type == "normal"

    def test_to_stanza(self):
        """Test XMPP stanza generation."""
        msg = SendXmppMessage(jid="user@example.com", body="Hello world")
        stanza = msg.to_stanza()

        expected = '<message to="user@example.com" type="chat"><body>Hello world</body></message>'
        assert stanza == expected

    def test_to_stanza_with_escaping(self):
        """Test XMPP stanza with XML escaping."""
        msg = SendXmppMessage(
            jid="user@example.com", body="<script>alert('xss')</script>"
        )
        stanza = msg.to_stanza()

        expected = '<message to="user@example.com" type="chat"><body>&lt;script&gt;alert(\'xss\')&lt;/script&gt;</body></message>'
        assert stanza == expected

    def test_to_dict(self):
        """Test dictionary conversion."""
        msg = SendXmppMessage(jid="user@example.com", body="Hello world")
        data = msg.to_dict()

        expected = {
            "type": "send_message",
            "jid": "user@example.com",
            "body": "Hello world",
            "message_type": "chat",
        }
        assert data == expected


class TestReceivedXmppMessage:
    """Test cases for ReceivedXmppMessage dataclass."""

    def test_basic_creation(self):
        """Test basic message creation."""
        msg = ReceivedXmppMessage(jid="sender@example.com", body="Hello back")
        assert msg.jid == "sender@example.com"
        assert msg.body == "Hello back"
        assert msg.message_type == "chat"
        assert msg.timestamp is None

    def test_from_stanza(self):
        """Test creation from XMPP stanza data."""
        msg = ReceivedXmppMessage.from_stanza(
            from_jid="sender@example.com",
            body="Hello from XMPP",
            message_type="normal",
            timestamp=1234567890.0,
        )

        assert msg.jid == "sender@example.com"
        assert msg.body == "Hello from XMPP"
        assert msg.message_type == "normal"
        assert msg.timestamp == 1234567890.0

    def test_from_stanza_with_html_unescaping(self):
        """Test HTML unescaping in message body."""
        msg = ReceivedXmppMessage.from_stanza(
            from_jid="sender@example.com",
            body="&lt;test&gt; &amp; &quot;quotes&quot;",
        )

        assert msg.body == '<test> & "quotes"'

    def test_from_mcp_event(self):
        """Test creation from MCP event data."""
        event_data = {
            "from_jid": "sender@example.com",
            "body": "Hello from MCP",
            "message_type": "groupchat",
            "timestamp": 1234567890.0,
        }

        msg = ReceivedXmppMessage.from_mcp_event(event_data)

        assert msg.jid == "sender@example.com"
        assert msg.body == "Hello from MCP"
        assert msg.message_type == "groupchat"
        assert msg.timestamp == 1234567890.0

    def test_from_mcp_event_with_jid_fallback(self):
        """Test fallback to 'jid' field if 'from_jid' not present."""
        event_data = {
            "jid": "sender@example.com",
            "body": "Hello from MCP",
        }

        msg = ReceivedXmppMessage.from_mcp_event(event_data)
        assert msg.jid == "sender@example.com"

    def test_to_mcp_event(self):
        """Test conversion to MCP RECEIVED event."""
        msg = ReceivedXmppMessage(
            jid="sender@example.com",
            body="Hello MCP",
            message_type="groupchat",
            timestamp=1234567890.0,
        )

        event = msg.to_mcp_event()

        expected = {
            "type": "received_message",
            "from_jid": "sender@example.com",
            "body": "Hello MCP",
            "message_type": "groupchat",
            "timestamp": 1234567890.0,
        }
        assert event == expected

    def test_to_mcp_event_no_timestamp(self):
        """Test MCP event without timestamp."""
        msg = ReceivedXmppMessage(jid="sender@example.com", body="Hello MCP")
        event = msg.to_mcp_event()

        expected = {
            "type": "received_message",
            "from_jid": "sender@example.com",
            "body": "Hello MCP",
            "message_type": "chat",
        }
        assert event == expected


class TestConverterFunctions:
    """Test cases for converter utility functions."""

    def test_convert_mcp_send_to_xmpp(self):
        """Test MCP SEND to XMPP conversion."""
        mcp_data = {
            "jid": "recipient@example.com",
            "body": "Test message",
            "message_type": "normal",
        }

        msg = convert_mcp_send_to_xmpp(mcp_data)

        assert isinstance(msg, SendXmppMessage)
        assert msg.jid == "recipient@example.com"
        assert msg.body == "Test message"
        assert msg.message_type == "normal"

    def test_convert_mcp_send_to_xmpp_defaults(self):
        """Test MCP SEND conversion with defaults."""
        mcp_data = {
            "jid": "recipient@example.com",
            "body": "Test message",
        }

        msg = convert_mcp_send_to_xmpp(mcp_data)
        assert msg.message_type == "chat"

    def test_convert_mcp_send_to_xmpp_missing_jid(self):
        """Test MCP SEND conversion with missing JID."""
        mcp_data = {"body": "Test message"}

        with pytest.raises(ValueError, match="Missing required field: jid"):
            convert_mcp_send_to_xmpp(mcp_data)

    def test_convert_mcp_send_to_xmpp_missing_body(self):
        """Test MCP SEND conversion with missing body."""
        mcp_data = {"jid": "recipient@example.com"}

        with pytest.raises(ValueError, match="Missing required field: body"):
            convert_mcp_send_to_xmpp(mcp_data)

    def test_convert_mcp_send_to_xmpp_invalid_types(self):
        """Test MCP SEND conversion with invalid data types."""
        # Invalid JID type
        with pytest.raises(ValueError, match="Field 'jid' must be a string"):
            convert_mcp_send_to_xmpp({"jid": 123, "body": "test"})

        # Invalid body type
        with pytest.raises(ValueError, match="Field 'body' must be a string"):
            convert_mcp_send_to_xmpp({"jid": "test@example.com", "body": 123})

    def test_convert_xmpp_to_mcp_event(self):
        """Test XMPP to MCP RECEIVED event conversion."""
        event = convert_xmpp_to_mcp_event(
            from_jid="sender@example.com",
            body="Hello MCP",
            message_type="groupchat",
            timestamp=1234567890.0,
        )

        expected = {
            "type": "received_message",
            "from_jid": "sender@example.com",
            "body": "Hello MCP",
            "message_type": "groupchat",
            "timestamp": 1234567890.0,
        }
        assert event == expected

    def test_convert_xmpp_to_mcp_event_defaults(self):
        """Test XMPP to MCP event conversion with defaults."""
        event = convert_xmpp_to_mcp_event(
            from_jid="sender@example.com", body="Hello MCP"
        )

        expected = {
            "type": "received_message",
            "from_jid": "sender@example.com",
            "body": "Hello MCP",
            "message_type": "chat",
        }
        assert event == expected

    def test_convert_xmpp_to_mcp_event_missing_jid(self):
        """Test XMPP conversion with missing from_jid."""
        with pytest.raises(ValueError, match="Missing required field: from_jid"):
            convert_xmpp_to_mcp_event(from_jid="", body="Hello")

    def test_convert_xmpp_to_mcp_event_invalid_types(self):
        """Test XMPP conversion with invalid data types."""
        # Invalid from_jid type
        with pytest.raises(ValueError, match="Field 'from_jid' must be a string"):
            convert_xmpp_to_mcp_event(from_jid=123, body="hello")

        # Invalid body type
        with pytest.raises(ValueError, match="Field 'body' must be a string"):
            convert_xmpp_to_mcp_event(from_jid="test@example.com", body=123)

    # Additional edge case tests for comprehensive coverage
    def test_from_mcp_event_type_coercion(self):
        """Test type coercion in from_mcp_event."""
        # Test non-string types that should be coerced
        event_data = {
            "from_jid": 123,  # Should be converted to string
            "body": 456,  # Should be converted to string "456"
            "message_type": 456,  # Should default to 'chat'
            "timestamp": "not_a_number",  # Should be set to None
        }

        msg = ReceivedXmppMessage.from_mcp_event(event_data)
        assert msg.jid == "123"
        assert msg.body == "456"  # 456 is converted to string "456"
        assert msg.message_type == "chat"
        assert msg.timestamp is None

    def test_from_mcp_event_with_valid_numeric_timestamp(self):
        """Test from_mcp_event with valid numeric timestamp."""
        event_data = {
            "from_jid": "sender@example.com",
            "body": "Hello",
            "timestamp": 1234567890,  # int timestamp
        }

        msg = ReceivedXmppMessage.from_mcp_event(event_data)
        assert msg.timestamp == 1234567890

    def test_convert_mcp_send_to_xmpp_empty_strings(self):
        """Test convert function with empty string edge cases."""
        # Empty JID should raise error
        with pytest.raises(ValueError, match="Missing required field: jid"):
            convert_mcp_send_to_xmpp({"jid": "", "body": "test"})

        # Empty body should raise error
        with pytest.raises(ValueError, match="Missing required field: body"):
            convert_mcp_send_to_xmpp({"jid": "test@example.com", "body": ""})

    def test_convert_mcp_send_to_xmpp_non_string_message_type(self):
        """Test that non-string message_type defaults to 'chat'."""
        mcp_data = {
            "jid": "test@example.com",
            "body": "Hello",
            "message_type": 123,  # Non-string type
        }

        msg = convert_mcp_send_to_xmpp(mcp_data)
        assert msg.message_type == "chat"  # Should default

    def test_send_xmpp_message_special_characters_in_attributes(self):
        """Test XML escaping in JID and message type attributes."""
        msg = SendXmppMessage(
            jid="user&test@exam<ple.com",  # Contains XML special chars
            body="Normal body",
            message_type="cha<t&type",  # Contains XML special chars
        )

        stanza = msg.to_stanza()
        assert "user&amp;test@exam&lt;ple.com" in stanza
        assert "cha&lt;t&amp;type" in stanza
