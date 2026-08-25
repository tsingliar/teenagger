"""Local runtime state: which chore-instances are pending/done, and nag history."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


def default_state_path() -> Path:
    return Path(__file__).resolve().parent.parent / "state" / "teenagger_state.json"


@dataclass
class ChoreInstanceState:
    chore_id: str
    date: str
    status: str = "pending"
    last_nagged_at: str | None = None
    nag_count: int = 0
    done_at: str | None = None


@dataclass
class TeenPollState:
    last_seen_sid: str | None = None
    nagging_enabled: bool = True
    # ISO timestamp of the last time we actually asked Twilio for this
    # teen's inbound messages -- lets `teenagger status` show whether the
    # background loop is alive, independent of whether anything was found.
    last_polled_at: str | None = None


@dataclass
class StateStore:
    path: Path
    instances: dict[str, ChoreInstanceState] = field(default_factory=dict)
    teen_poll: dict[str, TeenPollState] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "StateStore":
        path = Path(path) if path else default_state_path()
        store = cls(path=path)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            store.instances = {
                k: ChoreInstanceState(**v) for k, v in raw.get("instances", {}).items()
            }
            store.teen_poll = {
                k: TeenPollState(**v) for k, v in raw.get("teen_poll", {}).items()
            }
        return store

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "instances": {k: asdict(v) for k, v in self.instances.items()},
            "teen_poll": {k: asdict(v) for k, v in self.teen_poll.items()},
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def instance_key(self, chore_id: str, date_iso: str) -> str:
        return f"{chore_id}:{date_iso}"

    def get_or_create_instance(self, chore_id: str, date_iso: str) -> ChoreInstanceState:
        key = self.instance_key(chore_id, date_iso)
        if key not in self.instances:
            self.instances[key] = ChoreInstanceState(chore_id=chore_id, date=date_iso)
        return self.instances[key]

    def find_latest_pending_for_teen(self, chore_ids_for_teen: list[str], today_iso: str) -> ChoreInstanceState | None:
        candidates = [
            inst for key, inst in self.instances.items()
            if inst.chore_id in chore_ids_for_teen and inst.status == "pending"
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda i: i.date, reverse=True)
        return candidates[0]

    def get_teen_poll(self, teen_id: str) -> TeenPollState:
        if teen_id not in self.teen_poll:
            self.teen_poll[teen_id] = TeenPollState()
        return self.teen_poll[teen_id]
