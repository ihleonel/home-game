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


def remaining_seconds(disconnected_at, now, grace_seconds):
    """Whole seconds left in a reconnect window, or ``None`` once it closed.

    The window is the one ``grace_expired`` already fixes: at the deadline the
    reconnect time is over, so the value is ``None`` there and never negative.
    Between zero and one second left the value floors to ``0``, which says
    "no reconnect time left" without claiming that the seat was expelled at
    that very instant (S8). A row with no ``disconnected_at`` has nothing to
    measure from and also resolves to ``None``.
    """
    if disconnected_at is None:
        return None
    if grace_expired(disconnected_at, now, grace_seconds):
        return None
    deadline = disconnected_at + timedelta(seconds=grace_seconds)
    return max(0, int((deadline - now).total_seconds()))


def inactive_change():
    return PresenceChange((('presence', 'inactive'),), True)
