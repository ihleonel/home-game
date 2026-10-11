from contextlib import AbstractContextManager
from typing import Protocol

from ..domain.entities import ActiveRoom, ParticipantMembership


class RoomMembershipPorts(Protocol):
    def atomic(self) -> AbstractContextManager: ...

    def get_active_room_snapshot(
        self, game_id: str | None = None, session_id=None
    ) -> dict | None: ...

    def get_active_room_snapshots(self) -> list[dict]: ...

    def active_room_for_update(
        self, *, game_id: str | None = None, session_id=None
    ) -> ActiveRoom | None: ...

    def create_or_lock_active_room(self, game_id: str) -> tuple[ActiveRoom, bool]: ...

    def participant_for_session_for_update(
        self, room_id: int, session_id
    ) -> ParticipantMembership | None: ...

    def active_participant_for_session_for_update(
        self, room_id: int, session_id
    ) -> ParticipantMembership | None: ...

    def create_participant(
        self, room_id: int, display_name: str, game_marker: str
    ) -> ParticipantMembership: ...

    def save_membership_changes(
        self, participant_id: int, changes: dict
    ) -> ParticipantMembership: ...

    def room_snapshot(self, room_id: int) -> dict: ...

    def has_active_participants(self, room_id: int) -> bool: ...

    def delete_room(self, room_id: int) -> None: ...

    def schedule_room_event(
        self,
        room_id: int,
        event_name: str,
        snapshot: dict,
        *,
        departed_session_id=None,
        vote=None,
    ) -> None: ...

    def now(self): ...
