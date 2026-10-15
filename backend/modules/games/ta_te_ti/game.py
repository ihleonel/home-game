"""``ta_te_ti`` implementation of the framework-free game runtime contract.

The definition is stateless: it reads and produces the plain rules state owned
by the caller. No Django, DRF, or Channels imports are allowed here.
"""

from typing import Mapping, Sequence

from ..contracts import Action, ActionSpec, Fact, Outcome, Seat, SeatOption, Transition
from . import rules


class TaTeTiDefinition:
    """Tic-tac-toe for exactly two seats, X for seat 0 and O for seat 1."""

    game_id = 'ta-te-ti'
    label = 'Ta-te-ti'
    description = 'Formá una línea de tres y ganá la partida.'
    min_seats = 2
    max_seats = 2
    # The room chips are purely cosmetic identity: the board is always X/O.
    seat_options = (
        SeatOption(id='sol', label='Sol'),
        SeatOption(id='luna', label='Luna'),
        SeatOption(id='estrella', label='Estrella'),
    )

    def start(self, seats: Sequence[Seat], rng) -> Mapping:
        """Open a match, drawing the opening seat from ``rng``.

        ``rng`` is required: the opening seat is random per match (S4), and
        silently defaulting to seat 0 would give every match to the same seat
        and make the coin toss an illusion. A ``None`` rng therefore raises
        ``ValueError`` instead of falling back.
        """
        if rng is None:
            raise ValueError(
                'ta-te-ti requires a RandomSource to draw the opening seat; '
                'rng must not be None'
            )
        seat_ids = tuple(f'seat-{seat.index}' for seat in seats)
        # ``shuffle`` is the unambiguous draw available on the RandomSource
        # protocol; the first item of the shuffled seats opens the match.
        first_seat = rng.shuffle(seat_ids)[0]
        return rules.initial_state(seat_ids, first_seat)

    def active_seats(self, state: Mapping) -> tuple[str, ...]:
        """The seat on turn, or ``()`` once the match is finished."""
        if rules.is_finished(state):
            return ()
        return (state['turn'],)

    def legal_actions(self, state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
        """The free cells are offered to the seat on turn of a live match."""
        if (
            rules.is_finished(state)
            or seat not in state['seats']
            or state['turn'] != seat
        ):
            return ()
        options = tuple(
            str(cell) for cell, value in enumerate(state['board']) if value is None
        )
        if not options:
            return ()
        return (
            ActionSpec(name='pick', options=options, prompt='Elegí una celda.'),
        )

    def apply(
        self,
        state: Mapping,
        seat: str,
        action: Action,
        rng,
    ) -> Transition:
        """Place ``action.value`` on the board and return the facts emitted.

        A pick that leaves the match running emits only ``pick_recorded`` with
        the chosen cell. A pick that ends the match -- by a line or by filling
        the board, which is a draw -- additionally emits ``match_finished`` with
        the winner (``None`` for a draw). ``rng`` is accepted for contract
        compatibility and ignored: after the opening draw the game is
        deterministic.
        """
        new_state = rules.apply_pick(state, seat, action.value)
        facts = [
            Fact(
                name='pick_recorded',
                seat=seat,
                detail={'cell': int(action.value)},
            )
        ]

        if rules.is_finished(new_state):
            facts.append(
                Fact(name='match_finished', detail={'winner': new_state['winner']})
            )

        return Transition(state=new_state, facts=tuple(facts))

    def view(self, state: Mapping, seat: str | None) -> Mapping:
        """Return the seat-scoped or spectator view of the match.

        The board is public: a seat and a spectator see exactly the same
        fields, and the only difference is ``you``, which is present only when
        ``seat`` is not ``None``. ``winner_line`` is always a list of three
        cell indexes or ``None``, and ``finished`` is true for a draw too.
        """
        finished = rules.is_finished(state)
        winner_line = state['winner_line']
        view = {
            'board': list(state['board']),
            'turn': state['turn'] if not finished else None,
            'symbols': rules.symbols(state),
            'winner_line': None if winner_line is None else list(winner_line),
            'winner': state['winner'],
            'finished': finished,
            'ended_by_abandon': state['ended_by_abandon'],
        }
        if seat is not None:
            view['you'] = seat
        return view

    def abandon(self, state: Mapping, seat: str, rng) -> Transition:
        """Resolve the match after ``seat`` is expelled for not reconnecting.

        Delegates to the pure rules: the seat that stayed wins by abandonment
        and the match is frozen. The facts record the expulsion and the
        resulting finish. ``rng`` is accepted for contract compatibility and
        ignored, like ``apply``.
        """
        new_state = rules.abandon(state, seat)
        facts = (
            Fact(name='seat_abandoned', seat=seat, detail={}),
            Fact(name='match_finished', detail={'winner': new_state['winner']}),
        )
        return Transition(state=new_state, facts=facts)

    def is_finished(self, state: Mapping) -> bool:
        """Delegate to the pure rules."""
        return rules.is_finished(state)

    def outcome(self, state: Mapping) -> Outcome | None:
        """Delegate to the pure rules."""
        return rules.outcome(state)
