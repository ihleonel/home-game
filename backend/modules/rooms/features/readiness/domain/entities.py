from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessParticipant:
    id: int
    is_ready: bool
