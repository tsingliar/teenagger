"""Command-line interface for Teenagger."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .config import ConfigError, load_config
from .scheduler import run_forever, run_tick
from .state import StateStore
from .twilio_client import TeenaggerTwilioClient


def cmd_validate(args) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(config.teens)} teen(s), {len(config.chores)} chore(s) configured.")
    for chore in config.chores.values():
        teen = config.teens[chore.teen_id]
        days = ",".join(chore.days) if chore.days else "every day"
        print(f"  - [{chore.id}] \"{chore.description}\" -> {teen.name} @ {chore.due_time.strftime('%H:%M')} ({days})")
    return 0


def cmd_list(args) -> int:
    config = load_config(args.config)
    state = StateStore.load(args.state)
    today_iso = datetime.now().date().isoformat()
    print(f"Chores for {today_iso}:")
    for chore in config.chores.values():
        if not chore.is_due_on(datetime.now().weekday()):
            continue
        teen = config.teens[chore.teen_id]
        inst = state.get_or_create_instance(chore.id, today_iso)
        print(
            f"  [{chore.id}] \"{chore.description}\" -> {teen.name} "
            f"due {chore.due_time.strftime('%H:%M')} | status={inst.status} "
            f"| nags sent={inst.nag_count} | last_nagged={inst.last_nagged_at or '-'}"
        )
    state.save()
    return 0


def cmd_done(args) -> int:
    config = load_config(args.config)
    state = StateStore.load(args.state)
    if args.chore_id not in config.chores:
        print(f"Unknown chore id '{args.chore_id}'. Known: {sorted(config.chores)}", file=sys.stderr)
        return 1
    today_iso = datetime.now().date().isoformat()
    inst = state.get_or_create_instance(args.chore_id, today_iso)
    inst.status = "done"
    inst.done_at = datetime.now().isoformat()
    state.save()
    print(f"Marked '{args.chore_id}' done for {today_iso}.")

    if not args.silent:
        chore = config.chores[args.chore_id]
        twilio = TeenaggerTwilioClient(config.twilio)
        for notify_id in chore.notify_ids:
            person = config.people[notify_id]
            twilio.send_sms(
                person.phone,
                f"(Manually marked) \"{chore.description}\" is done.",
            )
    return 0


def cmd_test_sms(args) -> int:
    config = load_config(args.config)
    if args.to not in config.people:
        print(f"Unknown id '{args.to}'. Known: {sorted(config.people)}", file=sys.stderr)
        return 1
    person = config.people[args.to]
    twilio = TeenaggerTwilioClient(config.twilio)
    sid = twilio.send_sms(person.phone, "Test message from Teenagger. If you got this, Twilio is wired up correctly.")
    print(f"Sent test SMS to {person.name} ({person.phone}); Twilio SID={sid}")
    return 0


def cmd_run(args) -> int:
    if args.once:
        config = load_config(args.config)
        twilio = TeenaggerTwilioClient(config.twilio)
        state = StateStore.load(args.state)
        run_tick(config, state, twilio)
        print("Ran a single tick.")
        return 0
    run_forever(args.config, args.state, tick_seconds=args.tick_seconds)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teenagger", description="Nag your teenager until the chore is done.")
    parser.add_argument("--config", default=None, help="Path to teenagger.conf (default: config/teenagger.conf)")
    parser.add_argument("--state", default=None, help="Path to state JSON file (default: state/teenagger_state.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="Check the config file for errors")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("list", help="Show today's chores and their status")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("done", help="Manually mark a chore done (and notify)")
    p.add_argument("chore_id")
    p.add_argument("--silent", action="store_true", help="Don't send the parent notification")
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("test-sms", help="Send a test text to a configured person")
    p.add_argument("to", help="id of a teen (e.g. 'alex') or 'parent'")
    p.set_defaults(func=cmd_test_sms)

    p = sub.add_parser("run", help="Run the nagging loop (foreground; launchd runs this)")
    p.add_argument("--once", action="store_true", help="Run a single tick and exit, instead of looping forever")
    p.add_argument("--tick-seconds", type=int, default=60, help="Seconds between ticks (default 60)")
    p.set_defaults(func=cmd_run)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
