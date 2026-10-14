"""Framework-free DTOs and ports of the match runtime.

The use cases depend only on these protocols, so they can run against an
in-memory store and projector in tests and against Django-backed adapters in
production without changing. No Django, DRF or Channels imports are allowed
here.
"""

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from ...contracts import Action


@dataclass(frozen=True)
class SeatRecord:
    """One persisted seat of a match, ordered by ``index``."""

    index: int
    seat_id: str
    participant_ref: str
    badge: str


@dataclass(frozen=True)
class MatchHeader:
    """Everything about a match except its state."""

    match_ref: str
    room_id: int
    game_id: str
    version: int
    status: str
    winner_seat: str | None
    seats: tuple[SeatRecord, ...]


@dataclass(frozen=True)
class MatchRecord:
    """The persisted snapshot of a match handed to the use cases.

    ``version`` is the optimistic-concurrency token: a caller submits the
    version it read and the use case stores ``version + 1``.
    """

    match_ref: str
    room_id: int
    game_id: str
    version: int
    state: Mapping
    status: str
    winner_seat: str | None
    seats: tuple[SeatRecord, ...]

    def seat_for(self, participant_ref) -> SeatRecord | None:
        """Return the seat occupied by ``participant_ref``, or ``None``."""
        for seat in self.seats:
            if seat.participant_ref == participant_ref:
                return seat
        return None

    def seat(self, seat_id) -> SeatRecord | None:
        """Return the seat with ``seat_id``, or ``None``."""
        for seat in self.seats:
            if seat.seat_id == seat_id:
                return seat
        return None

    @property
    def header(self) -> MatchHeader:
        """Return this match as a state-free :class:`MatchHeader`."""
        return MatchHeader(
            match_ref=self.match_ref,
            room_id=self.room_id,
            game_id=self.game_id,
            version=self.version,
            status=self.status,
            winner_seat=self.winner_seat,
            seats=self.seats,
        )


class MatchStore(Protocol):
    """Persistence port for matches.

    ``unit_of_work`` is a context manager: atomicity is the adapter's job, not
    the use case's.
    """

    def unit_of_work(self):
        """Run a read-validate-write sequence as one transaction.

        Hard requirement on the adapter: it must serialize concurrent writers
        on the same match (for example by locking the match row), because the
        whole read-validate-write sequence must run in one transaction.
        ``save`` must fail loudly rather than overwrite when the stored version
        is no longer ``record.version - 1``, raising the existing
        ``StaleVersion``.
        """
        ...

    def load(self, match_ref: str) -> MatchRecord | None: ...

    def create(
        self,
        *,
        room_id: int,
        game_id: str,
        state: Mapping,
        seats: Sequence[SeatRecord],
    ) -> MatchRecord: ...

    def save(self, record: MatchRecord) -> None:
        """Persist ``version``, ``state``, ``status`` and ``winner_seat``."""
        ...

    def append_action(
        self,
        *,
        record: MatchRecord,
        seat_id: str,
        action: Action,
        facts: Sequence[Mapping],
    ) -> None:
        """Append the immutable audit row for this transition.

        ``seat_id`` is passed explicitly rather than derived from ``facts``:
        ``MatchAction`` persists a ``seat_id`` column, and scraping it back out
        of the emitted facts would be indirect and fragile. No ``event`` is
        passed: ``MatchAction`` has no event column, and the event name is a
        projection concern owned by ``MatchProjector.publish``, so handing it
        to the store would only invite the adapter to ignore it.
        """
        ...


class MatchLifecycle(Protocol):
    """Room-level consequences of finishing a match.

    Finishing a match is not only a match concern in this product: the room
    returns to its lobby with readiness reset so a rematch is possible (D7).
    That consequence lives in ``rooms``, and the runtime must reach it through
    this port rather than importing ``rooms``: the runtime's application layer
    is framework-free, and the adapter built in the interface composition root
    owns how a room's readiness is reset.

    The hook is a required part of finishing a match, not an optional extra:
    ``submit_action`` takes it with no default, so a caller that omits it fails
    at the call site rather than silently skipping the reset.
    """

    def on_match_finished(self, *, match_ref: str, room_id: int) -> None:
        """Apply the room-level consequence of ``match_ref`` finishing.

        Called exactly once, from inside the unit of work that saves the
        finished match, so the finish and the reset are one atomic outcome:
        either both happen or neither does. Raising aborts the action instead
        of leaving a half-finished state. The hook is a required part of
        finishing a match; callers cannot opt out by omitting it.
        """
        ...


class MatchProjector(Protocol):
    """Projection port for match events."""

    def publish(
        self,
        *,
        event: str,
        header: MatchHeader,
        views: Mapping,
        facts: Sequence[Mapping],
    ) -> None:
        """Publish ``views``, keyed by ``seat_id`` with a ``None`` public view.

        The projector deliberately never receives ``state``: a match's state
        may hold a value that some seat must not see until the reveal (a
        pending pick, for example). Publishing only precomputed ``views``
        makes a leak structurally impossible; ``header`` carries everything
        else about the match.
        """
        ...
