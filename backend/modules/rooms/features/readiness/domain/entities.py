from dataclasses import dataclass

from ...membership.domain.rules import PLAYER_ROLE


@dataclass(frozen=True)
class ReadinessParticipant:
    id: int
    is_ready: bool
    role: str = PLAYER_ROLE
