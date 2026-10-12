from contextlib import AbstractContextManager
from typing import Protocol

from ..domain.entities import ReadinessParticipant


class ReadinessPorts(Protocol):
    def atomic(self) -> AbstractContextManager: ...

    def active_room_for_update(self, *, session_id) -> int | None: ...

    def active_participant_for_session_for_update(
        self, room_id: int, session_id
    ) -> ReadinessParticipant | None: ...

    def save_readiness(self, participant_id: int, is_ready: bool) -> None: ...

    def reset_room_readiness(self, room_id: int) -> None:
        """Set every participant of ``room_id`` who has not left to not ready."""
        ...

    def room_snapshot(self, room_id: int) -> dict: ...

    def schedule_room_event(
        self, room_id: int, event_name: str, snapshot: dict
    ) -> None: ...
