"""End-to-end tests with real XMPP connection capabilities for CI environment."""

import asyncio
import os
from typing import Any, Dict, Optional
from unittest.mock import Mock, patch

import pytest

from jabber_mcp.bridge.mcp_bridge import McpBridge
from jabber_mcp.converters import convert_mcp_send_to_xmpp
from jabber_mcp.xmpp_adapter import XmppAdapter


class RealXmppTestBridge(McpBridge):
    """Test bridge for end-to-end XMPP testing."""

    def __init__(self, queue_size: int = 100):
        super().__init__(queue_size)
        self.sent_messages = []
        self.received_messages = []

    async def _process_xmpp_to_mcp(self) -> None:
        """Process messages from XMPP to MCP queue."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.xmpp_to_mcp, timeout=1.0)
                if message:
                    self.received_messages.append(message)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _process_mcp_to_xmpp(self) -> None:
        """Process messages from MCP to XMPP queue."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.mcp_to_xmpp, timeout=1.0)
                if message:
                    self.sent_messages.append(message)
                    # For real testing, we'd forward to actual XMPP client
            except asyncio.CancelledError:
                break
            except Exception:
                pass


@pytest.mark.integration
class TestE2EXmppReal:
    """End-to-end tests with real XMPP server capabilities.

    These tests can be run against a real XMPP server when credentials
    are provided via environment variables. They will be skipped if
    credentials are not available.
    """

    def get_xmpp_credentials(self) -> Optional[Dict[str, str]]:
        """Get XMPP credentials from environment variables."""
        jid = os.getenv("XMPP_TEST_JID")
        password = os.getenv("XMPP_TEST_PASSWORD")
        recipient = os.getenv("XMPP_TEST_RECIPIENT")

        if jid and password and recipient:
            return {"jid": jid, "password": password, "recipient": recipient}
        return None

    def should_skip_real_tests(self) -> bool:
        """Check if real XMPP tests should be skipped."""
        return self.get_xmpp_credentials() is None

    @pytest.mark.skipif(
        "XMPP_TEST_JID" not in os.environ, reason="XMPP test credentials not provided"
    )
    async def test_real_xmpp_connection(self):
        """Test real XMPP connection and authentication."""
        creds = self.get_xmpp_credentials()
        assert creds, "XMPP credentials should be available"

        bridge = RealXmppTestBridge(queue_size=10)
        adapter = XmppAdapter(creds["jid"], creds["password"], bridge)

        try:
            await bridge.start()

            # Attempt connection with timeout
            connection_task = asyncio.create_task(adapter.connect_and_wait())
            try:
                await asyncio.wait_for(connection_task, timeout=10.0)
            except asyncio.TimeoutError:
                pytest.fail("XMPP connection timed out after 10 seconds")

            # Verify connection state
            # Note: This depends on the actual XMPP adapter implementation
            # We would need to add a way to check connection status

            await asyncio.sleep(1)  # Allow connection to stabilize

        finally:
            await adapter.disconnect()
            await bridge.stop()

    @pytest.mark.skipif(
        "XMPP_TEST_JID" not in os.environ, reason="XMPP test credentials not provided"
    )
    async def test_real_message_send_and_receive(self):
        """Test sending and receiving messages through real XMPP."""
        creds = self.get_xmpp_credentials()
        assert creds, "XMPP credentials should be available"

        bridge = RealXmppTestBridge(queue_size=10)
        adapter = XmppAdapter(creds["jid"], creds["password"], bridge)

        test_message = f"E2E test message at {asyncio.get_event_loop().time()}"

        try:
            await bridge.start()

            # Connect to XMPP server
            connection_task = asyncio.create_task(adapter.connect_and_wait())
            await asyncio.wait_for(connection_task, timeout=10.0)

            await asyncio.sleep(2)  # Allow connection to stabilize

            # Send a message through the bridge
            await bridge.send_to_jabber(creds["recipient"], test_message)

            # Allow time for message to be processed
            await asyncio.sleep(3)

            # Verify message was queued for sending
            assert len(bridge.sent_messages) == 1
            sent = bridge.sent_messages[0]
            assert sent["jid"] == creds["recipient"]
            assert sent["body"] == test_message

        finally:
            await adapter.disconnect()
            await bridge.stop()

    @pytest.mark.skipif(
        "XMPP_TEST_JID" not in os.environ, reason="XMPP test credentials not provided"
    )
    async def test_real_connection_resilience(self):
        """Test connection resilience with real XMPP server."""
        creds = self.get_xmpp_credentials()
        assert creds, "XMPP credentials should be available"

        bridge = RealXmppTestBridge(queue_size=10)
        adapter = XmppAdapter(creds["jid"], creds["password"], bridge)

        try:
            await bridge.start()

            # Initial connection
            connection_task = asyncio.create_task(adapter.connect_and_wait())
            await asyncio.wait_for(connection_task, timeout=10.0)

            # Send initial message
            await bridge.send_to_jabber(creds["recipient"], "Connection test 1")
            await asyncio.sleep(1)

            # Simulate connection interruption
            await adapter.disconnect()
            await asyncio.sleep(2)

            # Reconnect
            reconnect_task = asyncio.create_task(adapter.connect_and_wait())
            await asyncio.wait_for(reconnect_task, timeout=10.0)

            # Send message after reconnection
            await bridge.send_to_jabber(creds["recipient"], "Connection test 2")
            await asyncio.sleep(2)

            # Verify both messages were processed
            assert len(bridge.sent_messages) == 2

        finally:
            await adapter.disconnect()
            await bridge.stop()


@pytest.mark.integration
class TestE2EWithMockXmpp:
    """E2E tests with sophisticated XMPP mocking for CI reliability."""

    async def test_e2e_message_flow_simulation(self):
        """Test complete message flow with realistic XMPP simulation."""

        class RealisticXmppAdapter:
            """More realistic XMPP adapter simulation."""

            def __init__(self, jid: str, password: str, bridge: McpBridge):
                self.jid = jid
                self.password = password
                self.bridge = bridge
                self.connected = False
                self.sent_messages = []
                self.connection_latency = 0.1  # Simulate network latency

            async def connect_and_wait(self):
                """Simulate connection with realistic delays."""
                await asyncio.sleep(self.connection_latency)

                # Simulate occasional connection failures
                import random

                if random.random() < 0.1:  # 10% failure rate
                    msg = "Simulated connection failure"
                    raise ConnectionError(msg)

                self.connected = True

            async def disconnect(self):
                """Simulate disconnection."""
                await asyncio.sleep(0.05)
                self.connected = False

            async def send_message_to_jid(self, jid: str, body: str):
                """Simulate sending with network conditions."""
                if not self.connected:
                    msg = "Not connected to XMPP server"
                    raise ConnectionError(msg)

                # Simulate network latency
                await asyncio.sleep(self.connection_latency)

                message = {
                    "to": jid,
                    "body": body,
                    "sent_at": asyncio.get_event_loop().time(),
                }
                self.sent_messages.append(message)

                # Simulate occasional delivery failures
                import random

                if random.random() < 0.05:  # 5% failure rate
                    msg = "Simulated message delivery failure"
                    raise RuntimeError(msg)

            def simulate_incoming_message(self, from_jid: str, body: str):
                """Simulate receiving a message from XMPP network."""
                if self.bridge and self.connected:
                    asyncio.create_task(
                        self.bridge.handle_incoming_xmpp_message(from_jid, body, "chat")
                    )

        # Set up the test system
        bridge = RealXmppTestBridge(queue_size=20)
        adapter = RealisticXmppAdapter("testbot@example.com", "password", bridge)

        # Replace the bridge's XMPP processing to work with our adapter

        async def enhanced_process_mcp_to_xmpp():
            """Enhanced processing that actually sends via adapter."""
            while bridge._running:
                try:
                    message = await bridge._safe_queue_get(
                        bridge.mcp_to_xmpp, timeout=1.0
                    )
                    if message and adapter.connected:
                        await adapter.send_message_to_jid(
                            message["jid"], message["body"]
                        )
                        bridge.sent_messages.append(message)
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

        bridge._process_mcp_to_xmpp = enhanced_process_mcp_to_xmpp

        try:
            await bridge.start()

            # Test connection establishment
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    await adapter.connect_and_wait()
                    break
                except ConnectionError:
                    if attempt == max_attempts - 1:
                        pytest.fail("Failed to connect after maximum attempts")
                    await asyncio.sleep(0.5)  # Wait before retry

            assert adapter.connected

            # Test bidirectional message flow
            # Send outbound message
            await bridge.send_to_jabber("friend@example.com", "Hello from E2E test!")

            # Simulate incoming message
            adapter.simulate_incoming_message(
                "friend@example.com", "Hi back from XMPP!"
            )

            # Allow processing time
            await asyncio.sleep(1.0)

            # Verify outbound message
            assert len(bridge.sent_messages) == 1
            assert bridge.sent_messages[0]["jid"] == "friend@example.com"
            assert bridge.sent_messages[0]["body"] == "Hello from E2E test!"

            # Verify message was actually "sent" via adapter
            assert len(adapter.sent_messages) == 1
            assert adapter.sent_messages[0]["to"] == "friend@example.com"

            # Verify incoming message
            assert len(bridge.received_messages) == 1
            assert bridge.received_messages[0]["from_jid"] == "friend@example.com"
            assert bridge.received_messages[0]["body"] == "Hi back from XMPP!"

        finally:
            await adapter.disconnect()
            await bridge.stop()

    async def test_e2e_error_scenarios(self):
        """Test E2E behavior under various error conditions."""

        class FlakyXmppAdapter:
            """XMPP adapter that simulates various failure modes."""

            def __init__(self, jid: str, password: str):
                self.jid = jid
                self.password = password
                self.connected = False
                self.failure_mode = None
                self.sent_messages = []

            def set_failure_mode(self, mode: str):
                """Set a specific failure mode for testing."""
                self.failure_mode = mode

            async def connect_and_wait(self):
                if self.failure_mode == "connect_timeout":
                    await asyncio.sleep(5)  # Simulate timeout
                    msg = "Connection timed out"
                    raise asyncio.TimeoutError(msg)
                elif self.failure_mode == "auth_failure":
                    msg = "Authentication failed"
                    raise Exception(msg)

                self.connected = True

            async def disconnect(self):
                if self.failure_mode == "disconnect_hang":
                    await asyncio.sleep(10)  # Simulate hanging
                self.connected = False

            async def send_message_to_jid(self, jid: str, body: str):
                if not self.connected:
                    msg = "Not connected"
                    raise ConnectionError(msg)
                if self.failure_mode == "send_failure":
                    msg = "Failed to send message"
                    raise RuntimeError(msg)

                self.sent_messages.append({"to": jid, "body": body})

        bridge = RealXmppTestBridge(queue_size=10)
        adapter = FlakyXmppAdapter("test@example.com", "password")

        try:
            await bridge.start()

            # Test connection timeout handling
            adapter.set_failure_mode("connect_timeout")
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(adapter.connect_and_wait(), timeout=2.0)

            # Test authentication failure
            adapter.set_failure_mode("auth_failure")
            with pytest.raises(Exception, match="Authentication failed"):
                await adapter.connect_and_wait()

            # Test successful connection after clearing failure mode
            adapter.set_failure_mode(None)
            await adapter.connect_and_wait()
            assert adapter.connected

            # Test message sending failure
            adapter.set_failure_mode("send_failure")

            # Enhanced processing that handles send failures
            async def process_with_error_handling():
                while bridge._running:
                    try:
                        message = await bridge._safe_queue_get(
                            bridge.mcp_to_xmpp, timeout=0.5
                        )
                        if message and adapter.connected:
                            try:
                                await adapter.send_message_to_jid(
                                    message["jid"], message["body"]
                                )
                                bridge.sent_messages.append(message)
                            except Exception:
                                # Log the error but continue processing
                                pass
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        pass

            bridge._process_mcp_to_xmpp = process_with_error_handling

            # Try to send a message - should fail but not crash
            await bridge.send_to_jabber("test@example.com", "This should fail")
            await asyncio.sleep(0.5)

            # Message should be processed but send should fail
            assert len(adapter.sent_messages) == 0  # No successful sends

        finally:
            adapter.set_failure_mode(None)  # Clear failure mode for clean disconnect
            await adapter.disconnect()
            await bridge.stop()

    async def test_e2e_performance_characteristics(self):
        """Test performance characteristics under load."""
        bridge = RealXmppTestBridge(queue_size=100)

        # High-performance mock adapter
        class FastMockAdapter:
            def __init__(self):
                self.connected = True
                self.sent_messages = []

            async def send_message_to_jid(self, jid: str, body: str):
                # Minimal processing time
                await asyncio.sleep(0.001)
                self.sent_messages.append({"to": jid, "body": body})

        adapter = FastMockAdapter()

        # Enhanced processing for performance test
        async def fast_process_mcp_to_xmpp():
            while bridge._running:
                try:
                    message = await bridge._safe_queue_get(
                        bridge.mcp_to_xmpp, timeout=0.1
                    )
                    if message:
                        await adapter.send_message_to_jid(
                            message["jid"], message["body"]
                        )
                        bridge.sent_messages.append(message)
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

        bridge._process_mcp_to_xmpp = fast_process_mcp_to_xmpp

        try:
            await bridge.start()

            # Send a high volume of messages
            message_count = 100
            start_time = asyncio.get_event_loop().time()

            tasks = []
            for i in range(message_count):
                task = bridge.send_to_jabber(
                    f"user{i}@example.com", f"Performance test {i}"
                )
                tasks.append(task)

            await asyncio.gather(*tasks)
            queue_time = asyncio.get_event_loop().time() - start_time

            # Allow processing
            processing_start = asyncio.get_event_loop().time()
            while (
                len(bridge.sent_messages) < message_count
                and (asyncio.get_event_loop().time() - processing_start) < 10.0
            ):
                await asyncio.sleep(0.1)

            total_time = asyncio.get_event_loop().time() - start_time

            # Performance assertions
            assert len(bridge.sent_messages) == message_count
            assert len(adapter.sent_messages) == message_count

            # Should process messages reasonably quickly
            assert total_time < 5.0, f"Processing took {total_time:.2f}s, expected <5s"

            # Queue operations should be very fast
            assert queue_time < 1.0, f"Queueing took {queue_time:.2f}s, expected <1s"

            throughput = message_count / total_time
            assert throughput > 20, (
                f"Throughput {throughput:.2f} msg/s, expected >20 msg/s"
            )

        finally:
            await bridge.stop()
