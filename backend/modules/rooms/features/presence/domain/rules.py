from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class PresenceChange:
    updates: tuple[tuple[str, object], ...]
    changed: bool


def online_change(presence, disconnected_at):
    changed = presence != 'online' or disconnected_at is not None
    updates = (
        (('presence', 'online'), ('disconnected_at', None))
        if changed
        else ()
    )
    return PresenceChange(updates, changed)


def reconnecting_change(disconnected_at):
    return PresenceChange(
        (('presence', 'reconnecting'), ('disconnected_at', disconnected_at)),
        True,
    )


def grace_expired(disconnected_at, now, grace_seconds):
    return (
        disconnected_at is not None
        and now >= disconnected_at + timedelta(seconds=grace_seconds)
    )


def inactive_change():
    return PresenceChange((('presence', 'inactive'),), True)
