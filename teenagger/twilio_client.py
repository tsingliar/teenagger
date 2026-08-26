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

    def send_message(self, to: str, body: str, channel: str = "sms") -> str:
        """Send via RCS or SMS depending on `channel`, return the Twilio
        message SID.

        RCS is sent through a Messaging Service that has an RCS sender
        configured (Twilio auto-falls-back to SMS within that service if
        the recipient isn't RCS-capable). SMS is sent directly from
        `from_number`, unchanged from before.
        """
        if channel == "rcs":
            if not self.settings.rcs_messaging_service_sid:
                raise RuntimeError(
                    "channel = rcs is configured for this recipient, but "
                    "[twilio] rcs_messaging_service_sid is not set. Fill it "
                    "in once your RCS Messaging Service is approved, or set "
                    "channel = sms for this person in the meantime."
                )
            msg = self.client.messages.create(
                to=to, messaging_service_sid=self.settings.rcs_messaging_service_sid, body=body,
            )
            log.info("Sent RCS to %s (sid=%s): %s", to, msg.sid, body)
        else:
            msg = self.client.messages.create(
                to=to, from_=self.settings.from_number, body=body,
            )
            log.info("Sent SMS to %s (sid=%s): %s", to, msg.sid, body)
        return msg.sid

    # Kept as a thin alias -- existing call sites/tests that only ever sent
    # SMS can still call this; new code should use send_message(channel=...).
    def send_sms(self, to: str, body: str) -> str:
        return self.send_message(to, body, channel="sms")

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
