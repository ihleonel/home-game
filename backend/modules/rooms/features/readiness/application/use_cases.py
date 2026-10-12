from ..domain.errors import ActiveParticipantNotFound, ActiveRoomNotFound
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

        change = readiness_change(participant.is_ready, data['is_ready'])
        requested_value = change.value if change.changed else participant.is_ready
        ports.save_readiness(participant.id, requested_value)
        response = {'room': ports.room_snapshot(room_id)}
        ports.schedule_room_event(
            room_id, 'ready_changed', ports.room_snapshot(room_id)
        )
    return response
