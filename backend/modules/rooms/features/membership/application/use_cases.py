from ..domain.errors import (
    ActiveParticipantNotFound,
    ActiveRoomGameConflict,
    ActiveRoomNotFound,
    ActiveRoomSelectionRequired,
    MatchAlreadyStarted,
    MissingParticipantIdentity,
    NoFreeSeat,
    ReadyParticipantCannotLeave,
    RemovedSession,
)
from ..domain.rules import (
    PLAYER_ROLE,
    SPECTATOR_ROLE,
    can_leave,
    can_take_player_seat,
    game_matches,
    is_disconnected_presence,
    leave_changes,
    membership_change,
    missing_identity_fields,
    resolve_entry_role,
    resolve_returning_role,
)
from ....application.ports import GhostReaping, VoteCancellation
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
        updates = dict(change.updates)
        if participant.was_left:
            # A row that comes back is not a fresh arrival: its seat was
            # released when it left, so it is re-admitted by the same policy
            # that admits a new session. Otherwise a player returning after
            # its seat was given to a promoted spectator would leave the room
            # holding more players than the game accepts.
            role = resolve_returning_role(
                current_role=participant.role,
                as_spectator=bool(data.get('as_spectator', False)),
                match_in_progress=ports.has_in_progress_match(room.id),
                active_players=ports.count_active_players(room.id),
                max_seats=ports.game_max_seats(room.game_id),
            )
            if role != participant.role:
                updates['role'] = role
        if updates:
            participant = ports.save_membership_changes(participant.id, updates)
        return participant, change.event_name

    missing = missing_identity_fields(data)
    if missing:
        raise MissingParticipantIdentity(missing)
    role = resolve_entry_role(
        as_spectator=bool(data.get('as_spectator', False)),
        match_in_progress=ports.has_in_progress_match(room.id),
        active_players=ports.count_active_players(room.id),
        max_seats=ports.game_max_seats(room.game_id),
    )
    participant = ports.create_participant(
        room.id, data['display_name'], data['game_marker'], role
    )
    event_name = (
        'spectator_joined' if role == SPECTATOR_ROLE else 'player_joined'
    )
    return participant, event_name


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
    ports: RoomMembershipPorts,
    data,
    vote_cancellation: VoteCancellation,
    reaping: GhostReaping,
):
    with ports.atomic():
        # Reaping happens before the room is locked or created: reaping an
        # emptied room deletes its row, so resolving the room first would lock
        # and then delete the very row this transaction goes on to use.
        reaping.reap()
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


def join_room(
    ports: RoomMembershipPorts,
    data,
    vote_cancellation: VoteCancellation,
    reaping: GhostReaping,
):
    with ports.atomic():
        # Reaping happens before the room is resolved for the same reason as in
        # create_or_discover_room: the reap may delete the ghost room, and doing
        # it first gives the joining player a clean room instead of a revived
        # ghost one.
        reaping.reap()
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


def play_room(ports: RoomMembershipPorts, data):
    """S5: promote a requesting spectator to player when the lobby allows it.

    The room and the participant are locked in one unit of work so the seat
    count cannot change between the decision and the role write. A player who
    calls the endpoint is idempotent: the snapshot is returned unchanged and no
    event is published.
    """
    session_id = data['session_id']
    with ports.atomic():
        room = ports.active_room_for_update(session_id=session_id)
        if room is None:
            raise ActiveRoomNotFound()
        participant = ports.active_participant_for_session_for_update(
            room.id, session_id
        )
        if participant is None:
            raise ActiveParticipantNotFound()
        if participant.role == PLAYER_ROLE:
            return {'room': ports.room_snapshot(room.id)}

        match_in_progress = ports.has_in_progress_match(room.id)
        active_players = ports.count_active_players(room.id)
        max_seats = ports.game_max_seats(room.game_id)
        if not can_take_player_seat(
            role=participant.role,
            match_in_progress=match_in_progress,
            active_players=active_players,
            max_seats=max_seats,
        ):
            if match_in_progress:
                raise MatchAlreadyStarted()
            raise NoFreeSeat()

        ports.set_participant_role(participant.id, PLAYER_ROLE)
        snapshot = ports.room_snapshot(room.id)
        ports.schedule_room_event(room.id, 'player_promoted', snapshot)
    return {'room': snapshot}


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
