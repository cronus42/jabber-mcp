import asyncio
import logging
from typing import Any, Dict

import slixmpp
from slixmpp import JID
from slixmpp.xmlstream import ElementBase


class XmppAdapter(slixmpp.ClientXMPP):
    def __init__(self, jid: str, password: str):
        super().__init__(jid, password)
        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("message", self.message_received)

    async def session_start(self, _event: Dict[str, Any]) -> None:
        """Handle session start event."""
        self.send_presence()
        await self.get_roster()

    def message_received(self, msg: ElementBase):
        if msg["type"] in ("chat", "normal"):
            logging.debug(f"Message received from {msg['from']}: {msg['body']}")
            task = asyncio.create_task(self.process_message(msg))
            # Store task reference to prevent it from being garbage collected
            task.add_done_callback(lambda _: None)

    async def process_message(self, msg: ElementBase):
        # TODO: Implement message processing logic
        logging.info(f"Processing message from {msg['from']}: {msg['body']}")

    async def normalize_format(self, content: str) -> str:
        # Placeholder for normalization logic
        normalized_content = content.strip()
        logging.debug(f"Normalized content: {normalized_content}")
        return normalized_content

    async def send_message_to_jid(self, to_jid: str, content: str):
        normalized_content = await self.normalize_format(content)
        self.send_message(mto=JID(to_jid), mbody=normalized_content, mtype="chat")
        logging.info(f"Sent message to {to_jid}: {normalized_content}")
