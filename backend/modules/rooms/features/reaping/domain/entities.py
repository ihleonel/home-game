from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReapableParticipant:
    id: int
    room_id: int
    session_id: object
    presence: str
    disconnected_at: datetime | None
    updated_at: datetime | None
    # The sweep walks expired absences in join order (S3); the bare reaper
    # itself does not need it, so it defaults for the pure-reap call sites.
    joined_at: datetime | None = None


@dataclass(frozen=True)
class ReapOutcome:
    rooms_reaped: int
    participants_removed: int
    rooms_deleted: int
