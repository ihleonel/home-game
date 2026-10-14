"""``duelo`` implementation of the framework-free game runtime contract.

The definition is stateless: it reads and produces the plain rules state owned
by the caller. No Django, DRF, or Channels imports are allowed here.
"""

from typing import Mapping, Sequence

from ..contracts import Action, ActionSpec, Fact, Outcome, Seat, SeatOption, Transition
from . import rules


class DueloDefinition:
    """Rock-paper-scissors, best of three, with exactly two seats."""

    game_id = 'duelo'
    label = 'Duelo'
    description = 'Elegí piedra, papel o tijera y ganá dos rondas.'
    min_seats = 2
    max_seats = 2
    seat_options = (
        SeatOption(id='guante-rojo', label='Guante rojo'),
        SeatOption(id='guante-azul', label='Guante azul'),
        SeatOption(id='guante-verde', label='Guante verde'),
    )

    def start(self, seats: Sequence[Seat], rng) -> Mapping:
        """Open a match keyed by seat index.

        ``duelo`` has no randomness, so ``rng`` is accepted for contract
        compatibility and ignored.
        """
        return rules.initial_state(f'seat-{seat.index}' for seat in seats)

    def active_seats(self, state: Mapping) -> tuple[str, ...]:
        """Seats still owing a pick, in seat-id order; empty once finished."""
        if rules.is_finished(state):
            return ()
        return tuple(
            seat_id for seat_id, pick in state['picks'].items() if pick is None
        )

    def legal_actions(self, state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
        """Only an unpicked seat of an unfinished match may pick."""
        if (
            seat not in state['picks']
            or state['picks'][seat] is not None
            or rules.is_finished(state)
        ):
            return ()
        return (
            ActionSpec(name='pick', options=rules.CHOICES, prompt='Elegí tu jugada.'),
        )

    def apply(
        self,
        state: Mapping,
        seat: str,
        action: Action,
        rng,
    ) -> Transition:
        """Advance the match with ``action.value`` and return the facts emitted.

        A pick that leaves the round open emits only ``pick_recorded`` with an
        empty detail, so the chosen value never leaks before the reveal. A pick
        that resolves the round also emits ``round_resolved``; a pick that ends
        the match additionally emits ``match_finished``.
        """
        other_picks = [
            pick for other, pick in state['picks'].items() if other != seat
        ]
        round_resolved = all(pick is not None for pick in other_picks)

        new_state = rules.apply_pick(state, seat, action.value)
        facts = [Fact(name='pick_recorded', seat=seat, detail={})]

        if round_resolved:
            reveal = new_state['reveal']
            facts.append(
                Fact(
                    name='round_resolved',
                    detail={
                        'round': reveal['round'],
                        'picks': dict(reveal['picks']),
                        'winner': reveal['winner'],
                    },
                )
            )

        if rules.is_finished(new_state):
            facts.append(
                Fact(name='match_finished', detail={'winner': new_state['winner']})
            )

        return Transition(state=new_state, facts=tuple(facts))

    def view(self, state: Mapping, seat: str | None) -> Mapping:
        """Return the seat-scoped or spectator view of the match.

        A seat never sees the opponent's pending pick: it only learns whether
        the opponent has picked. Both picks become public through ``reveal``
        once the round resolves. ``ended_by_abandon`` is public in every view so
        a client that only receives a snapshot can tell an abandonment finish
        from a normal one.
        """
        ended_by_abandon = state.get('abandoned_seat') is not None
        if seat is None:
            return {
                'round': state['round'],
                'scores': dict(state['scores']),
                'both_picked': all(
                    pick is not None for pick in state['picks'].values()
                ),
                'reveal': state['reveal'],
                'winner': state['winner'],
                'finished': rules.is_finished(state),
                'ended_by_abandon': ended_by_abandon,
            }

        opponent = next(
            (other for other in state['picks'] if other != seat), None
        )
        return {
            'round': state['round'],
            'scores': dict(state['scores']),
            'you': seat,
            'your_pick': state['picks'].get(seat),
            'opponent_has_picked': (
                opponent is not None and state['picks'][opponent] is not None
            ),
            'reveal': state['reveal'],
            'winner': state['winner'],
            'finished': rules.is_finished(state),
            'ended_by_abandon': ended_by_abandon,
        }

    def abandon(self, state: Mapping, seat: str, rng) -> Transition:
        """Resolve the match after ``seat`` is expelled for not reconnecting.

        Delegates to the pure rules. ``duelo`` has two seats, so the seat that
        stays wins by abandonment and the match is frozen; the emitted facts
        record the expulsion and, since the match always ends here, its result.
        ``rng`` is accepted for contract compatibility and ignored, like
        ``start``.
        """
        new_state = rules.abandon(state, seat)
        facts = [Fact(name='seat_abandoned', seat=seat, detail={})]

        if rules.is_finished(new_state):
            facts.append(
                Fact(name='match_finished', detail={'winner': new_state['winner']})
            )

        return Transition(state=new_state, facts=tuple(facts))

    def is_finished(self, state: Mapping) -> bool:
        """Delegate to the pure rules."""
        return rules.is_finished(state)

    def outcome(self, state: Mapping) -> Outcome | None:
        """Delegate to the pure rules."""
        return rules.outcome(state)
