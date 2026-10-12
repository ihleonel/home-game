from contextlib import AbstractContextManager
from typing import Protocol

from ..domain.entities import ReapableParticipant


class ReapingPorts(Protocol):
    def atomic(self) -> AbstractContextManager: ...

    def now(self): ...

    def active_room_ids(self, *, room_id: int | None = None) -> tuple[int, ...]: ...

    def room_ids_with_in_progress_match(self, room_ids) -> set[int]: ...

    def reapable_participants_for_update(
        self, room_ids, *, cutoff
    ) -> tuple[ReapableParticipant, ...]: ...

    def save_reaped_changes(self, participant_id: int, changes: dict) -> None: ...

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
