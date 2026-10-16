"""Pure rules for ``monopoly``, the classic property trading game (S5-S12).

Plain data transforms: the rules never mutate their inputs and never import
Django, DRF or Channels. The mutable match state lives in the caller and is
threaded through as an opaque mapping, exactly like ``ta_te_ti``.

The rules cover the playable core and the increments that followed it: dice,
movement, GO, purchases, the auction a decline opens, rents by development
level, house and hotel building with the bank's finite stock, both decks,
taxes, jail, bankruptcy, elimination and the end of the match. Mortgages and
trading are later increments and are deliberately absent (S16 of
``monopoly.md``): an unaffordable debt goes straight to bankruptcy because the
raise-cash route does not exist yet, and the scarcity auction of houses and
hotels is not implemented (S13 of ``monopoly-building.md``).

The edition is the classic 1999-2007 rulebook (S2): $1.500 to start, Income Tax
at $200 or 10 % of total worth, Luxury Tax at $75.
"""

import copy
from typing import Mapping, Sequence

from ..contracts import Action, ActionSpec, Fact, Outcome, Transition
from . import board, cards, deeds

DICE_SIDES = 6
DICE_COUNT = 2

MIN_SEATS = 2
MAX_SEATS = 8

STARTING_CASH = 1500
GO_SALARY = 200
JAIL_FINE = 50
# Three failed jail rolls means the fine is no longer optional.
JAIL_TURNS_LIMIT = 3
DOUBLES_TO_JAIL = 3
INCOME_TAX_FIXED = 200
INCOME_TAX_PERCENT = 10
LUXURY_TAX = 75
STARTING_HOUSES = 32
STARTING_HOTELS = 12

# A card's own rent rule, which is not the rule for landing there: the
# nearest-railroad card doubles the rent the count of railroads would charge,
# and the nearest-utility card pays ten times a fresh throw however many
# utilities the owner holds.
_RAILROAD_DOUBLED = 'railroad_doubled'
CARD_UTILITY_MULTIPLIER = 10

# The three phases the state persists (S6 of ``monopoly.md``), plus the auction
# phase the third increment adds (S2 of ``monopoly-auction.md``). Resolving a
# space happens inside the same transition as the roll, so it is not a phase.
PHASE_AWAITING_ROLL = 'awaiting_roll'
PHASE_AWAITING_DECISION = 'awaiting_decision'
PHASE_MANAGING = 'managing'
PHASE_AWAITING_BID = 'awaiting_bid'

ACTION_ROLL = 'roll'
ACTION_PAY_JAIL_FINE = 'pay_jail_fine'
ACTION_BUY = 'buy'
ACTION_DECLINE = 'decline'
ACTION_PAY_INCOME_TAX_FIXED = 'pay_income_tax_fixed'
ACTION_PAY_INCOME_TAX_PERCENT = 'pay_income_tax_percent'
ACTION_END_TURN = 'end_turn'
ACTION_USE_JAIL_CARD = 'use_jail_card'
ACTION_BID = 'bid'
ACTION_PASS = 'pass'
ACTION_BUILD = 'build'
ACTION_SELL = 'sell'

# The ladder a bid may climb by: the high bid plus each of these, filtered by
# the bidder's cash. The printed rules allow any price and the runtime only
# accepts an enumerated option list, so the ladder is the documented adaptation
# (S4 of ``monopoly-auction.md``).
_BID_STEPS = (1, 10, 50, 100)

# Spaces that stop the token without asking anything. The two card spaces are
# deliberately absent: they draw, and the draw is what resolves them.
_SILENT_KINDS = frozenset(
    (
        board.SpaceKind.GO,
        board.SpaceKind.JAIL,
        board.SpaceKind.FREE_PARKING,
    )
)


def validate_roster(seat_ids) -> list[str]:
    """Return the roster as a list, or raise for a roster the board cannot seat.

    Separated from :func:`initial_state` so a caller that must act before the
    opening throw -- the definition, which rolls for the turn order -- can
    reject an invalid roster without first drawing dice for it.
    """
    seats = list(seat_ids)
    if not MIN_SEATS <= len(seats) <= MAX_SEATS:
        raise ValueError(
            f'monopoly seats between {MIN_SEATS} and {MAX_SEATS} players, '
            f'got {len(seats)}'
        )
    if len(set(seats)) != len(seats):
        raise ValueError(f'duplicate seats: {seats!r}')
    return seats


def initial_state(
    seat_ids: Sequence[str], first_seat: str, decks: Mapping | None = None
) -> dict:
    """Open a match with every player at GO, solvent and holding $1.500.

    ``first_seat`` is supplied by the caller (the definition draws it from a
    ``RandomSource``); the rules never choose an opening seat themselves.
    ``decks`` is the shuffled deck order, also supplied by the caller through
    :func:`fresh_decks`; when it is omitted the decks stay in printed order,
    which is what a rule test wants and what production must never rely on.
    Raises ``ValueError`` for a roster the board cannot seat, so an invalid
    opening never reaches the board.
    """
    seats = validate_roster(seat_ids)
    if first_seat not in seats:
        raise ValueError(f'unknown first seat: {first_seat!r}')
    return {
        'seats': seats,
        'players': {seat: _fresh_player() for seat in seats},
        'owners': {},
        'buildings': {},
        'bank': {'houses': STARTING_HOUSES, 'hotels': STARTING_HOTELS},
        'decks': _deck_order(decks),
        'last_card': None,
        'auction': None,
        'phase': PHASE_AWAITING_ROLL,
        'turn': first_seat,
        'last_roll': None,
        'pending': None,
        'doubles_count': 0,
        'extra_roll': False,
        'ended_by_abandon': False,
        'abandoned_seat': None,
    }


def fresh_decks(rng) -> dict:
    """Return both decks shuffled with ``rng``.

    Production goes through this so a match never starts on an unshuffled deck;
    the order is hidden information the state keeps and the view never
    publishes beyond how many cards are left.

    The result is checked: a ``RandomSource`` that answers a deck shuffle with
    anything but a permutation of the cards it was handed would silently store
    that other thing as the deck. A test double handed the decks the seat ids
    exactly this way, and the match failed much later, only when a roll landed
    on a card space, which made the suite flaky for reasons nothing pointed at.
    A bad shuffle therefore fails here, loudly, at the moment it happens.
    """
    if rng is None:
        raise ValueError('a fresh deck needs a RandomSource to be shuffled')
    decks = {}
    for deck in cards.DECKS:
        ids = list(cards.deck_ids(deck))
        shuffled = list(rng.shuffle(list(ids)))
        if len(shuffled) != len(ids) or set(shuffled) != set(ids):
            raise ValueError(
                f'{deck}: the RandomSource did not return a permutation of the '
                f'{len(ids)} cards it was given'
            )
        decks[deck] = shuffled
    return decks


def _deck_order(decks) -> dict:
    """Normalize the deck order, defaulting to the printed order."""
    if decks is None:
        return {deck: list(cards.deck_ids(deck)) for deck in cards.DECKS}
    return {deck: list(decks[deck]) for deck in cards.DECKS}


def solvent_seats(state: Mapping) -> tuple[str, ...]:
    """Return every seat still in the match, in seat order."""
    return tuple(
        seat for seat in state['seats'] if not state['players'][seat]['eliminated']
    )


def is_finished(state: Mapping) -> bool:
    """Whether the match is over: at most one seat is still in it (S12)."""
    return len(solvent_seats(state)) <= 1


def outcome(state: Mapping) -> Outcome | None:
    """Return the winner and reason, or ``None`` while the match runs.

    The winner is the only seat left. The reason distinguishes a match that
    ended because a seat was expelled for not reconnecting (S14) from an
    ordinary win on the board.
    """
    if not is_finished(state):
        return None
    survivors = solvent_seats(state)
    winner = survivors[0] if survivors else None
    reason = 'win_by_abandon' if state['ended_by_abandon'] else 'last_solvent'
    return Outcome(winner_seat=winner, reason=reason)


def active_seats(state: Mapping) -> tuple[str, ...]:
    """Return the seats that may act right now, in seat order.

    Only one seat acts at a time, except while an auction is open: there every
    solvent seat that has not passed may bid, which is the multi-seat shape the
    runtime contract always allowed and the auction is the first rule to use.
    """
    if is_finished(state):
        return ()
    if state['phase'] == PHASE_AWAITING_BID:
        return eligible_bidders(state)
    turn = state['turn']
    return () if turn is None else (turn,)


def eligible_bidders(state: Mapping) -> tuple[str, ...]:
    """Return the seats still bidding, in seat order.

    A seat that passed is out until somebody bids again, because a fresh bid
    reopens the auction for everyone. An eliminated seat is never a bidder.
    """
    auction = state.get('auction')
    if auction is None:
        return ()
    passed = auction['passed']
    return tuple(seat for seat in solvent_seats(state) if seat not in passed)


def _bid_amounts(state: Mapping, seat: str) -> tuple[int, ...]:
    """The bids ``seat`` may place: the high bid plus the ladder, within cash."""
    auction = state['auction']
    cash = state['players'][seat]['cash']
    return tuple(
        amount
        for amount in (auction['high_bid'] + step for step in _BID_STEPS)
        if amount <= cash
    )


def _bid_specs(state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
    """The bids and the pass this seat may take in the open auction."""
    if seat not in eligible_bidders(state):
        return ()
    specs = []
    amounts = _bid_amounts(state, seat)
    if amounts:
        specs.append(
            ActionSpec(
                name=ACTION_BID,
                options=tuple(str(amount) for amount in amounts),
                prompt='Pujá',
            )
        )
    # A bid cannot be withdrawn, so the seat holding the high bid may only
    # raise it: the auction ends when the others pass, never by the leader
    # walking away from its own bid.
    if state['auction']['high_bidder'] != seat:
        specs.append(ActionSpec(name=ACTION_PASS, prompt='Pasá la subasta.'))
    return tuple(specs)


def _managing_specs(state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
    """The free window's actions: build, sell and end the turn.

    The option lists are the board indexes the seat may act on right now, as
    text and in board order, so the panel draws one button per option and
    never decides by itself what is buildable.
    """
    specs = []
    buildable = _buildable_indexes(state, seat)
    if buildable:
        specs.append(
            ActionSpec(
                name=ACTION_BUILD,
                options=tuple(str(index) for index in buildable),
                prompt='Construí',
            )
        )
    sellable = _sellable_indexes(state, seat)
    if sellable:
        specs.append(
            ActionSpec(
                name=ACTION_SELL,
                options=tuple(str(index) for index in sellable),
                prompt='Vendé',
            )
        )
    specs.append(ActionSpec(name=ACTION_END_TURN, prompt='Terminá tu turno.'))
    return tuple(specs)


def total_worth(state: Mapping, seat: str) -> int:
    """Return cash plus the printed prices of the seat's properties and builds.

    The buildings a seat holds are added at their cost price (a hotel as five
    houses, S5 of ``monopoly-building.md``), so improving a property can never
    lower the seat's worth. The mortgage state of a property deliberately does
    not change its printed price (S10 of ``monopoly.md``).
    """
    player = state['players'][seat]
    return (
        player['cash']
        + sum(deeds.purchase_price(index) for index in player['properties'])
        + sum(
            deeds.development_cost(deeds.deed_for(index), _level(state, index))
            for index in player['properties']
            if deeds.is_street(index)
        )
    )


def legal_actions(state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
    """Return the actions ``seat`` may take right now, and nothing else."""
    if is_finished(state) or seat not in state['players']:
        return ()
    if seat not in active_seats(state):
        return ()

    player = state['players'][seat]
    phase = state['phase']
    if phase == PHASE_AWAITING_BID:
        return _bid_specs(state, seat)
    if phase == PHASE_AWAITING_ROLL:
        specs = [ActionSpec(name=ACTION_ROLL, prompt='Tirá los dados.')]
        if player['in_jail'] and player['jail_cards']:
            specs.append(
                ActionSpec(
                    name=ACTION_USE_JAIL_CARD,
                    prompt='Usá la carta de «Salí de la cárcel gratis».',
                )
            )
        if (
            player['in_jail']
            and player['jail_turns'] < JAIL_TURNS_LIMIT - 1
            and player['cash'] >= JAIL_FINE
        ):
            specs.append(
                ActionSpec(
                    name=ACTION_PAY_JAIL_FINE,
                    prompt=f'Pagá ${JAIL_FINE} de multa y salí de la cárcel.',
                )
            )
        return tuple(specs)

    if phase == PHASE_AWAITING_DECISION:
        pending = state['pending'] or {}
        if pending.get('kind') == 'purchase':
            index = pending['space']
            price = deeds.purchase_price(index)
            specs = []
            if player['cash'] >= price:
                specs.append(
                    ActionSpec(
                        name=ACTION_BUY,
                        prompt=f'Comprá {board.space_at(index).name} por ${price}.',
                    )
                )
            specs.append(ActionSpec(name=ACTION_DECLINE, prompt='No la compres.'))
            return tuple(specs)
        if pending.get('kind') == 'income_tax':
            return (
                ActionSpec(
                    name=ACTION_PAY_INCOME_TAX_FIXED,
                    prompt=f'Pagá ${INCOME_TAX_FIXED} fijos.',
                ),
                ActionSpec(
                    name=ACTION_PAY_INCOME_TAX_PERCENT,
                    prompt=f'Pagá el {INCOME_TAX_PERCENT} % de tu patrimonio.',
                ),
            )
        return ()

    if phase == PHASE_MANAGING:
        return _managing_specs(state, seat)

    return ()


def apply_action(
    state: Mapping,
    seat: str,
    action: Action,
    rng,
) -> Transition:
    """Apply one action and return the new state plus the facts it emitted.

    Raises ``ValueError`` for an unknown seat, a seat that is not on turn, an
    action outside its phase or an unknown action name. The runtime only ever
    passes an action from :func:`legal_actions`, so a rejection here is a
    programming error and must never be silently accepted.
    """
    if is_finished(state):
        raise ValueError('the match is already finished')
    if seat not in state['players']:
        raise ValueError(f'unknown seat: {seat!r}')
    if seat not in active_seats(state):
        raise ValueError(f'{seat!r} cannot act right now')
    handler = _HANDLERS.get(action.name)
    if handler is None:
        raise ValueError(f'unknown action: {action.name!r}')
    return _with_finish_fact(handler(state, seat, action, rng))


def abandon(state: Mapping, seat: str) -> Transition:
    """Resolve the match after ``seat`` is expelled for not reconnecting (S14).

    The expulsion is a bankruptcy to the bank: the seat's cash leaves the game,
    its properties go back to the bank unowned and the seat leaves the match.
    The match keeps running for the remaining seats and only records that it
    ended by abandonment when the expulsion is what leaves one seat standing.

    Tolerates a repeated call for the same seat, because the reconnect timer and
    the recovery sweep are independent triggers of the same absence.
    """
    if seat not in state['players']:
        raise ValueError(f'unknown seat: {seat!r}')
    if is_finished(state):
        raise ValueError('the match is already finished')

    state = _copy(state)
    events = []
    if not state['players'][seat]['eliminated']:
        _eliminate(state, seat, None)
        events.append(Fact(name='seat_abandoned', seat=seat, detail={}))
    state['abandoned_seat'] = seat

    if len(solvent_seats(state)) <= 1:
        state['ended_by_abandon'] = True
        state['turn'] = None
        state['pending'] = None
        state['extra_roll'] = False
        state['auction'] = None
        state['phase'] = PHASE_AWAITING_ROLL
    elif state['auction'] is not None:
        # The auction owns the phase, so the turn is parked while it is open. It
        # only moves if the expelled seat was holding it, and the auction is
        # re-checked because losing a bidder can be what ends it (S6).
        if state['turn'] == seat:
            state['turn'] = _next_solvent_seat(state, seat)
        _resolve_auction_if_due(state, events)
    elif state['turn'] == seat:
        _pass_turn(state, events)

    return _with_finish_fact(Transition(state=state, facts=tuple(events)))


def _with_finish_fact(transition: Transition) -> Transition:
    """Announce the end of the match from the one transition that ends it.

    Every definition emits this fact so a client that reads only the published
    facts still sees the finish; the runtime reads the winner from
    :func:`outcome` and publishes its own ``match_finished`` event beside it. A
    transition that leaves the match running must not announce a finish, and a
    match can only end once, so the fact appears exactly once.
    """
    if not is_finished(transition.state):
        return transition
    finished = outcome(transition.state)
    winner = None if finished is None else finished.winner_seat
    return Transition(
        state=transition.state,
        facts=transition.facts
        + (Fact(name='match_finished', detail={'winner': winner}),),
    )


def _fresh_player() -> dict:
    return {
        'cash': STARTING_CASH,
        'position': board.GO_INDEX,
        'properties': [],
        'in_jail': False,
        'jail_turns': 0,
        # The decks of the held ``Get Out of Jail Free`` cards, because using
        # one returns it to the bottom of the deck it came from.
        'jail_cards': [],
        'eliminated': False,
    }


def _copy(state: Mapping) -> dict:
    return copy.deepcopy(dict(state))


def _require_phase(state: Mapping, phase: str) -> None:
    if state['phase'] != phase:
        raise ValueError(f'action not allowed in phase {state["phase"]!r}')


def _require_pending(state: Mapping, kind: str) -> Mapping:
    pending = state['pending']
    if not pending or pending.get('kind') != kind:
        raise ValueError(f'no {kind!r} decision is pending')
    return pending


def _throw(state, seat: str, rng, events):
    """Throw the two dice, record the faces and emit the fact.

    Used by the turn's own roll and by the card that makes the seat throw
    again, so both record the throw the same way.
    """
    faces = [rng.roll(DICE_SIDES) for _ in range(DICE_COUNT)]
    doubles = faces[0] == faces[1]
    state['last_roll'] = list(faces)
    events.append(
        Fact(
            name='roll_recorded',
            seat=seat,
            detail={'dice': list(faces), 'doubles': doubles},
        )
    )
    return faces, doubles


def _apply_roll(state: Mapping, seat: str, action, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_ROLL)
    if rng is None:
        raise ValueError('rolling requires a RandomSource')
    state = _copy(state)
    events = []
    faces, doubles = _throw(state, seat, rng, events)
    total = sum(faces)

    if state['players'][seat]['in_jail']:
        return _resolve_jail_roll(state, seat, faces, total, doubles, events, rng)

    if doubles:
        state['doubles_count'] += 1
        if state['doubles_count'] >= DOUBLES_TO_JAIL:
            # The third double goes straight to jail instead of moving.
            _send_to_jail(state, seat, 'three_doubles', events)
            _pass_turn(state, events)
            return Transition(state=state, facts=tuple(events))

    _move(state, seat, total, events)
    resolution = _resolve_landing(state, seat, faces, events, rng)
    return _finish_step(state, resolution, doubles, events)


def _resolve_jail_roll(state, seat, faces, total, doubles, events, rng) -> Transition:
    """Resolve a roll made from jail (S7)."""
    player = state['players'][seat]
    if doubles:
        player['in_jail'] = False
        player['jail_turns'] = 0
        events.append(Fact(name='left_jail', seat=seat, detail={'method': 'doubles'}))
        _move(state, seat, total, events)
        resolution = _resolve_landing(state, seat, faces, events, rng)
        # A double that opens the jail cell does not buy another turn.
        return _finish_step(state, resolution, False, events)

    player['jail_turns'] += 1
    if player['jail_turns'] < JAIL_TURNS_LIMIT:
        _pass_turn(state, events)
        return Transition(state=state, facts=tuple(events))

    if _pay(state, seat, JAIL_FINE, None, events):
        # The fine bankrupted the seat: it leaves jail only to leave the match.
        _pass_turn(state, events)
        return Transition(state=state, facts=tuple(events))
    player['in_jail'] = False
    player['jail_turns'] = 0
    events.append(Fact(name='left_jail', seat=seat, detail={'method': 'fine'}))
    _move(state, seat, total, events)
    resolution = _resolve_landing(state, seat, faces, events, rng)
    return _finish_step(state, resolution, False, events)


def _finish_step(state, resolution, extra: bool, events) -> Transition:
    """Close the movement step according to what the landing produced."""
    if resolution == 'decision':
        # The seat must decide before the turn can continue; whether the roll
        # was a double is kept so the extra turn still arrives afterwards.
        state['extra_roll'] = extra
        return Transition(state=state, facts=tuple(events))
    if resolution == 'jail':
        _pass_turn(state, events)
        return Transition(state=state, facts=tuple(events))
    _settle_turn(state, extra, events)
    return Transition(state=state, facts=tuple(events))


def _move(state, seat: str, total: int, events) -> int:
    """Move the token and pay the salary for passing or landing on GO."""
    player = state['players'][seat]
    start = player['position']
    passed_go = start + total >= board.BOARD_SIZE
    player['position'] = (start + total) % board.BOARD_SIZE
    if passed_go:
        player['cash'] += GO_SALARY
    events.append(
        Fact(
            name='moved',
            seat=seat,
            detail={
                'from': start,
                'to': player['position'],
                'passed_go': passed_go,
            },
        )
    )
    return player['position']


def _resolve_landing(state, seat: str, faces, events, rng, rent_rule=None):
    """Resolve the space the seat stopped on.

    Returns ``'decision'`` when the space opened a pending decision, ``'jail'``
    when the seat was sent to jail (which ends the turn in the act) and ``None``
    when the turn can simply continue. ``rent_rule`` carries a card's own rent
    rule down to :func:`_rent`; an ordinary landing passes ``None``.
    """
    index = state['players'][seat]['position']
    space = board.space_at(index)
    kind = space.kind

    if kind in _SILENT_KINDS:
        return None

    deck = cards.deck_for_space(index)
    if deck is not None:
        return _resolve_card(state, seat, _draw(state, seat, deck, events), faces, events, rng)

    if kind is board.SpaceKind.GO_TO_JAIL:
        _send_to_jail(state, seat, 'go_to_jail', events)
        return 'jail'

    if kind is board.SpaceKind.LUXURY_TAX:
        if not _pay(state, seat, LUXURY_TAX, None, events):
            events.append(
                Fact(
                    name='tax_paid',
                    seat=seat,
                    detail={'space': index, 'amount': LUXURY_TAX, 'option': 'fixed'},
                )
            )
        return None

    if kind is board.SpaceKind.INCOME_TAX:
        state['phase'] = PHASE_AWAITING_DECISION
        state['pending'] = {'kind': 'income_tax', 'space': index}
        return 'decision'

    owner = state['owners'].get(str(index))
    if owner is None:
        _offer_purchase(state, seat, index, events)
        return 'decision'

    if owner == seat:
        return None

    amount = _rent(state, space, owner, faces, rent_rule)
    if not _pay(state, seat, amount, owner, events):
        events.append(
            Fact(
                name='rent_paid',
                seat=seat,
                detail={
                    'from': seat,
                    'to': owner,
                    'space': index,
                    'amount': amount,
                },
            )
        )
    return None


def _offer_purchase(state, seat: str, index: int, events) -> None:
    """Leave the seat in the purchase decision for ``index``."""
    state['phase'] = PHASE_AWAITING_DECISION
    state['pending'] = {'kind': 'purchase', 'space': index}
    events.append(Fact(name='purchase_offered', seat=seat, detail={'space': index}))


def _draw(state, seat: str, deck: str, events):
    """Turn up the top card of ``deck`` and recycle it (S3).

    A ``Get Out of Jail Free`` card leaves the deck instead of going back to
    the bottom: the seat holds it until it is used, and using it is what
    returns it to its own deck.
    """
    order = list(state['decks'][deck])
    card = cards.card_for(order[0])
    state['decks'][deck] = order[1:] if card.effect is cards.JAIL_CARD else order[1:] + [card.id]
    state['last_card'] = {'deck': deck, 'id': card.id}
    events.append(
        Fact(
            name='card_drawn',
            seat=seat,
            detail={'deck': deck, 'id': card.id, 'title': card.title},
        )
    )
    return card


def _resolve_card(state, seat: str, card, faces, events, rng):
    """Apply one drawn card and resolve the space it leaves the token on."""
    effect = card.effect

    if effect == cards.ADVANCE:
        _advance_to(state, seat, card.space, events)
        return _resolve_landing(state, seat, faces, events, rng)

    if effect == cards.ADVANCE_NEAREST_RAILROAD:
        destination = _nearest_forward(
            state['players'][seat]['position'], board.RAILROAD_INDEXES
        )
        _advance_to(state, seat, destination, events)
        return _resolve_landing(
            state, seat, faces, events, rng, rent_rule=_RAILROAD_DOUBLED
        )

    if effect == cards.ADVANCE_NEAREST_UTILITY:
        destination = _nearest_forward(
            state['players'][seat]['position'], board.UTILITY_INDEXES
        )
        _advance_to(state, seat, destination, events)
        owner = state['owners'].get(str(destination))
        if owner is None:
            _offer_purchase(state, seat, destination, events)
            return 'decision'
        if owner == seat:
            return None
        throw, _ = _throw(state, seat, rng, events)
        events.append(
            Fact(name='card_roll', seat=seat, detail={'dice': list(throw)})
        )
        amount = CARD_UTILITY_MULTIPLIER * sum(throw)
        if not _pay(state, seat, amount, owner, events):
            events.append(
                Fact(
                    name='rent_paid',
                    seat=seat,
                    detail={
                        'from': seat,
                        'to': owner,
                        'space': destination,
                        'amount': amount,
                    },
                )
            )
        return None

    if effect == cards.GO_BACK_THREE:
        _go_back(state, seat, 3, events)
        return _resolve_landing(state, seat, faces, events, rng)

    if effect == cards.GO_TO_JAIL:
        _send_to_jail(state, seat, 'go_to_jail', events)
        return 'jail'

    if effect == cards.JAIL_CARD:
        state['players'][seat]['jail_cards'].append(card.id)
        events.append(
            Fact(name='jail_card_obtained', seat=seat, detail={'deck': card.deck})
        )
        return None

    if effect == cards.COLLECT_BANK:
        _card_collect(state, seat, card.amount, None, events)
        return None

    if effect == cards.PAY_BANK:
        _card_pay(state, seat, card.amount, None, events)
        return None

    if effect == cards.COLLECT_EACH_PLAYER:
        for other in solvent_seats(state):
            if other == seat:
                continue
            _card_collect(state, seat, card.amount, other, events)
        return None

    if effect == cards.PAY_EACH_PLAYER:
        for other in solvent_seats(state):
            if other == seat:
                continue
            if _card_pay(state, seat, card.amount, other, events):
                # The first share that cannot be paid is the bankruptcy and the
                # shares after it are never collected: the printed rules do not
                # cover several creditors at once (S10).
                break
        return None

    if effect == cards.REPAIRS:
        _card_pay(state, seat, _repairs_amount(state, seat, card), None, events)
        return None

    raise ValueError(f'unknown card effect: {effect!r}')


def _card_pay(state, seat: str, amount: int, creditor, events) -> bool:
    """Pay a card amount from ``seat``; ``True`` when it went bankrupt.

    A completed payment announces itself; a bankruptcy is announced by
    ``bankrupt``, which already carries the creditor.
    """
    if _pay(state, seat, amount, creditor, events):
        return True
    events.append(
        Fact(name='card_paid', seat=seat, detail={'amount': amount, 'to': creditor})
    )
    return False


def _card_collect(state, seat: str, amount: int, payer, events) -> bool:
    """Move a card amount to ``seat`` from ``payer`` (``None`` for the bank).

    Returns ``True`` when the payer went bankrupt over it.
    """
    if payer is not None and _pay(state, payer, amount, seat, events):
        return True
    if payer is None:
        state['players'][seat]['cash'] += amount
    events.append(
        Fact(
            name='card_collected',
            seat=seat,
            detail={'amount': amount, 'from': payer},
        )
    )
    return False


def _repairs_amount(state, seat: str, card) -> int:
    """What a repairs card costs the seat, from what the seat has built.

    Every owned street's level comes from the ``buildings`` map: no key reads
    as level 0, a level of 1 to 4 is that many houses and a hotel (level 5)
    counts at the card's hotel rate, never as its four houses.
    """
    buildings = state.get('buildings') or {}
    houses = 0
    hotels = 0
    for index in state['players'][seat]['properties']:
        level = buildings.get(str(index), 0)
        if level >= deeds.HOTEL_LEVEL:
            hotels += 1
        else:
            houses += level
    return card.per_house * houses + card.per_hotel * hotels


def _advance_to(state, seat: str, destination: int, events) -> int:
    """Move ``seat`` forward to ``destination``, paying the salary if it wraps."""
    distance = (destination - state['players'][seat]['position']) % board.BOARD_SIZE
    return _move(state, seat, distance, events)


def _go_back(state, seat: str, count: int, events) -> int:
    """Move ``seat`` back ``count`` spaces: no salary and no GO crossing."""
    player = state['players'][seat]
    start = player['position']
    player['position'] = (start - count) % board.BOARD_SIZE
    events.append(
        Fact(
            name='moved',
            seat=seat,
            detail={'from': start, 'to': player['position'], 'passed_go': False},
        )
    )
    return player['position']


def _nearest_forward(position: int, indexes) -> int:
    """Return the next index forward from ``position``, wrapping the circuit."""
    return min(indexes, key=lambda index: (index - position) % board.BOARD_SIZE)


def _settle_turn(state, extra: bool, events) -> None:
    """Close the seat's step: grant the extra roll or open the free window."""
    state['pending'] = None
    state['extra_roll'] = False
    seat = state['turn']
    if seat is None or state['players'][seat]['eliminated']:
        _pass_turn(state, events)
        return
    state['phase'] = PHASE_AWAITING_ROLL if extra else PHASE_MANAGING


def _pass_turn(state, events) -> None:
    """Hand the turn to the next seat still in the match."""
    ended = state['turn']
    if ended is not None:
        events.append(Fact(name='turn_ended', seat=ended, detail={}))
    state['doubles_count'] = 0
    state['extra_roll'] = False
    state['last_roll'] = None
    state['pending'] = None
    state['phase'] = PHASE_AWAITING_ROLL
    if len(solvent_seats(state)) <= 1:
        state['turn'] = None
        return
    state['turn'] = _next_solvent_seat(state, ended)


def _next_solvent_seat(state, after_seat):
    """Return the next seat in seat order that is still in the match."""
    seats = list(state['seats'])
    start = -1 if after_seat is None else seats.index(after_seat)
    for offset in range(1, len(seats) + 1):
        candidate = seats[(start + offset) % len(seats)]
        if not state['players'][candidate]['eliminated']:
            return candidate
    return None


def _send_to_jail(state, seat: str, reason: str, events) -> None:
    player = state['players'][seat]
    player['in_jail'] = True
    player['jail_turns'] = 0
    player['position'] = board.JAIL_INDEX
    state['doubles_count'] = 0
    events.append(Fact(name='sent_to_jail', seat=seat, detail={'reason': reason}))


def _rent(state, space, owner: str, faces, rule=None) -> int:
    """Return what ``owner`` charges a token stopping on ``space`` (S9).

    ``rule`` carries a card's own rent rule, which is not the landing rule: the
    nearest-railroad card doubles what the count of railroads held would charge.
    """
    if space.kind is board.SpaceKind.STREET:
        deed = deeds.deed_for(space.index)
        level = _level(state, space.index)
        if level >= 1:
            return deed.rent_for_level(level)
        # The set rent belongs to the unimproved street itself, never to the
        # group: a bare lot beside a built sibling still charges double (S6).
        if _owns_group(state, owner, space.group):
            return deed.set_rent
        return deed.base_rent
    if space.kind is board.SpaceKind.RAILROAD:
        owned = sum(
            1 for index in board.RAILROAD_INDEXES
            if state['owners'].get(str(index)) == owner
        )
        rent = deeds.RAILROAD_RENTS[owned - 1]
        return rent * 2 if rule is _RAILROAD_DOUBLED else rent
    owned = sum(
        1 for index in board.UTILITY_INDEXES
        if state['owners'].get(str(index)) == owner
    )
    return deeds.UTILITY_DICE_MULTIPLIERS[owned - 1] * sum(faces)


def _owns_group(state, seat: str, group) -> bool:
    """Whether ``seat`` holds every street of the colour group."""
    return all(
        state['owners'].get(str(index)) == seat
        for index in board.street_indexes(group)
    )


def _level(state: Mapping, index: int) -> int:
    """The development level of the street at ``index``, 0 when unbuilt."""
    return (state.get('buildings') or {}).get(str(index), 0)


def _group_levels(state: Mapping, index: int) -> tuple[int, ...]:
    """The development levels of every street of ``index``'s colour group."""
    return tuple(
        _level(state, other)
        for other in board.street_indexes(board.group_of(index))
    )


def _buildable_indexes(state: Mapping, seat: str) -> tuple[int, ...]:
    """The streets ``seat`` may build one level on right now (S3).

    Only a complete colour group builds, only its least developed street may
    rise so the build stays even, the cash has to cover the printed price, and
    the bank has to hold the piece: a house for levels 0-3, a hotel for level
    4. Level 5 is the ceiling and is never offered.
    """
    player = state['players'][seat]
    bank = state['bank']
    buildable = []
    for index in board.STREET_INDEXES:
        if state['owners'].get(str(index)) != seat:
            continue
        if not _owns_group(state, seat, board.group_of(index)):
            continue
        level = _level(state, index)
        if level != min(_group_levels(state, index)):
            continue
        if level >= deeds.HOTEL_LEVEL:
            continue
        deed = deeds.deed_for(index)
        if player['cash'] < deed.house_cost:
            continue
        if level == deeds.MAX_HOUSE_LEVEL:
            if bank['hotels'] < 1:
                continue
        elif bank['houses'] < 1:
            continue
        buildable.append(index)
    return tuple(buildable)


def _sellable_indexes(state: Mapping, seat: str) -> tuple[int, ...]:
    """The streets ``seat`` may sell one level from right now (S4).

    Only a built street of the seat's own complete group, and only its most
    developed one, so the group breaks down as evenly as it was built. Selling
    a hotel is the reverse of buying it: it needs four houses in the bank to
    leave the property at level 4.
    """
    sellable = []
    for index in board.STREET_INDEXES:
        if state['owners'].get(str(index)) != seat:
            continue
        level = _level(state, index)
        if level < 1 or level != max(_group_levels(state, index)):
            continue
        if (
            level == deeds.HOTEL_LEVEL
            and state['bank']['houses'] < deeds.MAX_HOUSE_LEVEL
        ):
            continue
        sellable.append(index)
    return tuple(sellable)


def _pay(state, seat: str, amount: int, creditor, events) -> bool:
    """Pay ``amount`` to ``creditor`` (or the bank, when ``None``).

    Returns ``True`` when the seat could not afford it and was eliminated in
    bankruptcy (S11): to another player it hands over everything it has, to the
    bank it hands over its cash and gives its properties back unowned.
    """
    player = state['players'][seat]
    if player['cash'] >= amount:
        player['cash'] -= amount
        if creditor is not None:
            state['players'][creditor]['cash'] += amount
        return False
    _eliminate(state, seat, creditor)
    events.append(
        Fact(name='bankrupt', seat=seat, detail={'creditor': creditor})
    )
    return True


def _eliminate(state, seat: str, creditor) -> None:
    """Take ``seat`` out of the match, settling its assets (S7, S11, S14).

    Every building goes back to the bank and its key leaves ``buildings``: a
    property is never transferred with buildings on it. When the creditor is a
    player it also collects the debtor's cash plus half of what the debtor had
    paid for those buildings; when the creditor is the bank (taxes, fines and
    the disconnection expulsion) the buildings simply return and nothing is
    paid, and the properties are left unowned as S11 and S14 already say.
    """
    player = state['players'][seat]
    if player['eliminated']:
        return
    refund = _return_buildings(state, player['properties'])
    if creditor is not None:
        state['players'][creditor]['cash'] += player['cash'] + refund
    player['cash'] = 0
    for index in list(player['properties']):
        if creditor is None:
            state['owners'].pop(str(index), None)
        else:
            state['owners'][str(index)] = creditor
            state['players'][creditor]['properties'].append(index)
    player['properties'] = []
    player['in_jail'] = False
    player['jail_turns'] = 0
    player['eliminated'] = True


def _return_buildings(state, indexes) -> int:
    """Return the buildings on ``indexes`` to the bank; return half their value."""
    buildings = state.setdefault('buildings', {})
    refund = 0
    for index in indexes:
        if not deeds.is_street(index):
            continue
        level = buildings.pop(str(index), 0)
        if level < 1:
            continue
        if level >= deeds.HOTEL_LEVEL:
            state['bank']['hotels'] += 1
        else:
            state['bank']['houses'] += level
        refund += deeds.development_cost(deeds.deed_for(index), level) // 2
    return refund


def _apply_pay_jail_fine(state: Mapping, seat: str, action, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_ROLL)
    player = state['players'][seat]
    if not player['in_jail'] or player['jail_turns'] >= JAIL_TURNS_LIMIT - 1:
        raise ValueError(f'{seat!r} cannot pay a jail fine right now')
    if player['cash'] < JAIL_FINE:
        raise ValueError(f'{seat!r} cannot afford the jail fine')
    state = _copy(state)
    player = state['players'][seat]
    player['cash'] -= JAIL_FINE
    player['in_jail'] = False
    player['jail_turns'] = 0
    return Transition(
        state=state,
        facts=(Fact(name='left_jail', seat=seat, detail={'method': 'fine'}),),
    )


def _apply_buy(state: Mapping, seat: str, action, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_DECISION)
    index = _require_pending(state, 'purchase')['space']
    price = deeds.purchase_price(index)
    if state['players'][seat]['cash'] < price:
        raise ValueError(f'{seat!r} cannot afford space {index}')
    state = _copy(state)
    events = []
    state['players'][seat]['cash'] -= price
    state['owners'][str(index)] = seat
    state['players'][seat]['properties'].append(index)
    events.append(
        Fact(name='property_bought', seat=seat, detail={'space': index, 'price': price})
    )
    _settle_turn(state, state['extra_roll'], events)
    return Transition(state=state, facts=tuple(events))


def _apply_decline(state: Mapping, seat: str, action, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_DECISION)
    index = _require_pending(state, 'purchase')['space']
    state = _copy(state)
    events = [Fact(name='purchase_declined', seat=seat, detail={'space': index})]
    # Declining no longer frees the space: it sends it to the bank's auction
    # (S1 of ``monopoly-auction.md``).
    _open_auction(state, seat, index, events)
    return Transition(state=state, facts=tuple(events))


def _open_auction(state, seat: str, index: int, events) -> None:
    """Send a declined property to the bank's auction (S1)."""
    state['phase'] = PHASE_AWAITING_BID
    state['pending'] = None
    state['auction'] = {
        'space': index,
        'high_bid': 0,
        'high_bidder': None,
        'passed': [],
    }
    events.append(Fact(name='auction_opened', seat=seat, detail={'space': index}))


def _apply_bid(state: Mapping, seat: str, action, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_BID)
    if seat not in eligible_bidders(state):
        raise ValueError(f'{seat!r} cannot bid right now')
    amount = _read_bid(state, seat, action)
    state = _copy(state)
    events = []
    space = state['auction']['space']
    state['auction']['high_bid'] = amount
    state['auction']['high_bidder'] = seat
    # A fresh bid reopens the auction for everyone who had stepped out (S3).
    state['auction']['passed'] = []
    events.append(
        Fact(name='auction_bid', seat=seat, detail={'space': space, 'amount': amount})
    )
    _resolve_auction_if_due(state, events)
    return Transition(state=state, facts=tuple(events))


def _apply_pass(state: Mapping, seat: str, action, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_BID)
    if seat not in eligible_bidders(state):
        raise ValueError(f'{seat!r} cannot pass right now')
    if state['auction']['high_bidder'] == seat:
        raise ValueError(f'{seat!r} holds the high bid and cannot withdraw it')
    state = _copy(state)
    events = []
    space = state['auction']['space']
    state['auction']['passed'] = list(state['auction']['passed']) + [seat]
    events.append(Fact(name='auction_passed', seat=seat, detail={'space': space}))
    _resolve_auction_if_due(state, events)
    return Transition(state=state, facts=tuple(events))


def _read_bid(state: Mapping, seat: str, action) -> int:
    """Return the bid ``action`` carries, or raise when it is off the ladder."""
    try:
        amount = int(action.value)
    except (TypeError, ValueError):
        raise ValueError(f'invalid bid: {action.value!r}') from None
    if amount not in _bid_amounts(state, seat):
        raise ValueError(f'{seat!r} cannot bid {amount}')
    return amount


def _resolve_auction_if_due(state, events) -> bool:
    """Close the auction when S5 says it is over; returns whether it closed."""
    auction = state['auction']
    bidder = auction['high_bidder']
    remaining = eligible_bidders(state)
    if bidder is not None:
        if remaining != (bidder,):
            return False
        return _finish_auction(state, bidder, auction['high_bid'], events)
    if remaining:
        return False
    return _finish_auction(state, None, 0, events)


def _finish_auction(state, winner, amount: int, events) -> bool:
    """Hand the property to the winner or back to the bank, and resume the turn."""
    space = state['auction']['space']
    turn_seat = state['turn']
    state['auction'] = None
    if winner is None:
        events.append(
            Fact(name='auction_unsold', seat=turn_seat, detail={'space': space})
        )
    else:
        state['players'][winner]['cash'] -= amount
        state['owners'][str(space)] = winner
        state['players'][winner]['properties'].append(space)
        events.append(
            Fact(
                name='auction_won',
                seat=winner,
                detail={'space': space, 'amount': amount},
            )
        )
    # The turn never left its owner while the auction was open, so this puts it
    # back exactly where it was: the extra roll of a double still stands.
    _settle_turn(state, state['extra_roll'], events)
    return True


def _apply_income_tax_fixed(state: Mapping, seat: str, action, rng) -> Transition:
    return _pay_income_tax(state, seat, 'fixed', INCOME_TAX_FIXED)


def _apply_income_tax_percent(state: Mapping, seat: str, action, rng) -> Transition:
    worth = total_worth(state, seat)
    # The match has no cents, and the printed rule rounds in no direction, so
    # the only clearly wrong option is paying less than a tenth (S10).
    amount = -(-worth // INCOME_TAX_PERCENT)
    return _pay_income_tax(state, seat, 'percent', amount)


def _pay_income_tax(state: Mapping, seat: str, option: str, amount: int) -> Transition:
    _require_phase(state, PHASE_AWAITING_DECISION)
    _require_pending(state, 'income_tax')
    state = _copy(state)
    events = []
    if not _pay(state, seat, amount, None, events):
        events.append(
            Fact(
                name='tax_paid',
                seat=seat,
                detail={
                    'space': board.INCOME_TAX_INDEX,
                    'amount': amount,
                    'option': option,
                },
            )
        )
    _settle_turn(state, state['extra_roll'], events)
    return Transition(state=state, facts=tuple(events))


def _apply_use_jail_card(state: Mapping, seat: str, action, rng) -> Transition:
    """Use a held ``Get Out of Jail Free`` card: release, then throw normally.

    The card goes back to the bottom of the deck it came from, and the seat is
    left in ``awaiting_roll``: leaving jail with the card does not consume the
    turn, exactly like paying the fine.
    """
    _require_phase(state, PHASE_AWAITING_ROLL)
    player = state['players'][seat]
    if not player['in_jail'] or not player['jail_cards']:
        raise ValueError(f'{seat!r} holds no jail card to use')
    state = _copy(state)
    player = state['players'][seat]
    card = cards.card_for(player['jail_cards'].pop(0))
    player['in_jail'] = False
    player['jail_turns'] = 0
    state['decks'][card.deck] = list(state['decks'][card.deck]) + [card.id]
    return Transition(
        state=state,
        facts=(Fact(name='jail_card_used', seat=seat, detail={'deck': card.deck}),),
    )


def _apply_end_turn(state: Mapping, seat: str, action, rng) -> Transition:
    _require_phase(state, PHASE_MANAGING)
    state = _copy(state)
    events = []
    _pass_turn(state, events)
    return Transition(state=state, facts=tuple(events))


def _read_offered_index(state: Mapping, seat: str, action, offered) -> int:
    """Return the space ``action`` names, or raise when it was not offered."""
    try:
        index = int(action.value)
    except (TypeError, ValueError):
        raise ValueError(f'invalid space: {action.value!r}') from None
    if index not in offered:
        raise ValueError(f'{seat!r} cannot act on space {index}')
    return index


def _apply_build(state: Mapping, seat: str, action, rng) -> Transition:
    """Raise one development level on an offered street (S3)."""
    _require_phase(state, PHASE_MANAGING)
    index = _read_offered_index(state, seat, action, _buildable_indexes(state, seat))
    deed = deeds.deed_for(index)
    state = _copy(state)
    state.setdefault('buildings', {})
    level = _level(state, index) + 1
    state['players'][seat]['cash'] -= deed.house_cost
    state['buildings'][str(index)] = level
    if level == deeds.HOTEL_LEVEL:
        # The hotel's four houses go back to the bank, so they are not lost.
        state['bank']['hotels'] -= 1
        state['bank']['houses'] += deeds.MAX_HOUSE_LEVEL
    else:
        state['bank']['houses'] -= 1
    return Transition(
        state=state,
        facts=(
            Fact(
                name='building_bought',
                seat=seat,
                detail={'space': index, 'level': level, 'price': deed.house_cost},
            ),
        ),
    )


def _apply_sell(state: Mapping, seat: str, action, rng) -> Transition:
    """Lower one development level on an offered street (S4)."""
    _require_phase(state, PHASE_MANAGING)
    index = _read_offered_index(state, seat, action, _sellable_indexes(state, seat))
    deed = deeds.deed_for(index)
    state = _copy(state)
    level = _level(state, index)
    price = deeds.sell_back(deed)
    new_level = level - 1
    state['players'][seat]['cash'] += price
    if level == deeds.HOTEL_LEVEL:
        # Selling a hotel reverses buying it: the hotel returns and the four
        # houses it left behind have to come back out of the bank.
        state['bank']['hotels'] += 1
        state['bank']['houses'] -= deeds.MAX_HOUSE_LEVEL
    else:
        state['bank']['houses'] += 1
    if new_level == 0:
        state['buildings'].pop(str(index), None)
    else:
        state['buildings'][str(index)] = new_level
    return Transition(
        state=state,
        facts=(
            Fact(
                name='building_sold',
                seat=seat,
                detail={'space': index, 'level': new_level, 'price': price},
            ),
        ),
    )


_HANDLERS = {
    ACTION_ROLL: _apply_roll,
    ACTION_BID: _apply_bid,
    ACTION_PASS: _apply_pass,
    ACTION_USE_JAIL_CARD: _apply_use_jail_card,
    ACTION_PAY_JAIL_FINE: _apply_pay_jail_fine,
    ACTION_BUY: _apply_buy,
    ACTION_DECLINE: _apply_decline,
    ACTION_PAY_INCOME_TAX_FIXED: _apply_income_tax_fixed,
    ACTION_PAY_INCOME_TAX_PERCENT: _apply_income_tax_percent,
    ACTION_END_TURN: _apply_end_turn,
    ACTION_BUILD: _apply_build,
    ACTION_SELL: _apply_sell,
}
