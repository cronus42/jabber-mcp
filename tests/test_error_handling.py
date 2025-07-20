"""Unit tests for error handling, back-pressure, and retry logic."""

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from jabber_mcp.bridge.mcp_bridge import (
    _DEFAULT_QUEUE_TIMEOUT,
    _QUEUE_PUT_TIMEOUT,
    ConnectionState,
    McpBridge,
    RetryConfig,
)


class TestRetryConfig:
    """Test RetryConfig dataclass and utility functions."""

    def test_default_retry_config(self):
        """Test default retry configuration values."""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 30.0
        assert config.backoff_multiplier == 2.0
        assert config.jitter is True

    def test_custom_retry_config(self):
        """Test custom retry configuration."""
        config = RetryConfig(
            max_attempts=5,
            initial_delay=0.5,
            max_delay=60.0,
            backoff_multiplier=1.5,
            jitter=False,
        )
        assert config.max_attempts == 5
        assert config.initial_delay == 0.5
        assert config.max_delay == 60.0
        assert config.backoff_multiplier == 1.5
        assert config.jitter is False


class TestRetryDelayCalculation:
    """Test retry delay calculation with backoff."""

    def test_first_attempt_no_delay(self):
        """Test that first attempt has no delay."""
        config = RetryConfig()
        delay = McpBridge._calculate_retry_delay(0, config)
        assert delay == 0

    def test_exponential_backoff_without_jitter(self):
        """Test exponential backoff calculation without jitter."""
        config = RetryConfig(
            initial_delay=1.0, backoff_multiplier=2.0, max_delay=10.0, jitter=False
        )

        # Second attempt: 1.0 * (2.0 ^ 0) = 1.0
        delay = McpBridge._calculate_retry_delay(1, config)
        assert delay == 1.0

        # Third attempt: 1.0 * (2.0 ^ 1) = 2.0
        delay = McpBridge._calculate_retry_delay(2, config)
        assert delay == 2.0

        # Fourth attempt: 1.0 * (2.0 ^ 2) = 4.0
        delay = McpBridge._calculate_retry_delay(3, config)
        assert delay == 4.0

    def test_max_delay_capping(self):
        """Test that delay is capped at max_delay."""
        config = RetryConfig(
            initial_delay=1.0, backoff_multiplier=2.0, max_delay=5.0, jitter=False
        )

        # This would be 8.0 without capping, should be capped at 5.0
        delay = McpBridge._calculate_retry_delay(4, config)
        assert delay == 5.0

    def test_jitter_adds_randomness(self):
        """Test that jitter adds randomness to delay."""
        config = RetryConfig(
            initial_delay=4.0, backoff_multiplier=1.0, max_delay=10.0, jitter=True
        )

        delays = []
        for _ in range(10):
            delay = McpBridge._calculate_retry_delay(1, config)
            delays.append(delay)

        # With jitter, delays should vary
        assert len(set(delays)) > 1  # Should have different values
        # All delays should be positive and within reasonable bounds
        for delay in delays:
            assert delay >= 0
            assert delay <= 6.0  # 4.0 + 25% jitter range = 5.0, but some variance


class ConcreteMcpBridge(McpBridge):
    """Concrete implementation of McpBridge for testing."""

    def __init__(self, queue_size: int = 10):
        super().__init__(queue_size)
        self.xmpp_to_mcp_messages: list[dict[str, Any]] = []
        self.mcp_to_xmpp_messages: list[dict[str, Any]] = []

    async def _process_xmpp_to_mcp(self) -> None:
        """Mock implementation that records processed messages."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.xmpp_to_mcp, timeout=0.1)
                if message:
                    self.xmpp_to_mcp_messages.append(message)
            except asyncio.CancelledError:
                break

    async def _process_mcp_to_xmpp(self) -> None:
        """Mock implementation that records processed messages."""
        while self._running:
            try:
                message = await self._safe_queue_get(self.mcp_to_xmpp, timeout=0.1)
                if message:
                    self.mcp_to_xmpp_messages.append(message)
            except asyncio.CancelledError:
                break


class TestBackPressureHandling:
    """Test back-pressure handling in queue operations."""

    @pytest.fixture
    def bridge(self):
        """Create a concrete MCP Bridge instance for testing."""
        return ConcreteMcpBridge(queue_size=3)  # Small queue for testing

    async def test_send_to_jabber_with_backpressure_success(self, bridge, caplog):
        """Test successful message sending with back-pressure."""
        # Fill queue to capacity but not beyond
        for i in range(3):
            await bridge.send_to_jabber("user@example.com", f"Message {i}")

        # Start bridge to consume messages
        await bridge.start()

        # Give processing time
        await asyncio.sleep(0.1)

        # Queue should now have space, this should succeed
        await bridge.send_to_jabber("user@example.com", "Final message")

        await bridge.stop()

    async def test_send_to_jabber_timeout_on_backpressure(self, bridge):
        """Test timeout when back-pressure persists."""
        # Fill queue completely
        for i in range(3):
            await bridge.send_to_jabber("user@example.com", f"Message {i}")

        # Don't start bridge (no consumers), so queue stays full

        # This should timeout due to back-pressure
        with pytest.raises(asyncio.TimeoutError):
            await bridge.send_to_jabber("user@example.com", "Will timeout", timeout=0.1)

    async def test_back_pressure_warning_logging(self, bridge, caplog):
        """Test that back-pressure triggers appropriate warnings."""
        # Fill queue completely
        for i in range(3):
            await bridge.send_to_jabber("user@example.com", f"Message {i}")

        with caplog.at_level(logging.WARNING):
            try:
                await bridge.send_to_jabber("user@example.com", "Overflow", timeout=0.1)
            except asyncio.TimeoutError:
                pass  # Expected

        # Should have warning about full queue
        assert any("queue is full" in record.message for record in caplog.records)


class TestSafeQueueOperations:
    """Test safe queue operations with timeout handling."""

    @pytest.fixture
    def bridge(self):
        return ConcreteMcpBridge(queue_size=5)

    async def test_safe_queue_get_with_item(self, bridge):
        """Test safe queue get when item is available."""
        # Add an item to the queue
        test_message = {"type": "test", "data": "hello"}
        await bridge.xmpp_to_mcp.put(test_message)

        # Should get the item
        result = await bridge._safe_queue_get(bridge.xmpp_to_mcp, timeout=1.0)
        assert result == test_message

    async def test_safe_queue_get_timeout(self, bridge):
        """Test safe queue get with timeout."""
        # Queue is empty, should timeout and return None
        result = await bridge._safe_queue_get(bridge.xmpp_to_mcp, timeout=0.1)
        assert result is None

    async def test_safe_queue_get_cancellation(self, bridge):
        """Test safe queue get handles cancellation."""

        async def cancelled_get():
            await bridge._safe_queue_get(bridge.xmpp_to_mcp, timeout=10.0)

        task = asyncio.create_task(cancelled_get())
        await asyncio.sleep(0.01)  # Brief delay
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


class TestRetryWithBackoff:
    """Test retry mechanism with exponential backoff."""

    @pytest.fixture
    def bridge(self):
        return ConcreteMcpBridge(queue_size=5)

    async def test_retry_success_on_first_attempt(self, bridge):
        """Test operation succeeds on first attempt."""
        operation = AsyncMock(return_value="success")
        config = RetryConfig(max_attempts=3)

        result = await bridge._retry_with_backoff(operation, config, "test_op")

        assert result == "success"
        operation.assert_called_once()

    async def test_retry_success_after_failures(self, bridge, caplog):
        """Test operation succeeds after some failures."""
        operation = AsyncMock(
            side_effect=[
                ValueError("First failure"),
                RuntimeError("Second failure"),
                "success",
            ]
        )
        config = RetryConfig(
            max_attempts=3, initial_delay=0.01
        )  # Fast retries for test

        with caplog.at_level(logging.WARNING):
            result = await bridge._retry_with_backoff(operation, config, "test_op")

        assert result == "success"
        assert operation.call_count == 3

        # Check warning logs
        warnings = [
            record for record in caplog.records if record.levelno >= logging.WARNING
        ]
        assert len(warnings) >= 2  # Should have warnings for first two failures

    async def test_retry_failure_after_max_attempts(self, bridge):
        """Test operation fails after max attempts."""
        operation = AsyncMock(side_effect=ValueError("Persistent failure"))
        config = RetryConfig(max_attempts=2, initial_delay=0.01)

        with pytest.raises(ValueError, match="Persistent failure"):
            await bridge._retry_with_backoff(operation, config, "test_op")

        assert operation.call_count == 2

    async def test_retry_with_different_exceptions(self, bridge):
        """Test retry handles different exception types."""
        exceptions = [
            ConnectionError("Network error"),
            TimeoutError("Request timeout"),
            ValueError("Data error"),
        ]
        operation = AsyncMock(side_effect=exceptions)
        config = RetryConfig(max_attempts=3, initial_delay=0.01)

        with pytest.raises(ValueError, match="Data error"):  # Last exception
            await bridge._retry_with_backoff(operation, config, "test_op")


class TestConnectionStateEnum:
    """Test ConnectionState enum."""

    def test_connection_states(self):
        """Test all connection state values."""
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.RECONNECTING.value == "reconnecting"
        assert ConnectionState.FAILED.value == "failed"


class TestIntegratedErrorHandling:
    """Test integrated error handling scenarios."""

    @pytest.fixture
    def bridge(self):
        return ConcreteMcpBridge(queue_size=5)

    async def test_queue_overflow_with_recovery(self, bridge, caplog):
        """Test system recovery after queue overflow."""
        # Fill queue beyond capacity
        for i in range(5):
            await bridge.send_to_jabber("user@example.com", f"Message {i}")

        # Start processing to drain queue
        await bridge.start()

        # Wait for some processing
        await asyncio.sleep(0.1)

        # Now sending should work again
        with caplog.at_level(logging.DEBUG):
            await bridge.send_to_jabber("user@example.com", "Recovery message")

        await bridge.stop()

        # Should have processed at least some messages
        assert len(bridge.mcp_to_xmpp_messages) > 0

    async def test_error_handling_during_processing(self, bridge):
        """Test error handling during message processing."""
        # Add a message
        await bridge.handle_incoming_xmpp_message("test@example.com", "Hello", "chat")

        # Start bridge
        await bridge.start()

        # Let it process
        await asyncio.sleep(0.1)

        await bridge.stop()

        # Message should be processed despite any minor errors
        assert len(bridge.xmpp_to_mcp_messages) == 1
        assert bridge.xmpp_to_mcp_messages[0]["body"] == "Hello"

    async def test_incoming_xmpp_message_timeout_handling(self, bridge):
        """Test timeout handling for incoming XMPP messages."""
        # Fill queue completely
        for i in range(5):
            await bridge.handle_incoming_xmpp_message(
                f"user{i}@example.com", f"Message {i}", "chat"
            )

        # Don't start bridge (no consumers), so queue stays full

        # This should timeout due to back-pressure
        with pytest.raises(asyncio.TimeoutError):
            await bridge.handle_incoming_xmpp_message(
                "overflow@example.com", "Will timeout", "chat", timeout=0.1
            )

    async def test_incoming_presence_timeout_handling(self, bridge):
        """Test timeout handling for incoming XMPP presence updates."""
        # Fill queue completely with messages first
        for i in range(5):
            await bridge.handle_incoming_xmpp_message(
                f"user{i}@example.com", f"Message {i}", "chat"
            )

        # Don't start bridge (no consumers), so queue stays full

        # Presence update should also timeout
        with pytest.raises(asyncio.TimeoutError):
            await bridge.handle_incoming_xmpp_presence(
                "overflow@example.com", "available", "Online", timeout=0.1
            )

    async def test_back_pressure_warning_on_incoming_messages(self, bridge, caplog):
        """Test that back-pressure triggers warnings for incoming messages."""
        # Fill queue completely
        for i in range(5):
            await bridge.handle_incoming_xmpp_message(
                f"user{i}@example.com", f"Message {i}", "chat"
            )

        with caplog.at_level(logging.WARNING):
            try:
                await bridge.handle_incoming_xmpp_message(
                    "overflow@example.com", "Overflow msg", "chat", timeout=0.1
                )
            except asyncio.TimeoutError:
                pass  # Expected

        # Should have warning about full queue
        assert any("queue is full" in record.message for record in caplog.records)
        assert any(
            "attempting timed put" in record.message for record in caplog.records
        )

    async def test_connection_state_tracking(self, bridge):
        """Test connection state management."""
        # Bridge starts disconnected
        assert bridge.get_connection_state() == ConnectionState.DISCONNECTED

        # Start bridge
        await bridge.start()
        assert bridge.get_connection_state() == ConnectionState.CONNECTED

        # Stop bridge
        await bridge.stop()
        assert bridge.get_connection_state() == ConnectionState.DISCONNECTED


if __name__ == "__main__":
    pytest.main([__file__])
