from ..domain.rules import (
    grace_expired,
    inactive_change,
    online_change,
    reconnecting_change,
)
from ....application.ports import VoteCancellation
from .ports import PresencePorts
from .results import PresenceEvent


def find_active_membership(ports: PresencePorts, session_id: str):
    return ports.active_membership(session_id)


def mark_online(
    ports: PresencePorts,
    room_id: int,
    session_id: str,
    vote_cancellation: VoteCancellation,
):
    with ports.atomic():
        if not ports.lock_active_room(room_id):
            return None
        participant = ports.active_participant_for_update(room_id, session_id)
        if participant is None:
            return None

        change = online_change(participant.presence, participant.disconnected_at)
        if change.changed:
            ports.save_presence_changes(participant.id, dict(change.updates))
        cancelled_vote = vote_cancellation.target_reconnected(
            room_id, participant.id
        )
        snapshot = ports.room_snapshot(room_id)
        events = []
        if change.changed:
            events.append(PresenceEvent('participant_online', snapshot))
        if cancelled_vote is not None:
            events.append(
                PresenceEvent('expulsion_vote_cancelled', snapshot, cancelled_vote)
            )
        return snapshot, tuple(events)


def mark_reconnecting(
    ports: PresencePorts,
    room_id: int,
    session_id: str,
    vote_cancellation: VoteCancellation,
):
    with ports.atomic():
        if not ports.lock_active_room(room_id):
            return None
        participant = ports.active_participant_for_update(room_id, session_id)
        if participant is None:
            return None

        change = reconnecting_change(ports.now())
        ports.save_presence_changes(participant.id, dict(change.updates))
        cancelled_vote = vote_cancellation.participant_disconnected(
            room_id, participant.id
        )
        snapshot = ports.room_snapshot(room_id)
        events = [PresenceEvent('participant_reconnecting', snapshot)]
        if cancelled_vote is not None:
            events.append(
                PresenceEvent('expulsion_vote_cancelled', snapshot, cancelled_vote)
            )
        return snapshot, dict(change.updates)['disconnected_at'], tuple(events)


def mark_inactive(
    ports: PresencePorts,
    room_id: int,
    session_id: str,
    disconnected_at,
    grace_seconds: int,
):
    with ports.atomic():
        if not ports.lock_active_room(room_id):
            return None
        participant = ports.reconnecting_participant_for_update(
            room_id, session_id, disconnected_at
        )
        if participant is None or not grace_expired(
            participant.disconnected_at, ports.now(), grace_seconds
        ):
            return None

        change = inactive_change()
        ports.save_presence_changes(participant.id, dict(change.updates))
        return PresenceEvent('participant_inactive', ports.room_snapshot(room_id))
