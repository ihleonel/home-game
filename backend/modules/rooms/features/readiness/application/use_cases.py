from ...membership.domain.rules import SPECTATOR_ROLE
from ..domain.errors import (
    ActiveParticipantNotFound,
    ActiveRoomNotFound,
    SpectatorCannotBeReady,
)
from ..domain.rules import readiness_change
from .ports import ReadinessPorts


def set_ready_state(ports: ReadinessPorts, data):
    with ports.atomic():
        room_id = ports.active_room_for_update(session_id=data['session_id'])
        if room_id is None:
            raise ActiveRoomNotFound()
        participant = ports.active_participant_for_session_for_update(
            room_id, data['session_id']
        )
        if participant is None:
            raise ActiveParticipantNotFound()
        if participant.role == SPECTATOR_ROLE:
            # The spectator has no seat, so the requested value is irrelevant:
            # the roster and the snapshot stay exactly as they were.
            raise SpectatorCannotBeReady()

        change = readiness_change(participant.is_ready, data['is_ready'])
        requested_value = change.value if change.changed else participant.is_ready
        ports.save_readiness(participant.id, requested_value)
        response = {'room': ports.room_snapshot(room_id)}
        ports.schedule_room_event(
            room_id, 'ready_changed', ports.room_snapshot(room_id)
        )
    return response


def reset_readiness(ports: ReadinessPorts, room_id: int) -> None:
    """Return a room to its lobby when its match finishes.

    Every participant who has not left goes back to not ready, so the roster
    must re-confirm before a rematch and, above all, nobody is trapped in the
    room by the rule that a ready participant cannot leave.
    """
    with ports.atomic():
        ports.reset_room_readiness(room_id)
        ports.schedule_room_event(
            room_id, 'ready_changed', ports.room_snapshot(room_id)
        )
