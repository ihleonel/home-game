"""Compatibility exports for the REST interface adapter."""

from .interfaces.rest import (
    ActiveRoomGameConflict,
    ExpulsionVoteConflict,
    _request_data,
    active_room,
    cast_expulsion_ballot,
    create_room,
    join_room,
    leave_room,
    play_room,
    start_expulsion_vote,
    update_ready_state,
)

__all__ = (
    'ActiveRoomGameConflict',
    'ExpulsionVoteConflict',
    'active_room',
    'cast_expulsion_ballot',
    'create_room',
    'join_room',
    'leave_room',
    'play_room',
    'start_expulsion_vote',
    'update_ready_state',
)
