# User Story: Send Message via Jabber MCP

## User Story
**As a** Warp IDE user
**When** Warp IDE issues MCP command `SEND <jid> <text>`
**Then** the project should deliver that text to the given Jabber JID

## Acceptance Criteria

1. **Message Delivery Performance**: Message must appear in recipient client within 2 seconds
2. **MCP Acknowledgment**: Bridge must send ACK (acknowledgment) over MCP for successful delivery
3. **MCP Error Handling**: Bridge must send NACK (negative acknowledgment) over MCP for failed delivery
4. **JID Validation**: System must validate the provided JID format before attempting delivery
5. **Connection Status**: System must handle cases where XMPP connection is unavailable
6. **Message Format**: Text messages should be delivered as plain text via XMPP

## Technical Requirements

- MCP command format: `SEND <jid> <text>`
- Response time: ≤ 2 seconds
- Acknowledgment mechanism: ACK/NACK over MCP protocol
- Error handling for invalid JIDs, connection failures, and delivery failures
- Integration with existing XMPP adapter functionality
