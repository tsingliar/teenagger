"""Thin wrapper around the Twilio REST API for sending nags and polling replies."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from twilio.rest import Client

from .models import TwilioSettings

log = logging.getLogger("teenagger.twilio")


class TeenaggerTwilioClient:
    def __init__(self, settings: TwilioSettings):
        self.settings = settings
        self.client = Client(settings.account_sid, settings.auth_token)

    def send_sms(self, to: str, body: str) -> str:
        """Send an SMS, return the Twilio message SID."""
        msg = self.client.messages.create(
            to=to, from_=self.settings.from_number, body=body,
        )
        log.info("Sent SMS to %s (sid=%s): %s", to, msg.sid, body)
        return msg.sid

    def fetch_new_inbound_from(self, phone_number: str, since_minutes: int = 60):
        """Return inbound messages sent TO our Twilio number FROM phone_number,
        newest first, within the last `since_minutes` minutes.
        """
        after = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        messages = self.client.messages.list(
            to=self.settings.from_number,
            from_=phone_number,
            date_sent_after=after,
        )
        # Twilio returns newest-first by default; be explicit anyway.
        messages.sort(key=lambda m: m.date_sent or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return messages
