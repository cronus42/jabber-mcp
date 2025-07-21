from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from jabber_mcp.xmpp_adapter import XmppAdapter


class TestXmppAdapter:
    def setup_method(self):
        """Setup for each test method."""
        self.jid = "test@example.com"
        self.password = "testpassword"

    def test_adapter_initialization(self):
        """Test that XmppAdapter initializes correctly."""
        adapter = XmppAdapter(self.jid, self.password)
        assert adapter.boundjid.bare == self.jid
        # Check that event handlers are registered by checking the internal structure
        # slixmpp stores handlers in the __event_handlers dict
        assert hasattr(adapter, "event_handler")
        # Basic test that the adapter was created successfully
        assert isinstance(adapter.jid, str)

    @pytest.mark.asyncio
    async def test_normalize_format(self):
        """Test message normalization."""
        adapter = XmppAdapter(self.jid, self.password)

        # Test basic whitespace stripping
        result = await adapter.normalize_format("  hello world  ")
        assert result == "hello world"

        # Test empty string
        result = await adapter.normalize_format("")
        assert result == ""

        # Test already normalized string
        result = await adapter.normalize_format("hello world")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_session_start(self):
        """Test session start handler."""
        adapter = XmppAdapter(self.jid, self.password)

        # Mock the methods that will be called
        adapter.send_presence = Mock()
        adapter.get_roster = AsyncMock()
        adapter._sync_roster_with_bridge = AsyncMock()

        # Call session_start
        await adapter.session_start({})

        # Verify methods were called
        adapter.send_presence.assert_called_once()
        adapter.get_roster.assert_called_once()
        adapter._sync_roster_with_bridge.assert_called_once()

    def test_message_received_chat_type(self):
        """Test message_received handler for chat messages."""
        adapter = XmppAdapter(self.jid, self.password)

        # Create a mock message with magic method support
        mock_msg = MagicMock()
        mock_msg.__getitem__.return_value = "chat"  # msg['type']

        with patch("asyncio.create_task") as mock_create_task:
            adapter.message_received(mock_msg)
            mock_create_task.assert_called_once()

    def test_message_received_normal_type(self):
        """Test message_received handler for normal messages."""
        adapter = XmppAdapter(self.jid, self.password)

        # Create a mock message
        mock_msg = MagicMock()
        mock_msg.__getitem__.return_value = "normal"  # msg['type']

        with patch("asyncio.create_task") as mock_create_task:
            adapter.message_received(mock_msg)
            mock_create_task.assert_called_once()

    def test_message_received_ignore_other_types(self):
        """Test that non-chat/normal messages are ignored."""
        adapter = XmppAdapter(self.jid, self.password)

        # Create a mock message with different type
        mock_msg = MagicMock()
        mock_msg.__getitem__.return_value = "groupchat"  # msg['type']

        with patch("asyncio.create_task") as mock_create_task:
            adapter.message_received(mock_msg)
            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_message(self):
        """Test message processing (currently just logs)."""
        adapter = XmppAdapter(self.jid, self.password)

        # Create a mock message
        mock_msg = MagicMock()
        mock_msg.__getitem__.side_effect = lambda key: {
            "from": "sender@example.com",
            "body": "Hello, world!",
        }[key]

        with patch("logging.info") as mock_log:
            await adapter.process_message(mock_msg)
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_to_jid(self):
        """Test sending a message."""
        adapter = XmppAdapter(self.jid, self.password)

        # Mock the inherited send_message method
        adapter.send_message = Mock()

        await adapter.send_message_to_jid("recipient@example.com", "  Hello  ")

        # Verify send_message was called with normalized content
        adapter.send_message.assert_called_once_with(
            mto="recipient@example.com", mbody="Hello", mtype="chat"
        )

    @pytest.mark.asyncio
    async def test_sync_roster_with_bridge_no_bridge(self):
        """Test roster sync when no bridge is available."""
        adapter = XmppAdapter(self.jid, self.password)

        # Should not raise any errors when no bridge is present
        await adapter._sync_roster_with_bridge()

    @pytest.mark.asyncio
    async def test_sync_roster_with_bridge_with_mcp_bridge(self):
        """Test roster sync with MCP bridge."""
        mock_bridge = Mock()
        adapter = XmppAdapter(self.jid, self.password, mcp_bridge=mock_bridge)

        # Mock the roster parsing
        adapter._parse_roster = Mock(
            return_value=[
                ("user1@example.com", "User One"),
                ("user2@example.com", None),
            ]
        )

        await adapter._sync_roster_with_bridge()

        # Verify roster parsing was called
        adapter._parse_roster.assert_called_once()

    def test_parse_roster_no_client_roster(self):
        """Test roster parsing when client_roster is not available."""
        adapter = XmppAdapter(self.jid, self.password)

        # Should return empty list when no client_roster
        result = adapter._parse_roster()
        assert result == []

    def test_parse_roster_with_entries(self):
        """Test roster parsing with actual roster entries."""
        adapter = XmppAdapter(self.jid, self.password)

        # Mock the client_roster
        adapter.client_roster = {
            "user1@example.com": {"name": "User One"},
            "user2@example.com": {},
            "user3@example.com": {"name": "User Three"},
        }

        result = adapter._parse_roster()

        expected = [
            ("user1@example.com", "User One"),
            ("user2@example.com", None),
            ("user3@example.com", "User Three"),
        ]

        # Sort both lists for comparison since order might vary
        result.sort()
        expected.sort()
        assert result == expected

    @pytest.mark.asyncio
    async def test_on_roster_update_no_bridge(self):
        """Test roster update event handler when no bridge is available."""
        adapter = XmppAdapter(self.jid, self.password)

        # Should not raise any errors when no bridge is present
        await adapter.on_roster_update({"event": "roster_update"})

    @pytest.mark.asyncio
    async def test_on_roster_update_with_bridge(self):
        """Test roster update event handler with MCP bridge."""
        mock_bridge = Mock()
        adapter = XmppAdapter(self.jid, self.password, mcp_bridge=mock_bridge)

        # Mock the sync method
        adapter._sync_roster_with_bridge = AsyncMock()

        await adapter.on_roster_update({"event": "roster_update"})

        # Verify sync was called
        adapter._sync_roster_with_bridge.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_roster_subscription_no_bridge(self):
        """Test roster subscription event handler when no bridge is available."""
        adapter = XmppAdapter(self.jid, self.password)

        # Should not raise any errors when no bridge is present
        await adapter.on_roster_subscription({"event": "roster_subscription"})

    @pytest.mark.asyncio
    async def test_on_roster_subscription_with_bridge(self):
        """Test roster subscription event handler with MCP bridge."""
        mock_bridge = Mock()
        adapter = XmppAdapter(self.jid, self.password, mcp_bridge=mock_bridge)

        # Mock the sync method
        adapter._sync_roster_with_bridge = AsyncMock()

        await adapter.on_roster_subscription({"event": "roster_subscription"})

        # Verify sync was called
        adapter._sync_roster_with_bridge.assert_called_once()


class TestXmppAdapterIntegration:
    """Integration tests that would require actual XMPP server."""

    def test_placeholder_integration(self):
        """Placeholder for integration tests."""
        # These would require setting up test XMPP server
        # or using mock XMPP server
        pass
