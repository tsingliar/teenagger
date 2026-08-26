"""Status text shared between `teenagger status` (CLI) and the STATUS text
keyword (any teen or the parent can text STATUS to get a summary back).
"""

from __future__ import annotations

from datetime import datetime

from .config import AppConfig
from .state import StateStore


def fmt_ago(iso_str: str | None, now: datetime) -> str:
    if not iso_str:
        return "never"
    dt = datetime.fromisoformat(iso_str)
    secs = int((now - dt).total_seconds())
    if secs < 0:
        return dt.strftime("%Y-%m-%d %H:%M")
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def full_status_lines(config: AppConfig, state: StateStore, now: datetime) -> list[str]:
    """The full, multi-line overview printed by `teenagger status`."""
    today_iso = now.date().isoformat()
    lines = [f"Teenagger status -- {now.strftime('%Y-%m-%d %H:%M')}", "", "Teens:"]

    for teen in config.teens.values():
        poll_state = state.get_teen_poll(teen.id)
        nag_state = "PAUSED" if not poll_state.nagging_enabled else "on"
        last_polled = fmt_ago(poll_state.last_polled_at, now)
        hint = "  <- background process may not be running" if poll_state.last_polled_at is None else ""
        lines.append(
            f"  {teen.name:<10} {teen.phone:<16} via {teen.channel.upper():<3} "
            f"nagging: {nag_state:<7} last polled: {last_polled}{hint}"
        )

    lines.append("")
    lines.append("Chores:")
    for chore in config.chores.values():
        teen = config.teens[chore.teen_id]
        days = ",".join(chore.days) if chore.days else "every day"
        if chore.is_due_on(now.weekday()):
            inst = state.get_or_create_instance(chore.id, today_iso)
            detail = f"status={inst.status} nags={inst.nag_count} last_nagged={fmt_ago(inst.last_nagged_at, now)}"
        else:
            detail = "not due today"
        lines.append(
            f"  [{chore.id}] \"{chore.description}\" -> {teen.name} "
            f"due {chore.due_time.strftime('%H:%M')} ({days}) | {detail}"
        )

    return lines


def compact_status_text(config: AppConfig, state: StateStore, now: datetime) -> str:
    """A shortened summary suitable for a text reply: teen pause states,
    plus only today's chores (skips 'not due today' entries and the
    last-polled health-check info, which aren't useful over text).
    """
    today_iso = now.date().isoformat()
    lines = [f"Teenagger status {now.strftime('%a %H:%M')}"]

    teen_bits = []
    for teen in config.teens.values():
        poll_state = state.get_teen_poll(teen.id)
        teen_bits.append(f"{teen.name}: {'PAUSED' if not poll_state.nagging_enabled else 'on'}")
    lines.append(" | ".join(teen_bits))

    today_chores = [c for c in config.chores.values() if c.is_due_on(now.weekday())]
    if not today_chores:
        lines.append("No chores due today.")
    else:
        lines.append("Today:")
        for chore in today_chores:
            teen = config.teens[chore.teen_id]
            inst = state.get_or_create_instance(chore.id, today_iso)
            nag_suffix = f" (x{inst.nag_count} nags)" if inst.nag_count else ""
            lines.append(
                f"- {chore.description} [{teen.name}, due {chore.due_time.strftime('%H:%M')}]: "
                f"{inst.status}{nag_suffix}"
            )

    return "\n".join(lines)
