"""The nagging engine: decide who to text, when, and process 'done' replies."""

from __future__ import annotations

import logging
import time as time_module
from datetime import datetime, timedelta

from .config import AppConfig, load_config
from .models import Chore
from .state import StateStore
from .twilio_client import TeenaggerTwilioClient

log = logging.getLogger("teenagger.scheduler")

DONE_KEYWORDS = {"done", "did it", "finished", "complete", "completed"}


def _is_done_reply(body: str) -> bool:
    text = body.strip().lower()
    return text in DONE_KEYWORDS or text.startswith("done")


def chores_for_teen(config: AppConfig, teen_id: str) -> list[str]:
    return [c.id for c in config.chores.values() if c.teen_id == teen_id]


def run_tick(config: AppConfig, state: StateStore, twilio: TeenaggerTwilioClient, now: datetime | None = None) -> None:
    """One pass: send any due nags, then check for 'done' replies. Idempotent-ish;
    safe to call repeatedly (e.g. once a minute from the background loop).
    """
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

        schedule = _effective_schedule(config, chore)
        due_dt = datetime.combine(now.date(), chore.due_time)

        if now < due_dt:
            continue  # not due yet today

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
            twilio.send_sms(teen.phone, body)
            inst.last_nagged_at = now.isoformat()
            inst.nag_count += 1


def _process_replies(config, state, twilio, now, today_iso) -> None:
    for teen in config.teens.values():
        poll_state = state.get_teen_poll(teen.id)
        messages = twilio.fetch_new_inbound_from(teen.phone, since_minutes=180)
        if not messages:
            continue

        # Only look at messages newer than the last one we've already handled.
        new_messages = []
        for m in messages:
            if poll_state.last_seen_sid and m.sid == poll_state.last_seen_sid:
                break
            new_messages.append(m)

        if not new_messages:
            continue

        # Remember the newest SID we've seen regardless of whether it said "done".
        poll_state.last_seen_sid = messages[0].sid

        done_reply = next((m for m in new_messages if _is_done_reply(m.body or "")), None)
        if not done_reply:
            continue

        chore_ids = chores_for_teen(config, teen.id)
        inst = state.find_latest_pending_for_teen(chore_ids, today_iso)
        if not inst:
            log.info("Got 'done' from %s but no pending chore found -- ignoring", teen.name)
            continue

        inst.status = "done"
        inst.done_at = now.isoformat()
        chore = config.chores[inst.chore_id]
        log.info("Marked '%s' done for %s", chore.id, teen.name)

        for notify_id in chore.notify_ids:
            person = config.people[notify_id]
            twilio.send_sms(
                person.phone,
                f"{teen.name} says \"{chore.description}\" is done. "
                f"(You may want to go check!)",
            )


def run_forever(config_path=None, state_path=None, tick_seconds: int = 60) -> None:
    """Foreground loop -- what the launchd agent actually executes."""
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
            # Reload config each tick so edits take effect without a restart.
            config = load_config(config_path)
            run_tick(config, state, twilio)
        except Exception:
            log.exception("Error during tick -- will retry next tick")
        time_module.sleep(tick_seconds)
