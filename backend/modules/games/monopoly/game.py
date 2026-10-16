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
from . import cards, rules


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
        """Open a match by the printed throw-off.

        ``rng`` is required: every seat throws two dice and the highest total
        opens the play, so a ``None`` rng raises ``ValueError`` instead of
        silently handing the first turn to the first seat and making the throw
        an illusion. The roster is validated before any die is rolled, so an
        invalid opening fails without consuming randomness.
        """
        if rng is None:
            raise ValueError(
                'monopoly requires a RandomSource to draw the opening seat; '
                'rng must not be None'
            )
        seat_ids = rules.validate_roster(seat_id(seat.index) for seat in seats)
        return rules.initial_state(
            seat_ids,
            _highest_throw(seat_ids, rng),
            rules.fresh_decks(rng),
        )

    def active_seats(self, state: Mapping) -> tuple[str, ...]:
        """The seats that may act right now, or ``()`` once the match is over.

        While an auction is open several seats act at once -- every solvent
        seat that has not passed -- which is the multi-seat shape the contract
        always allowed. Every other phase has exactly one.
        """
        return rules.active_seats(state)

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

        The public economy of a Monopoly match -- positions, cash, owners, the
        houses standing on the board, the bank's remaining stock, the last throw
        and the last card turned up -- is visible to everyone, so a spectator
        sees the same board as a player. The only difference is ``you`` and
        ``actions``: the legal actions belong to one seat, so they are offered
        to that seat and to nobody else.

        The deck **order** never reaches this projection: a seat learns how many
        cards are left, and the card that was drawn is published only because it
        was turned face up for the whole table.
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
            'buildings': dict(state.get('buildings') or {}),
            'mortgaged': dict(state.get('mortgaged') or {}),
            'bank': dict(state['bank']),
            'debt': self._debt_view(state),
            'decks': {
                deck: len(order) for deck, order in state['decks'].items()
            },
            'last_card': self._card_view(state),
            'auction': self._auction_view(state),
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
            # How many cards the seat holds, not which ones: the seat count is
            # what a table sees in someone's hand.
            'jail_cards': len(player['jail_cards']),
            'eliminated': player['eliminated'],
        }

    def _card_view(self, state: Mapping) -> dict | None:
        """The card turned up last, resolved to the copy a player reads."""
        drawn = state['last_card']
        if drawn is None:
            return None
        drawn_card = cards.card_for(drawn['id'])
        return {'deck': drawn_card.deck, 'id': drawn_card.id, 'title': drawn_card.title}

    def _debt_view(self, state: Mapping) -> dict | None:
        """The open debt, or ``null`` (S11).

        Only the public part is published: the seat, the creditor (``null``
        for the bank) and the amount. Everything else the rules keep in the
        record -- the exact continuation and the deferred fact -- is internal.
        """
        debt = state.get('debt')
        if debt is None:
            return None
        return {
            'seat': debt['seat'],
            'creditor': debt['creditor'],
            'amount': debt['amount'],
        }

    def _auction_view(self, state: Mapping) -> dict | None:
        """The open auction, or ``null``.

        ``waiting_for`` is what lets the table see who is still to bid; the bids
        themselves are actions, which every eligible seat already receives in
        its own view, so the frontend needs to know nothing about the auction.
        """
        auction = state.get('auction')
        if auction is None:
            return None
        return {
            'space': auction['space'],
            'high_bid': auction['high_bid'],
            'high_bidder': auction['high_bidder'],
            'waiting_for': list(rules.eligible_bidders(state)),
        }


def _highest_throw(seat_ids: Sequence[str], rng) -> str:
    """Return the seat that opens the match, by the printed throw-off.

    Every seat throws two dice and the highest total opens. Ties re-throw among
    the tied seats only, bounded to one round per seat so a degenerate
    ``RandomSource`` cannot spin forever: if the bound is exhausted, the first
    tied seat in seat order opens, which is the tie-break the printed rule
    leaves to the table.
    """
    contenders = list(seat_ids)
    for _ in range(len(seat_ids)):
        totals = {
            seat: sum(rng.roll(rules.DICE_SIDES) for _ in range(rules.DICE_COUNT))
            for seat in contenders
        }
        best = max(totals.values())
        leaders = [seat for seat in contenders if totals[seat] == best]
        if len(leaders) == 1:
            return leaders[0]
        contenders = leaders
    return contenders[0]
