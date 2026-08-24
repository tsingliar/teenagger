"""Parse the Linux-style INI config file into an AppConfig."""

from __future__ import annotations

import configparser
from datetime import time
from pathlib import Path

from .models import AppConfig, Chore, Person, Schedule, TwilioSettings


class ConfigError(ValueError):
    """Raised when the config file is missing required data or malformed."""


def _parse_time(value: str, *, section: str, key: str) -> time:
    value = value.strip()
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, IndexError):
        raise ConfigError(
            f"[{section}] {key} = '{value}' is not a valid HH:MM time"
        ) from None


def _parse_days(value: str, *, section: str) -> list[str]:
    valid = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    days = [d.strip().lower() for d in value.split(",") if d.strip()]
    bad = [d for d in days if d not in valid]
    if bad:
        raise ConfigError(
            f"[{section}] days contains invalid value(s) {bad}; "
            f"use any of {sorted(valid)}"
        )
    return days


def _parse_ids(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "teenagger.conf"


def load_config(path: str | Path | None = None) -> AppConfig:
    path = Path(path) if path else default_config_path()
    if not path.exists():
        raise ConfigError(
            f"Config file not found at {path}.\n"
            f"Copy config/teenagger.conf.example to config/teenagger.conf "
            f"and fill in your details, or pass --config /path/to/file."
        )

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")

    # ---- [twilio] ----
    if "twilio" not in parser:
        raise ConfigError("Missing required [twilio] section")
    tw = parser["twilio"]
    for req in ("account_sid", "auth_token", "from_number"):
        if not tw.get(req, "").strip() or tw.get(req, "").startswith("your_") or "XXXX" in tw.get(req, ""):
            raise ConfigError(
                f"[twilio] {req} looks unset -- fill in your real Twilio "
                f"credentials in the config file."
            )
    twilio_settings = TwilioSettings(
        account_sid=tw["account_sid"].strip(),
        auth_token=tw["auth_token"].strip(),
        from_number=tw["from_number"].strip(),
    )

    # ---- [parent] ----
    if "parent" not in parser:
        raise ConfigError("Missing required [parent] section")
    pr = parser["parent"]
    if not pr.get("phone", "").strip():
        raise ConfigError("[parent] phone is required")
    parent = Person(id="parent", name=pr.get("name", "Parent").strip(), phone=pr["phone"].strip())

    # ---- [schedule.default] ----
    sched_section = parser["schedule.default"] if "schedule.default" in parser else {}
    default_schedule = Schedule(
        interval_minutes=int(sched_section.get("interval_minutes", 30)),
        quiet_hours_start=_parse_time(
            sched_section.get("quiet_hours_start", "21:00"),
            section="schedule.default", key="quiet_hours_start",
        ),
        quiet_hours_end=_parse_time(
            sched_section.get("quiet_hours_end", "08:00"),
            section="schedule.default", key="quiet_hours_end",
        ),
        max_hours_after_due=float(sched_section.get("max_hours_after_due", 0)),
    )

    # ---- [teen.*] ----
    teens: dict[str, Person] = {}
    for section_name in parser.sections():
        if not section_name.startswith("teen."):
            continue
        teen_id = section_name.split(".", 1)[1].strip()
        sec = parser[section_name]
        if not sec.get("phone", "").strip():
            raise ConfigError(f"[{section_name}] phone is required")
        teens[teen_id] = Person(
            id=teen_id,
            name=sec.get("name", teen_id).strip(),
            phone=sec["phone"].strip(),
        )
    if not teens:
        raise ConfigError("No [teen.*] sections found -- add at least one teenager")

    people: dict[str, Person] = {**teens, "parent": parent}

    # ---- [chore.*] ----
    chores: dict[str, Chore] = {}
    for section_name in parser.sections():
        if not section_name.startswith("chore."):
            continue
        chore_id = section_name.split(".", 1)[1].strip()
        sec = parser[section_name]

        description = sec.get("description", "").strip()
        if not description:
            raise ConfigError(f"[{section_name}] description is required")

        teen_id = sec.get("teen", "").strip()
        if teen_id not in teens:
            raise ConfigError(
                f"[{section_name}] teen = '{teen_id}' does not match any "
                f"[teen.*] section (known teens: {sorted(teens)})"
            )

        due_time = _parse_time(sec.get("due_time", ""), section=section_name, key="due_time")

        days = _parse_days(sec["days"], section=section_name) if sec.get("days") else None

        notify_raw = sec.get("notify", "parent")
        notify_ids = _parse_ids(notify_raw) or ["parent"]
        unknown = [n for n in notify_ids if n not in people]
        if unknown:
            raise ConfigError(
                f"[{section_name}] notify references unknown id(s) {unknown} "
                f"(known: {sorted(people)})"
            )

        chore_schedule = None
        if "interval_minutes" in sec or "quiet_hours_start" in sec or "quiet_hours_end" in sec or "max_hours_after_due" in sec:
            chore_schedule = Schedule(
                interval_minutes=int(sec.get("interval_minutes", default_schedule.interval_minutes)),
                quiet_hours_start=_parse_time(
                    sec.get("quiet_hours_start", default_schedule.quiet_hours_start.strftime("%H:%M")),
                    section=section_name, key="quiet_hours_start",
                ),
                quiet_hours_end=_parse_time(
                    sec.get("quiet_hours_end", default_schedule.quiet_hours_end.strftime("%H:%M")),
                    section=section_name, key="quiet_hours_end",
                ),
                max_hours_after_due=float(sec.get("max_hours_after_due", default_schedule.max_hours_after_due)),
            )

        chores[chore_id] = Chore(
            id=chore_id,
            description=description,
            teen_id=teen_id,
            due_time=due_time,
            notify_ids=notify_ids,
            days=days,
            schedule=chore_schedule,
        )

    if not chores:
        raise ConfigError("No [chore.*] sections found -- add at least one chore")

    return AppConfig(
        twilio=twilio_settings,
        parent=parent,
        default_schedule=default_schedule,
        teens=teens,
        chores=chores,
        people=people,
    )
