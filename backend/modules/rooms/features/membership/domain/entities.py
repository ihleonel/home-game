from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ActiveRoom:
    id: int
    game_id: str


@dataclass(frozen=True)
class ParticipantMembership:
    id: int
    session_id: UUID
    public_id: UUID
    display_name: str
    game_marker: str
    presence: str
    was_left: bool
    is_ready: bool
    role: str
