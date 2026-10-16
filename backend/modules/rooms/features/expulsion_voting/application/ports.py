from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from ..domain.entities import BallotRecord, VoteParticipant, VoteRecord


class ExpulsionVotingPorts(Protocol):
    def atomic(self) -> AbstractContextManager: ...

    def active_room_for_session_for_update(self, session_id: UUID) -> int | None: ...

    def room_for_vote_for_update(self, vote_ref: UUID) -> int | None: ...

    def participant_for_session_for_update(
        self, room_id: int, session_id: UUID
    ) -> VoteParticipant | None: ...

    def participant_for_public_ref_for_update(
        self, room_id: int, participant_ref: UUID
    ) -> VoteParticipant | None: ...

    def participant_by_id_for_update(
        self, participant_id: int
    ) -> VoteParticipant: ...

    def has_connection(self, room_id: int, session_id: str) -> bool: ...

    def online_active_participants_for_update(
        self, room_id: int
    ) -> list[VoteParticipant]: ...

    def pending_vote_for_update(self, room_id: int) -> VoteRecord | None: ...

    def pending_vote_target_ids_for_update(self, room_id: int) -> tuple[int, ...]: ...

    def connected_voter_ids_for_update(self, room_id: int) -> tuple[int, ...]: ...

    def absence_is_spent_for_update(
        self, room_id: int, participant_id: int, disconnected_at
    ) -> bool: ...

    def pending_vote_for_target_for_update(
        self, room_id: int, target_id: int
    ) -> VoteRecord | None: ...

    def pending_vote_for_room_for_update(self, room_id: int) -> VoteRecord | None: ...

    def participant_has_ballot(self, vote_id: int, participant_id: int) -> bool: ...

    def session_was_removed(self, room_id: int, participant_id: int) -> bool: ...

    def create_vote(
        self,
        room_id: int,
        target_ids: tuple[int, ...],
        *,
        caller_id: int | None = None,
        origin: str = 'automatic',
    ) -> VoteRecord: ...

    def create_ballots(self, vote_id: int, voter_ids: tuple[int, ...]) -> None: ...

    def vote_for_public_ref_for_update(
        self, room_id: int, vote_ref: UUID
    ) -> VoteRecord | None: ...

    def ballot_for_voter_for_update(
        self, vote_id: int, voter_id: int
    ) -> BallotRecord | None: ...

    def mark_target_inactive(self, participant_id: int) -> None: ...

    def save_ballot(self, ballot_id: int, choice: str, cast_at) -> None: ...

    def ballot_counts(self, vote_id: int) -> tuple[int, int, int]: ...

    def remove_target(self, participant_id: int, left_at) -> None: ...

    def save_vote_resolution(
        self, vote_id: int, status: str, reason: str, resolved_at
    ) -> None: ...

    def vote_snapshot(self, vote_id: int) -> dict: ...

    def room_snapshot(self, room_id: int) -> dict: ...

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
