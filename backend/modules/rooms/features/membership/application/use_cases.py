from ..domain.errors import (
    ActiveParticipantNotFound,
    ActiveRoomGameConflict,
    ActiveRoomNotFound,
    ActiveRoomSelectionRequired,
    MissingParticipantIdentity,
    ReadyParticipantCannotLeave,
    RemovedSession,
)
from ..domain.rules import (
    can_leave,
    game_matches,
    is_disconnected_presence,
    leave_changes,
    membership_change,
    missing_identity_fields,
)
from ....application.ports import VoteCancellation
from .ports import RoomMembershipPorts


def _membership_for(ports: RoomMembershipPorts, room, data, vote_cancellation):
    session_id = data.get('session_id')
    participant = None
    if session_id is not None:
        participant = ports.participant_for_session_for_update(room.id, session_id)

    if participant is not None:
        if vote_cancellation.session_was_removed(room.id, participant.id):
            raise RemovedSession()

        change = membership_change(
            was_left=participant.was_left,
            was_disconnected=is_disconnected_presence(participant.presence),
            current_display_name=participant.display_name,
            current_game_marker=participant.game_marker,
            data=data,
        )
        if change.updates:
            participant = ports.save_membership_changes(
                participant.id, dict(change.updates)
            )
        return participant, change.event_name

    missing = missing_identity_fields(data)
    if missing:
        raise MissingParticipantIdentity(missing)
    participant = ports.create_participant(
        room.id, data['display_name'], data['game_marker']
    )
    return participant, 'player_joined'


def _membership_response(ports: RoomMembershipPorts, room, participant):
    return {
        'room': ports.room_snapshot(room.id),
        'session_id': str(participant.session_id),
        'participant_ref': str(participant.public_id),
    }


def _publish_join_events(ports, room_id, event_name, cancelled_vote):
    if event_name is not None:
        ports.schedule_room_event(
            room_id, event_name, ports.room_snapshot(room_id)
        )
    if cancelled_vote is not None:
        ports.schedule_room_event(
            room_id,
            'expulsion_vote_cancelled',
            ports.room_snapshot(room_id),
            vote=cancelled_vote,
        )


def create_or_discover_room(
    ports: RoomMembershipPorts, data, vote_cancellation: VoteCancellation
):
    with ports.atomic():
        room, created = ports.create_or_lock_active_room(data['game_id'])
        if not game_matches(room.game_id, data['game_id']):
            raise ActiveRoomGameConflict()
        participant, event_name = _membership_for(
            ports, room, data, vote_cancellation
        )
        cancelled_vote = vote_cancellation.target_reconnected(
            room.id, participant.id
        )
        response = _membership_response(ports, room, participant)
        _publish_join_events(ports, room.id, event_name, cancelled_vote)
    return response, created


def join_room(ports: RoomMembershipPorts, data, vote_cancellation: VoteCancellation):
    with ports.atomic():
        room = ports.active_room_for_update(game_id=data['game_id'])
        if room is None:
            return None
        if not game_matches(room.game_id, data['game_id']):
            raise ActiveRoomGameConflict()
        participant, event_name = _membership_for(
            ports, room, data, vote_cancellation
        )
        cancelled_vote = vote_cancellation.target_reconnected(
            room.id, participant.id
        )
        response = _membership_response(ports, room, participant)
        _publish_join_events(ports, room.id, event_name, cancelled_vote)
    return response


def leave_room(
    ports: RoomMembershipPorts, data, vote_cancellation: VoteCancellation
):
    with ports.atomic():
        room = ports.active_room_for_update(session_id=data['session_id'])
        if room is None:
            raise ActiveRoomNotFound()
        participant = ports.active_participant_for_session_for_update(
            room.id, data['session_id']
        )
        if participant is None:
            raise ActiveParticipantNotFound()
        if not can_leave(participant.is_ready):
            raise ReadyParticipantCannotLeave()

        participant = ports.save_membership_changes(
            participant.id, dict(leave_changes(ports.now()))
        )
        cancelled_vote = vote_cancellation.participant_left(room.id, participant.id)
        snapshot = ports.room_snapshot(room.id)
        if not ports.has_active_participants(room.id):
            ports.delete_room(room.id)
        ports.schedule_room_event(
            room.id,
            'player_left',
            snapshot,
            departed_session_id=participant.session_id,
        )
        if cancelled_vote is not None:
            ports.schedule_room_event(
                room.id,
                'expulsion_vote_cancelled',
                snapshot,
                vote=cancelled_vote,
            )


def get_active_room(ports: RoomMembershipPorts, game_id=None, session_id=None):
    if game_id is None and session_id is None:
        snapshots = ports.get_active_room_snapshots()
        if len(snapshots) > 1:
            raise ActiveRoomSelectionRequired()
        snapshot = snapshots[0] if snapshots else None
    else:
        snapshot = ports.get_active_room_snapshot(game_id, session_id)
    if snapshot is None:
        raise ActiveRoomNotFound()
    return snapshot
