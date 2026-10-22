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
    # A freeform action carries a client-composed value the engine alone can
    # grade (S3): the runtime accepts any non-empty string and the engine's
    # ``ValueError`` is a client error, never a programming error.
    freeform: bool = False


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

    def abandon(
        self,
        state: Mapping,
        seat: SeatId,
        rng: RandomSource | None,
    ) -> Transition:
        """Resolve the match after ``seat`` is expelled for not reconnecting.

        The runtime calls this exactly once, immediately after it removes
        ``seat`` from the match, inside the same transaction that persists the
        resulting state (S5): a seat is never already out while the match has
        not yet processed it. Defining what the expulsion does is the game's
        own decision (S3). A definition may end the match here (for example
        ``duelo`` awards the win to the seat that stayed) or return a state in
        which the remaining seats keep playing with the abandoned seat's turns,
        points or resources folded back in (S4).

        Like every other method in this protocol this is a pure function: it
        never mutates ``state`` and returns a brand-new state plus the facts
        the expulsion emits. It deliberately does **not** decide whether the
        match is over: the runtime still calls :meth:`is_finished` and
        :meth:`outcome` on the returned state, exactly as it does after
        :meth:`apply`. A definition whose match continues must therefore return
        a state that reflects that, instead of a finished-flags-clear state
        that silently still looks over (S4).

        Raises ``ValueError`` if ``seat`` is not one of the match's seats, or
        if the match is already finished. Both are programming errors -- the
        runtime only ever abandons a live seat of an unfinished match -- and
        accepting them would silently corrupt an already-resolved match. This
        mirrors the loud-failure convention of ``duelo.rules.apply_pick``.

        A trigger can repeat. The runtime is idempotent for a match it has
        already resolved and never calls this on a finished match, but two
        independent triggers of the same absence (the reconnect grace timer
        and the sweep that recovers seats left expired by a restart) can both
        reach a match that is still running. A definition whose ``abandon``
        leaves the match alive must therefore tolerate a repeated call for the
        same seat: return a state equivalent to the one it already produced,
        instead of raising or folding the same seat's points in twice.
        """
        ...

    def view(self, state: Mapping, seat: SeatId | None) -> Mapping: ...

    def is_finished(self, state: Mapping) -> bool: ...

    def outcome(self, state: Mapping) -> Outcome | None: ...
