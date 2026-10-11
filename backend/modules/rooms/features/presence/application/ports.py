from contextlib import AbstractContextManager
from typing import Protocol

from ..domain.entities import PresenceParticipant


class PresencePorts(Protocol):
    def active_membership(self, session_id: str): ...

    def atomic(self) -> AbstractContextManager: ...

    def lock_active_room(self, room_id: int) -> bool: ...

    def active_participant_for_update(
        self, room_id: int, session_id: str
    ) -> PresenceParticipant | None: ...

    def reconnecting_participant_for_update(
        self, room_id: int, session_id: str, disconnected_at
    ) -> PresenceParticipant | None: ...

    def save_presence_changes(self, participant_id: int, changes: dict) -> None: ...

    def now(self): ...

    def cancel_vote_for_target(self, room_id: int, participant_id: int, reason: str): ...

    def cancel_vote_for_participant(
        self,
        room_id: int,
        participant_id: int,
        target_reason: str,
        voter_reason: str,
    ): ...

    def room_snapshot(self, room_id: int) -> dict: ...
