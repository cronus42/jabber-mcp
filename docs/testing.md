# Testing Documentation

This document describes the comprehensive test suite for the XMPP-MCP bridge project.

## Test Structure

The project includes three main categories of tests:

### 1. Unit Tests for AddressBook (`tests/test_address_book.py`)

Tests the core functionality of the AddressBook class:

- **Alias management**: Save, query, and remove aliases
- **Input validation**: Invalid JID and alias handling
- **Fuzzy search**: Search functionality with score-based ranking
- **Data persistence**: Load and save to JSON files
- **Thread safety**: Async operations with locking

**Key test scenarios:**
```python
# Basic functionality
test_save_and_query_alias()          # Save alias and retrieve via fuzzy search
test_invalid_alias()                 # Validation of empty/invalid aliases
test_invalid_jid()                   # Validation of malformed JIDs
test_remove_alias()                  # Alias removal and cleanup
test_clear_address_book()            # Bulk clearing operations
```

### 2. Unit Tests for Inbox Limits (`tests/test_inbox_limits.py`)

Tests the inbox message management and limits:

- **Size limits**: Inbox capacity enforcement using deque maxlen
- **Message retrieval**: Get messages by UUID and listing with limits
- **Statistics**: Track inbox usage and capacity
- **Thread safety**: Concurrent access to inbox operations
- **Memory management**: Automatic oldest message dropping

**Key test scenarios:**
```python
# Inbox capacity management
test_inbox_maxlen_enforcement()      # Ensures oldest messages are dropped
test_get_inbox_list_limit()          # Pagination support
test_get_inbox_message_by_uuid()     # Individual message retrieval
test_inbox_stats()                   # Usage statistics tracking
test_clear_inbox()                   # Bulk clearing with count
test_thread_safety()                 # Concurrent operations safety
test_inbox_deque_behavior()          # Underlying deque behavior
```

### 3. Integration Tests (`tests/test_xmpp_inbox_integration.py`)

Tests the complete message flow from fake XMPP adapter to inbox:

- **Message injection**: Fake XmppAdapter that can inject test messages
- **End-to-end flow**: XMPP → bridge → inbox → retrieval
- **Concurrency**: Multiple simultaneous message injection
- **Overflow handling**: Behavior when inbox capacity is exceeded
- **Bi-directional communication**: Both incoming and outgoing messages

**Key test scenarios:**
```python
# Full integration scenarios
test_message_injection_to_inbox()           # Basic message flow
test_multiple_message_injection()           # Bulk message handling
test_inbox_overflow_with_injection()        # Capacity limit behavior
test_message_retrieval_by_uuid()            # End-to-end retrieval
test_send_message_via_fake_adapter()        # Outgoing message flow
test_presence_injection()                   # Presence update handling
test_concurrent_message_injection()         # Thread safety under load
test_inbox_stats_after_injection()          # Statistics accuracy
```

## Test Configuration

### Environment Variables

Test configuration uses environment variables to avoid committing credentials:

```bash
# Copy the example file and fill in test credentials
cp .env.example .env.test

# Required for integration tests (optional)
TEST_XMPP_JID=testuser@example.org
TEST_XMPP_PASSWORD=your_test_password_here
TEST_XMPP_SERVER=localhost
TEST_XMPP_PORT=5222
TEST_RECIPIENT_JID=recipient@example.org
```

### Test Safety Features

- **No hardcoded credentials**: All sensitive data via environment variables
- **Validation checks**: `validate_test_environment()` prevents credential leaks
- **Isolated fixtures**: Each test uses clean, isolated instances
- **Fake adapters**: Integration tests use fake XMPP adapters, not real connections

## Running Tests

### Individual Test Suites

```bash
# Unit tests for AddressBook
python -m pytest tests/test_address_book.py -v

# Unit tests for Inbox limits
python -m pytest tests/test_inbox_limits.py -v

# Integration tests
python -m pytest tests/test_xmpp_inbox_integration.py -v
```

### All New Tests

```bash
# Run all new comprehensive tests
python -m pytest tests/test_address_book.py tests/test_inbox_limits.py tests/test_xmpp_inbox_integration.py -v
```

### With Coverage

```bash
# Generate coverage report
python -m pytest tests/test_address_book.py tests/test_inbox_limits.py tests/test_xmpp_inbox_integration.py --cov=src/jabber_mcp --cov-report=html
```

## DevOps Integration

### Pre-commit Hooks

The project uses pre-commit hooks for code quality:

```bash
# Install hooks
pre-commit install

# Run hooks manually
pre-commit run --all-files
```

### Type Checking

```bash
# Run mypy type checking
python -m mypy src/jabber_mcp/ --ignore-missing-imports
```

### Linting

```bash
# Run ruff linting with auto-fix
python -m ruff check --fix src/jabber_mcp/ tests/
```

### Formatting

```bash
# Auto-format code with ruff
python -m ruff format src/jabber_mcp/ tests/
```

## Test Markers

Tests use pytest markers for categorization:

- `@pytest.mark.asyncio`: Async test functions
- `@pytest.mark.integration`: Integration tests (vs unit tests)

Run specific categories:

```bash
# Run only integration tests
python -m pytest -m integration

# Skip integration tests
python -m pytest -m "not integration"
```

## Mocking and Fakes

### FakeXmppAdapter

The integration tests use a `FakeXmppAdapter` class that:

- Simulates XMPP connection without network calls
- Allows message injection for testing
- Tracks sent messages for verification
- Supports presence updates
- Provides callback mechanisms for realistic behavior

### Benefits

- **Fast execution**: No network delays
- **Reliable**: No external dependencies
- **Controllable**: Deterministic test scenarios
- **Safe**: No risk of sending real messages

## Continuous Integration

The comprehensive test suite is designed to run in CI/CD pipelines:

- All tests are deterministic and repeatable
- No external dependencies required for core functionality
- Environment variable configuration prevents credential exposure
- Comprehensive coverage of critical functionality

## Coverage Goals

The test suite aims for high coverage of:

- **AddressBook**: 95%+ coverage of all public methods
- **Inbox functionality**: 90%+ coverage including edge cases
- **Message flow**: End-to-end integration scenarios
- **Error handling**: Invalid inputs and edge conditions
- **Concurrency**: Thread safety under concurrent access
