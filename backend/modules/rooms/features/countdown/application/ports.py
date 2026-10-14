"""Ports and value objects of the lobby countdown use cases.

The use cases depend only on this protocol, so they stay free of Django,
Channels and asyncio. Timer methods are sync (they only touch an in-memory
registry); the lobby and transport methods are async.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LobbyLimits:
    """The seat bounds a game accepts for a lobby."""

    min_seats: int
    max_seats: int


@dataclass(frozen=True)
class LobbyState:
    """A freshly prepared lobby and whether a match may start from it."""

    snapshot: dict
    seatable: bool


class LobbyCountdownPorts(Protocol):
    def game_limits(self, game_id) -> LobbyLimits | None: ...

    def current_countdown(self, room_id): ...

    def arm_countdown(self, room_id, seconds, on_expire) -> object | None: ...

    def cancel_countdown(self, room_id) -> object | None: ...

    async def prepare_lobby(self, room_id) -> LobbyState | None: ...

    async def start_match(self, room_id) -> None: ...

    async def broadcast(self, room_id, event_name, snapshot, countdown): ...
