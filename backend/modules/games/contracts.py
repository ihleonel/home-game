"""Framework-free game runtime contract.

Game definitions are stateless: the mutable state of a match lives in the
caller (the future ``Match`` runtime) and is threaded through every method as
an opaque ``Mapping``. Nothing in this module may import Django, DRF, or
Channels.
"""

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

SeatId = str
ParticipantRef = str


def seat_id(index: int) -> str:
    """Return the canonical seat id for a seat index.

    This is the single source of the ``f'seat-{index}'`` convention shared by
    the runtime and every game definition, so the two cannot drift apart.
    """
    return f'seat-{index}'


@dataclass(frozen=True)
class Seat:
    index: int
    participant_ref: ParticipantRef
    badge: str | None = None


@dataclass(frozen=True)
class SeatOption:
    id: str
    label: str


@dataclass(frozen=True)
class ActionSpec:
    name: str
    options: tuple[str, ...] = ()
    prompt: str = ''


@dataclass(frozen=True)
class Action:
    name: str
    value: str | None = None


@dataclass(frozen=True)
class Fact:
    """An observable fact emitted by a transition.

    ``detail`` must carry only what every recipient of this fact may see.
    """

    name: str
    seat: SeatId | None = None
    detail: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    state: Mapping
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class Outcome:
    winner_seat: SeatId | None
    reason: str


class RandomSource(Protocol):
    def shuffle(self, items: Sequence) -> list: ...

    def roll(self, sides: int) -> int: ...


class GameDefinition(Protocol):
    """Stateless rules of a game; mutable state lives in Match."""

    game_id: str
    label: str
    description: str
    min_seats: int
    max_seats: int
    seat_options: tuple[SeatOption, ...]

    def start(self, seats: Sequence[Seat], rng: RandomSource | None) -> Mapping: ...

    def active_seats(self, state: Mapping) -> tuple[SeatId, ...]:
        """Return the seats that may act in ``state``.

        The order of the returned tuple is **not significant**: the runtime
        orders seats by its own ``MatchSeat.index``. Match state is persisted
        in a Postgres ``jsonb`` column, which does not preserve object key
        order, so a definition must not rely on the order of a state-derived
        tuple.
        """
        ...

    def legal_actions(self, state: Mapping, seat: SeatId) -> tuple[ActionSpec, ...]: ...

    def apply(
        self,
        state: Mapping,
        seat: SeatId,
        action: Action,
        rng: RandomSource | None,
    ) -> Transition:
        """Advance the match and return the new state plus the facts emitted.

        Precondition: the runtime passes only actions obtained from
        ``legal_actions`` for a seat returned by ``active_seats``. An
        implementation must still never silently accept an invalid value.
        """
        ...

    def view(self, state: Mapping, seat: SeatId | None) -> Mapping: ...

    def is_finished(self, state: Mapping) -> bool: ...

    def outcome(self, state: Mapping) -> Outcome | None: ...
