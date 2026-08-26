"""The nagging engine: decide who to text, when, and process replies
(DONE, plus the standard SMS opt-out keywords STOP/START/HELP)."""

from __future__ import annotations

import logging
import re
import time as time_module
from datetime import datetime, timedelta

from .config import AppConfig, load_config
from .models import Chore
from .state import StateStore
from .twilio_client import TeenaggerTwilioClient

log = logging.getLogger("teenagger.scheduler")

DONE_KEYWORDS = {"done", "did it", "finished", "complete", "completed"}

STOP_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
START_KEYWORDS = {"start", "unstop"}
HELP_KEYWORDS = {"help", "info"}

HELP_REPLY_TEXT = "Talk to your parent about chores. Text STOP if you want to stop the messages."


def _normalize(body: str) -> str:
    return re.sub(r"[^\w\s]", "", (body or "").strip().lower())


def _is_done_reply(body: str) -> bool:
    text = body.strip().lower()
    return text in DONE_KEYWORDS or text.startswith("done")


def chores_for_teen(config: AppConfig, teen_id: str) -> list[str]:
    return [c.id for c in config.chores.values() if c.teen_id == teen_id]


def run_tick(config: AppConfig, state: StateStore, twilio: TeenaggerTwilioClient, now: datetime | None = None) -> None:
    now = now or datetime.now()
    today_iso = now.date().isoformat()

    _send_due_nags(config, state, twilio, now, today_iso)
    _process_replies(config, state, twilio, now, today_iso)

    state.save()


def _effective_schedule(config: AppConfig, chore: Chore):
    return chore.schedule or config.default_schedule


def _send_due_nags(config, state, twilio, now, today_iso) -> None:
    for chore in config.chores.values():
        if not chore.is_due_on(now.weekday()):
            continue

        inst = state.get_or_create_instance(chore.id, today_iso)
        if inst.status != "pending":
            continue

        if not state.get_teen_poll(chore.teen_id).nagging_enabled:
            continue

        schedule = _effective_schedule(config, chore)
        due_dt = datetime.combine(now.date(), chore.due_time)

        if now < due_dt:
            continue

        if schedule.max_hours_after_due and now > due_dt + timedelta(hours=schedule.max_hours_after_due):
            if inst.status == "pending":
                inst.status = "expired"
                log.info("Chore '%s' expired for %s (past max_hours_after_due)", chore.id, today_iso)
            continue

        if schedule.is_quiet(now.time()):
            continue

        should_nag = inst.last_nagged_at is None
        if not should_nag:
            last = datetime.fromisoformat(inst.last_nagged_at)
            should_nag = (now - last) >= timedelta(minutes=schedule.interval_minutes)

        if should_nag:
            teen = config.teens[chore.teen_id]
            body = (
                f"Hey {teen.name}, this is your reminder: \"{chore.description}\" "
                f"was due at {chore.due_time.strftime('%H:%M')}. "
                f"Reply DONE when it's finished."
            )
            twilio.send_message(teen.phone, body, channel=teen.channel)
            inst.last_nagged_at = now.isoformat()
            inst.nag_count += 1


def _process_replies(config, state, twilio, now, today_iso) -> None:
    for teen in config.teens.values():
        poll_state = state.get_teen_poll(teen.id)
        # Record that a poll attempt happened even if nothing new came back --
        # this is what lets `teenagger status` show whether the background
        # process is actually alive and checking Twilio.
        poll_state.last_polled_at = now.isoformat()

        messages = twilio.fetch_new_inbound_from(teen.phone, since_minutes=180)
        if not messages:
            continue

        new_messages = []
        for m in messages:
            if poll_state.last_seen_sid and m.sid == poll_state.last_seen_sid:
                break
            new_messages.append(m)

        if not new_messages:
            continue

        poll_state.last_seen_sid = messages[0].sid

        for message in reversed(new_messages):
            _handle_inbound_message(config, state, twilio, teen, message, now, today_iso)


def _handle_inbound_message(config, state, twilio, teen, message, now, today_iso) -> None:
    body = message.body or ""
    keyword = _normalize(body)
    poll_state = state.get_teen_poll(teen.id)

    if keyword in STOP_KEYWORDS:
        poll_state.nagging_enabled = False
        log.info("%s replied STOP -- pausing nags for them", teen.name)
        twilio.send_message(
            config.parent.phone,
            f"{teen.name} replied STOP -- I've paused chore reminders for "
            f"them. They (or you) can text START to this number to resume.",
            channel=config.parent.channel,
        )
        return

    if keyword in START_KEYWORDS:
        poll_state.nagging_enabled = True
        log.info("%s replied START -- resuming nags for them", teen.name)
        twilio.send_message(
            config.parent.phone,
            f"{teen.name} replied START -- chore reminders have resumed "
            f"for them.",
            channel=config.parent.channel,
        )
        return

    if keyword in HELP_KEYWORDS:
        log.info("%s replied HELP", teen.name)
        twilio.send_message(teen.phone, HELP_REPLY_TEXT, channel=teen.channel)
        return

    if _is_done_reply(body):
        chore_ids = chores_for_teen(config, teen.id)
        inst = state.find_latest_pending_for_teen(chore_ids, today_iso)
        if not inst:
            log.info("Got 'done' from %s but no pending chore found -- ignoring", teen.name)
            return

        inst.status = "done"
        inst.done_at = now.isoformat()
        chore = config.chores[inst.chore_id]
        log.info("Marked '%s' done for %s", chore.id, teen.name)

        for notify_id in chore.notify_ids:
            person = config.people[notify_id]
            twilio.send_message(
                person.phone,
                f"{teen.name} says \"{chore.description}\" is done. "
                f"(You may want to go check!)",
                channel=person.channel,
            )


def run_forever(config_path=None, state_path=None, tick_seconds: int = 60) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("Teenagger starting (tick every %ss)", tick_seconds)

    config = load_config(config_path)
    twilio = TeenaggerTwilioClient(config.twilio)
    state = StateStore.load(state_path)

    while True:
        try:
            config = load_config(config_path)
            run_tick(config, state, twilio)
        except Exception:
            log.exception("Error during tick -- will retry next tick")
        time_module.sleep(tick_seconds)
