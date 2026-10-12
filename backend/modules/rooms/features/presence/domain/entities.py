from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class PresenceParticipant:
    id: int
    session_id: UUID
    presence: str
    disconnected_at: datetime | None
