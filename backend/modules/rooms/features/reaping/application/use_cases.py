"""Reap memberships and rooms that nobody is coming back to.

Staleness is decided from the persisted ``presence`` and ``disconnected_at``
columns rather than from the in-process connection registry, so this sweep is
correct from any process and survives a restart. Two rules carry the weight:

- a room holding an in-progress match is skipped entirely, because its seats
  belong to players who may still reconnect into the running match;
- the reaped membership clears ``is_ready`` as well as setting ``left_at``,
  because ``participant_for_session_for_update`` resolves left rows too and the
  rejoin path would otherwise revive a ready ghost.

Deleting an emptied room takes that room's matches with it (``Match.room`` is
CASCADE), which is the accepted cost of having no soft-close state: ``Room``
only allows ``status='active'``.
"""

from ....application.ports import VoteCancellation
from ..domain.entities import ReapOutcome
from ..domain.rules import is_stale, reap_changes, staleness_cutoff
from .ports import ReapingPorts


def _reapable_by_room(participants):
    grouped = {}
    for participant in sorted(participants, key=lambda item: item.id):
        grouped.setdefault(participant.room_id, []).append(participant)
    return grouped


def reap_ghost_memberships(
    ports: ReapingPorts,
    vote_cancellation: VoteCancellation,
    *,
    grace_seconds: int,
    room_id: int | None = None,
) -> ReapOutcome:
    with ports.atomic():
        room_ids = ports.active_room_ids(room_id=room_id)
        if not room_ids:
            return ReapOutcome(0, 0, 0)
        busy = ports.room_ids_with_in_progress_match(room_ids)
        candidate_rooms = tuple(
            room for room in sorted(room_ids) if room not in busy
        )
        if not candidate_rooms:
            return ReapOutcome(0, 0, 0)

        now = ports.now()
        cutoff = staleness_cutoff(now, grace_seconds)
        reapable = tuple(
            participant
            for participant in ports.reapable_participants_for_update(
                candidate_rooms, cutoff=cutoff
            )
            if is_stale(participant.presence, participant.disconnected_at, cutoff)
        )

        rooms_reaped = 0
        participants_removed = 0
        rooms_deleted = 0
        grouped = _reapable_by_room(reapable)
        for target_room in sorted(grouped):
            for participant in grouped[target_room]:
                ports.save_reaped_changes(
                    participant.id, dict(reap_changes(now))
                )
                cancelled_vote = vote_cancellation.participant_left(
                    target_room, participant.id
                )
                snapshot = ports.room_snapshot(target_room)
                ports.schedule_room_event(
                    target_room,
                    'player_left',
                    snapshot,
                    departed_session_id=participant.session_id,
                )
                if cancelled_vote is not None:
                    ports.schedule_room_event(
                        target_room,
                        'expulsion_vote_cancelled',
                        snapshot,
                        vote=cancelled_vote,
                    )
                participants_removed += 1
            rooms_reaped += 1
            if not ports.has_active_participants(target_room):
                ports.delete_room(target_room)
                rooms_deleted += 1
    return ReapOutcome(rooms_reaped, participants_removed, rooms_deleted)
