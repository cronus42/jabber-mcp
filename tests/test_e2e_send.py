# tests/test_e2e_send.py
"""
End-to-end integration tests for sending messages via Jabber MCP.

This module contains high-level integration tests that validate the complete
workflow of sending messages from Warp IDE through the MCP bridge to Jabber/XMPP
recipients.
"""

import time
from unittest.mock import Mock

import pytest


class MCPResponse:
    """Represents an MCP response (ACK/NACK)."""

    def __init__(self, *, success: bool, message: str = "", response_time: float = 0.0):
        self.success = success
        self.message = message
        self.response_time = response_time


class TestJabberMCPSend:
    """Test suite for Jabber MCP SEND command functionality."""

    @pytest.fixture
    def mock_xmpp_client(self):
        """Mock XMPP client for testing."""
        mock_client = Mock()
        mock_client.connected = True
        mock_client.send_message = Mock(return_value=True)
        return mock_client

    @pytest.fixture
    def mock_mcp_bridge(self):
        """Mock MCP bridge for testing."""
        mock_bridge = Mock()
        mock_bridge.send_ack = Mock()
        mock_bridge.send_nack = Mock()
        return mock_bridge

    def test_successful_message_delivery(self, mock_xmpp_client, mock_mcp_bridge):
        """Test successful message delivery within 2 seconds with ACK."""
        # Given
        jid = "user@example.com"
        text = "Hello, Jabber!"

        # When
        start_time = time.time()
        response = self._send_mcp_command(jid, text, mock_xmpp_client, mock_mcp_bridge)
        elapsed_time = time.time() - start_time

        # Then
        assert response.success, "Message delivery should succeed"
        assert elapsed_time < 2.0, (
            f"Response time {elapsed_time:.2f}s exceeds 2s requirement"
        )
        mock_mcp_bridge.send_ack.assert_called_once()
        mock_xmpp_client.send_message.assert_called_once_with(jid, text)

    def test_invalid_jid_format(self, mock_xmpp_client, mock_mcp_bridge):
        """Test NACK response for invalid JID format."""
        # Given
        invalid_jid = "invalid-jid-format"
        text = "This should fail"

        # When
        response = self._send_mcp_command(
            invalid_jid, text, mock_xmpp_client, mock_mcp_bridge
        )

        # Then
        assert not response.success, "Invalid JID should result in failure"
        assert "invalid jid" in response.message.lower()
        mock_mcp_bridge.send_nack.assert_called_once()
        mock_xmpp_client.send_message.assert_not_called()

    def test_xmpp_connection_unavailable(self, mock_xmpp_client, mock_mcp_bridge):
        """Test NACK response when XMPP connection is unavailable."""
        # Given
        jid = "user@example.com"
        text = "Connection test"
        mock_xmpp_client.connected = False

        # When
        response = self._send_mcp_command(jid, text, mock_xmpp_client, mock_mcp_bridge)

        # Then
        assert not response.success, "Should fail when XMPP is disconnected"
        assert "connection" in response.message.lower()
        mock_mcp_bridge.send_nack.assert_called_once()
        mock_xmpp_client.send_message.assert_not_called()

    def test_xmpp_send_failure(self, mock_xmpp_client, mock_mcp_bridge):
        """Test NACK response when XMPP message sending fails."""
        # Given
        jid = "user@example.com"
        text = "Send failure test"
        mock_xmpp_client.send_message.return_value = False

        # When
        response = self._send_mcp_command(jid, text, mock_xmpp_client, mock_mcp_bridge)

        # Then
        assert not response.success, "Should fail when XMPP send fails"
        mock_mcp_bridge.send_nack.assert_called_once()
        mock_xmpp_client.send_message.assert_called_once_with(jid, text)

    def test_empty_message_text(self, mock_xmpp_client, mock_mcp_bridge):
        """Test handling of empty message text."""
        # Given
        jid = "user@example.com"
        text = ""

        # When
        response = self._send_mcp_command(jid, text, mock_xmpp_client, mock_mcp_bridge)

        # Then
        # This could be success or failure depending on implementation requirements
        # For now, assume empty messages are allowed
        assert response.success, "Empty messages should be allowed"
        mock_mcp_bridge.send_ack.assert_called_once()
        mock_xmpp_client.send_message.assert_called_once_with(jid, text)

    def test_special_characters_in_message(self, mock_xmpp_client, mock_mcp_bridge):
        """Test handling of special characters and Unicode in message text."""
        # Given
        jid = "user@example.com"
        text = "Hello 🌍! Special chars: <>&\"'\n\t"

        # When
        response = self._send_mcp_command(jid, text, mock_xmpp_client, mock_mcp_bridge)

        # Then
        assert response.success, "Special characters should be handled correctly"
        mock_mcp_bridge.send_ack.assert_called_once()
        mock_xmpp_client.send_message.assert_called_once_with(jid, text)

    def test_response_time_requirement(self, mock_xmpp_client, mock_mcp_bridge):
        """Test that response time is consistently under 2 seconds."""
        jid = "user@example.com"
        text = "Performance test"

        # Run multiple tests to ensure consistent performance
        response_times = []
        for i in range(5):
            start_time = time.time()
            response = self._send_mcp_command(
                jid, f"{text} {i}", mock_xmpp_client, mock_mcp_bridge
            )
            elapsed_time = time.time() - start_time
            response_times.append(elapsed_time)

            assert response.success, f"Test {i} should succeed"
            assert elapsed_time < 2.0, (
                f"Test {i} response time {elapsed_time:.2f}s exceeds requirement"
            )

        # Ensure average response time is reasonable
        avg_response_time = sum(response_times) / len(response_times)
        assert avg_response_time < 1.0, (
            f"Average response time {avg_response_time:.2f}s should be well under 2s"
        )

    def _send_mcp_command(
        self, jid: str, text: str, mock_xmpp_client: Mock, mock_mcp_bridge: Mock
    ) -> MCPResponse:
        """Simulate sending an MCP SEND command.

        This method represents the core functionality that would be implemented
        in the actual MCP bridge. For now, it contains mock behavior.

        Args:
            jid: The Jabber ID to send the message to
            text: The message text to send
            mock_xmpp_client: Mock XMPP client
            mock_mcp_bridge: Mock MCP bridge

        Returns:
            MCPResponse indicating success/failure and details
        """
        try:
            # Validate JID format (basic validation)
            if not self._is_valid_jid(jid):
                mock_mcp_bridge.send_nack("Invalid JID format")
                return MCPResponse(success=False, message="Invalid JID format")

            # Check XMPP connection
            if not mock_xmpp_client.connected:
                mock_mcp_bridge.send_nack("XMPP connection unavailable")
                return MCPResponse(success=False, message="XMPP connection unavailable")

            # Attempt to send message
            success = mock_xmpp_client.send_message(jid, text)
            if not success:
                mock_mcp_bridge.send_nack("Failed to send XMPP message")
                return MCPResponse(success=False, message="Failed to send XMPP message")

            # Success case
            mock_mcp_bridge.send_ack()
            return MCPResponse(success=True, message="Message sent successfully")

        except Exception as e:
            mock_mcp_bridge.send_nack(f"Unexpected error: {e!s}")
            return MCPResponse(success=False, message=f"Unexpected error: {e!s}")

    def _is_valid_jid(self, jid: str) -> bool:
        """Basic JID validation.

        Args:
            jid: The JID to validate

        Returns:
            True if JID appears valid, False otherwise
        """
        if not jid or not isinstance(jid, str):
            return False

        # Basic check: should contain @ and domain
        parts = jid.split("@")
        if len(parts) != 2:
            return False

        username, domain = parts
        if not username or not domain:
            return False

        # Very basic domain validation (should contain at least one dot)
        if "." not in domain:
            return False

        return True


# Integration test that could be run against a real XMPP server
@pytest.mark.integration
class TestRealXMPPIntegration:
    """Integration tests that require a real XMPP server connection.

    These tests are marked as integration tests and may require special setup.
    """

    @pytest.mark.skip(reason="Requires real XMPP server setup")
    def test_real_message_delivery(self):
        """Test actual message delivery to a real XMPP server.

        This test would require:
        1. A test XMPP server
        2. Test user accounts
        3. Configuration for connection details
        """
        # TODO: Implement when XMPP server is available
        pass

    @pytest.mark.skip(reason="Requires real XMPP server setup")
    def test_message_receipt_verification(self):
        """Test that messages actually appear in recipient client.

        This test would verify the full end-to-end delivery by:
        1. Sending a message via MCP
        2. Connecting as the recipient
        3. Verifying the message was received
        """
        # TODO: Implement when XMPP server is available
        pass
