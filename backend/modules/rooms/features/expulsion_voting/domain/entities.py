from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class VoteParticipant:
    id: int
    public_id: UUID
    session_id: UUID
    display_name: str
    presence: str
    was_left: bool
    disconnected_at: datetime | None


@dataclass(frozen=True)
class VoteRecord:
    id: int
    public_id: UUID
    status: str
    target_id: int
    initiated_by_id: int


@dataclass(frozen=True)
class BallotRecord:
    id: int
    choice: str | None


@dataclass(frozen=True)
class VoteResolution:
    status: str
    reason: str
    event_name: str
    remove_target: bool = False
