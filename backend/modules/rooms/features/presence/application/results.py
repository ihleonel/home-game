from dataclasses import dataclass


@dataclass(frozen=True)
class PresenceEvent:
    name: str
    snapshot: dict
    vote: dict | None = None
