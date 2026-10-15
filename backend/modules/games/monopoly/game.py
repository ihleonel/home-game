"""``monopoly`` implementation of the framework-free game runtime contract.

The definition is stateless: it reads and produces the plain rules state owned
by the caller, and it adds nothing to the rules except the projection the match
screen consumes. No Django, DRF or Channels imports are allowed here.
"""

from typing import Mapping, Sequence

from ..contracts import (
    Action,
    ActionSpec,
    Outcome,
    Seat,
    SeatOption,
    Transition,
    seat_id,
)
from . import rules


class MonopolyDefinition:
    """The classic property trading game for two to eight seats."""

    game_id = 'monopoly'
    label = 'Monopoly'
    description = (
        'Comprá, alquilá y llevá a la quiebra a tus rivales: gana el último solvente.'
    )
    min_seats = rules.MIN_SEATS
    max_seats = rules.MAX_SEATS
    # Cosmetic identity, like every other game's chips: the token a player picks
    # in the room never changes the board.
    seat_options = (
        SeatOption(id='sombrero', label='Sombrero'),
        SeatOption(id='automovil', label='Automóvil'),
        SeatOption(id='perro', label='Perro'),
        SeatOption(id='barco', label='Barco'),
        SeatOption(id='gato', label='Gato'),
        SeatOption(id='plancha', label='Plancha'),
        SeatOption(id='botin', label='Botín'),
        SeatOption(id='dedal', label='Dedal'),
    )

    def start(self, seats: Sequence[Seat], rng) -> Mapping:
        """Open a match, drawing the opening seat from ``rng``.

        ``rng`` is required: the turn order is decided by a throw of the dice,
        and silently defaulting to the first seat would hand every match to the
        same player and make the throw an illusion. A ``None`` rng therefore
        raises ``ValueError`` instead of falling back.
        """
        if rng is None:
            raise ValueError(
                'monopoly requires a RandomSource to draw the opening seat; '
                'rng must not be None'
            )
        seat_ids = tuple(seat_id(seat.index) for seat in seats)
        return rules.initial_state(seat_ids, rng.shuffle(seat_ids)[0])

    def active_seats(self, state: Mapping) -> tuple[str, ...]:
        """The seat on turn, or ``()`` once the match is finished.

        Only one seat acts at a time in this increment. Auctions and trades,
        which let several seats act at once, are later increments and will
        widen this tuple without changing how the runtime reads it.
        """
        if rules.is_finished(state):
            return ()
        turn = state['turn']
        return () if turn is None else (turn,)

    def legal_actions(self, state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
        """Delegate to the pure rules."""
        return rules.legal_actions(state, seat)

    def apply(
        self,
        state: Mapping,
        seat: str,
        action: Action,
        rng,
    ) -> Transition:
        """Delegate to the pure rules."""
        return rules.apply_action(state, seat, action, rng)

    def abandon(self, state: Mapping, seat: str, rng) -> Transition:
        """Delegate to the pure rules; ``monopoly`` abandon needs no dice."""
        return rules.abandon(state, seat)

    def view(self, state: Mapping, seat: str | None) -> Mapping:
        """Return the seat-scoped or spectator view of the match (S13).

        The public economy of a Monopoly match -- positions, cash, owners and
        the last throw -- is visible to everyone, so a spectator sees the same
        board as a player. The only difference is ``you`` and ``actions``: the
        legal actions belong to one seat, so they are offered to that seat and
        to nobody else. The deck order of a later increment must never reach
        this projection, spectator or not.
        """
        finished = rules.is_finished(state)
        outcome = rules.outcome(state)
        view = {
            'finished': finished,
            'winner': None if outcome is None else outcome.winner_seat,
            'ended_by_abandon': state['ended_by_abandon'],
            'phase': state['phase'],
            'turn': None if finished else state['turn'],
            'players': [self._player_view(state, seat_id_) for seat_id_ in state['seats']],
            'owners': dict(state['owners']),
            'last_roll': (
                None if state['last_roll'] is None else list(state['last_roll'])
            ),
            'pending': (
                None if state['pending'] is None else dict(state['pending'])
            ),
            'actions': [] if seat is None else self._actions(state, seat),
        }
        if seat is not None:
            view['you'] = seat
        return view

    def is_finished(self, state: Mapping) -> bool:
        """Delegate to the pure rules."""
        return rules.is_finished(state)

    def outcome(self, state: Mapping) -> Outcome | None:
        """Delegate to the pure rules."""
        return rules.outcome(state)

    def _actions(self, state: Mapping, seat: str) -> list[dict]:
        """Project the seat's legal actions, which the frame does not carry."""
        return [
            {
                'name': spec.name,
                'prompt': spec.prompt,
                'options': list(spec.options),
            }
            for spec in rules.legal_actions(state, seat)
        ]

    def _player_view(self, state: Mapping, seat: str) -> dict:
        player = state['players'][seat]
        return {
            'seat': seat,
            'cash': player['cash'],
            'position': player['position'],
            'properties': list(player['properties']),
            'in_jail': player['in_jail'],
            'jail_turns': player['jail_turns'],
            'eliminated': player['eliminated'],
        }
