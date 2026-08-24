"""Data classes for Teenagger's config model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass
class TwilioSettings:
    account_sid: str
    auth_token: str
    from_number: str


@dataclass
class Person:
    """A teen or a parent -- anyone with a name and a phone number."""

    id: str
    name: str
    phone: str


@dataclass
class Schedule:
    """How often, and during what hours, to send nag texts."""

    interval_minutes: int = 30
    quiet_hours_start: time = time(21, 0)
    quiet_hours_end: time = time(8, 0)
    # 0 means "nag forever until done"
    max_hours_after_due: float = 0

    def is_quiet(self, now_time: time) -> bool:
        start, end = self.quiet_hours_start, self.quiet_hours_end
        if start == end:
            return False
        if start < end:
            return start <= now_time < end
        # window wraps midnight, e.g. 21:00 -> 08:00
        return now_time >= start or now_time < end


@dataclass
class Chore:
    id: str
    description: str
    teen_id: str
    due_time: time
    notify_ids: list[str] = field(default_factory=list)
    days: list[str] | None = None  # e.g. ["mon", "thu"]; None = every day
    schedule: Schedule | None = None  # per-chore override; falls back to default

    _DAY_MAP = {
        "mon": 0, "tue": 1, "wed": 2, "thu": 3,
        "fri": 4, "sat": 5, "sun": 6,
    }

    def is_due_on(self, weekday: int) -> bool:
        """weekday: Monday=0 ... Sunday=6 (matches datetime.weekday())."""
        if not self.days:
            return True
        return weekday in {self._DAY_MAP[d] for d in self.days}


@dataclass
class AppConfig:
    twilio: TwilioSettings
    parent: Person
    default_schedule: Schedule
    teens: dict[str, Person]
    chores: dict[str, Chore]
    # everyone who can be a notify/target -- teens + parent(s), keyed by id
    people: dict[str, Person]
