from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReapableParticipant:
    id: int
    room_id: int
    session_id: object
    presence: str
    disconnected_at: datetime | None


@dataclass(frozen=True)
class ReapOutcome:
    rooms_reaped: int
    participants_removed: int
    rooms_deleted: int
