# MCP SEND Command Design Documentation

## Overview

This document outlines the design for implementing the `SEND <jid> <text>` command in the Jabber MCP bridge, allowing Warp IDE to send messages via XMPP/Jabber protocol.

## User Story

**As a** Warp IDE user
**When** Warp IDE issues MCP command `SEND <jid> <text>`
**Then** the project should deliver that text to the given Jabber JID

## Acceptance Criteria

### Performance Requirements
- **Response Time**: Message delivery acknowledgment must be received within 2 seconds
- **Reliability**: System must handle network failures gracefully

### Functional Requirements
1. **Message Delivery**: Text message must appear in recipient's Jabber/XMPP client
2. **ACK/NACK Protocol**:
   - Send ACK (acknowledgment) over MCP for successful delivery
   - Send NACK (negative acknowledgment) over MCP for failed delivery
3. **Input Validation**: Validate JID format before attempting delivery
4. **Connection Management**: Handle XMPP connection availability
5. **Error Handling**: Graceful handling of various failure scenarios

### Technical Requirements
- Command format: `SEND <jid> <text>`
- Protocol: XMPP/Jabber for message delivery
- Interface: MCP (Model Context Protocol) for Warp IDE integration
- Response format: ACK/NACK with appropriate error messages

## Implementation Plan

### Phase 1: Core Infrastructure
- Extend existing XMPP adapter with message sending capability
- Implement MCP command parser for SEND command
- Create ACK/NACK response mechanism

### Phase 2: Integration & Testing
- Comprehensive unit tests for all components
- End-to-end integration tests (see `tests/test_e2e_send.py`)
- Performance testing to ensure 2-second response requirement

### Phase 3: Error Handling & Edge Cases
- Invalid JID format handling
- Network connectivity issues
- XMPP server unavailability
- Message delivery failures

## Test Strategy

### Unit Tests
- JID validation logic
- MCP command parsing
- XMPP message sending
- ACK/NACK response generation

### Integration Tests
Located in `tests/test_e2e_send.py`, covering:

1. **Successful Message Delivery**: Happy path with ACK response
2. **Invalid JID Handling**: NACK for malformed JIDs
3. **Connection Failures**: NACK when XMPP is unavailable
4. **Send Failures**: NACK when XMPP send operation fails
5. **Edge Cases**: Empty messages, special characters
6. **Performance**: Response time verification

### Real-World Testing
- Integration tests with actual XMPP servers
- Message receipt verification in real Jabber clients
- Load testing for performance validation

## Error Scenarios & Responses

| Scenario | Response | Message |
|----------|----------|---------|
| Invalid JID format | NACK | "Invalid JID format" |
| XMPP disconnected | NACK | "XMPP connection unavailable" |
| Send failure | NACK | "Failed to send XMPP message" |
| Success | ACK | "Message sent successfully" |

## Future Considerations

### Security
- Message encryption support
- Authentication mechanisms
- Rate limiting

### Features
- Message delivery receipts
- Offline message queuing
- Group chat support
- File transfer capabilities

### Monitoring
- Message delivery metrics
- Response time monitoring
- Error rate tracking
- Connection health monitoring

## Files Created/Modified

- `USER_STORY.md`: Detailed user story and acceptance criteria
- `tests/test_e2e_send.py`: Comprehensive integration test suite
- `docs/SEND_COMMAND_DESIGN.md`: This design document
- `pyproject.toml`: Updated with pytest configuration

## Next Steps

1. Implement the actual MCP command handler
2. Extend XMPP adapter with robust message sending
3. Add MCP protocol integration
4. Implement comprehensive error handling
5. Conduct performance testing and optimization
