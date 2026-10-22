"""Pure rules for ``monopoly``, the classic property trading game (S5-S12).

Plain data transforms: the rules never mutate their inputs and never import
Django, DRF or Channels. The mutable match state lives in the caller and is
threaded through as an opaque mapping, exactly like ``ta_te_ti``.

The rules cover the playable core and the increments that followed it: dice,
movement, GO, purchases, the auction a decline opens, rents by development
level, house and hotel building with the bank's finite stock, both decks,
taxes, jail, bankruptcy, elimination, the end of the match, mortgages with the
raise-cash window, and trading between seats. Three deviations from the print are
deliberate and documented: when the bank's stock of houses or hotels runs out
the build option is simply not offered, and the print's scarcity auction of the
last houses and hotels is **not** implemented -- the first seat that asks takes
the piece at its printed price, so turn order is what settles it (S13 of
``monopoly-building.md``) -- and the properties a bankrupt seat turns over to
the bank are left unowned instead of being auctioned at once, exactly like a
space nobody ever bought (S11 of ``monopoly.md``).

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
PHASE_RAISING_CASH = 'raising_cash'

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
ACTION_MORTGAGE = 'mortgage'
ACTION_UNMORTGAGE = 'unmortgage'
ACTION_PAY_DEBT = 'pay_debt'
ACTION_DECLARE_BANKRUPTCY = 'declare_bankruptcy'

# The four trade actions (S5). They are available in every phase, so they are
# never gated by ``_require_phase``; their own handlers decide who may act.
ACTION_PROPOSE = 'propose'
ACTION_ACCEPT = 'accept'
ACTION_REJECT = 'reject'
ACTION_WITHDRAW = 'withdraw'

# The canonical composed value of ``propose`` (S3), published in its prompt so
# the panel can compose a value the engine accepts.
PROPOSE_GRAMMAR = 'to=<seat>;give=<idx,idx>;cash=<int>|want=<idx,idx>;cash=<int>'
PROPOSE_PROMPT = f'Proponé un trato con la forma {PROPOSE_GRAMMAR}.'

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
        'mortgaged': {},
        'bank': {'houses': STARTING_HOUSES, 'hotels': STARTING_HOTELS},
        'decks': _deck_order(decks),
        'last_card': None,
        'auction': None,
        'offers': {},
        'offer_seq': 0,
        'phase': PHASE_AWAITING_ROLL,
        'turn': first_seat,
        'last_roll': None,
        'pending': None,
        'debt': None,
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

    While the match runs **every solvent seat** may act, because a trade can be
    proposed at any moment, out of turn included (D1). The phase's own actions
    are still gated to the phase's actor by :func:`legal_actions`, so an
    off-turn seat only ever receives the trade actions. The order is not
    significant to the runtime; this returns seat order so a test can read it
    deterministically.
    """
    if is_finished(state):
        return ()
    return solvent_seats(state)


def _phase_actors(state: Mapping) -> tuple[str, ...]:
    """The seats a phase of its own gives actions to, before any trade.

    This is the old single-seat (and auction) gate, split out so
    :func:`active_seats` can add offer participants without also handing them
    the phase's own actions.
    """
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
    mortgageable = _mortgageable_indexes(state, seat)
    if mortgageable:
        specs.append(
            ActionSpec(
                name=ACTION_MORTGAGE,
                options=tuple(str(index) for index in mortgageable),
                prompt='Hipotecá',
            )
        )
    unmortgageable = _unmortgageable_indexes(state, seat)
    if unmortgageable:
        specs.append(
            ActionSpec(
                name=ACTION_UNMORTGAGE,
                options=tuple(str(index) for index in unmortgageable),
                prompt='Levantá la hipoteca',
            )
        )
    specs.append(ActionSpec(name=ACTION_END_TURN, prompt='Terminá tu turno.'))
    return tuple(specs)


def _raising_cash_specs(state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
    """The debt window's actions: sell, mortgage, pay the debt or bankrupt (S7).

    ``build``, ``unmortgage`` and ``end_turn`` are deliberately absent: the
    window exists to raise cash, and the turn never ends with an open debt.
    ``pay_debt`` is offered only once the cash covers the whole amount; closing
    the window grants and removes nothing.
    """
    specs = []
    sellable = _sellable_indexes(state, seat)
    if sellable:
        specs.append(
            ActionSpec(
                name=ACTION_SELL,
                options=tuple(str(index) for index in sellable),
                prompt='Vendé',
            )
        )
    mortgageable = _mortgageable_indexes(state, seat)
    if mortgageable:
        specs.append(
            ActionSpec(
                name=ACTION_MORTGAGE,
                options=tuple(str(index) for index in mortgageable),
                prompt='Hipotecá',
            )
        )
    debt = state.get('debt') or {}
    if debt and state['players'][seat]['cash'] >= debt.get('amount', 0):
        specs.append(ActionSpec(name=ACTION_PAY_DEBT, prompt='Pagá la deuda.'))
    specs.append(
        ActionSpec(name=ACTION_DECLARE_BANKRUPTCY, prompt='Declarate en bancarrota.')
    )
    return tuple(specs)


def offers_in_id_order(state: Mapping) -> list:
    """Return the live offers sorted by numeric id, tolerating old states."""
    offers = state.get('offers') or {}
    return [offers[offer_id] for offer_id in sorted(offers, key=int)]


def _offer_ids_in_order(offers: list) -> tuple[str, ...]:
    return tuple(offer['id'] for offer in offers)


def _is_debtor(state: Mapping, seat: str) -> bool:
    """Whether ``seat`` is the seat whose debt is still open (S7)."""
    debt = state.get('debt')
    return debt is not None and debt.get('seat') == seat


def _require_not_debtor(state: Mapping, seat: str) -> None:
    """A seat with an open debt never trades: it must resolve the debt."""
    if _is_debtor(state, seat):
        raise ValueError(f'{seat!r} cannot trade while a debt is open')


def _interest_total(state: Mapping, indexes) -> int:
    """The 10 % interest a receiver owes for its mortgaged properties (S6)."""
    mortgaged = state.get('mortgaged') or {}
    return sum(
        deeds.mortgage_lift_cost(index) - deeds.mortgage_value(index)
        for index in indexes
        if mortgaged.get(str(index))
    )


def offer_is_valid(state: Mapping, offer: Mapping) -> bool:
    """Whether ``offer``'s terms are legal on the current state (S4).

    The same function gates ``accept`` and paints the view's ``valid`` flag, so
    a stale offer cannot be accepted through a panel that was rendered from an
    older state. Every index is read against the real state, never against
    what the view published.
    """
    give = offer['give']
    want = offer['want']
    give_properties = list(give['properties'])
    want_properties = list(want['properties'])
    proposer = offer['proposer']
    receiver = offer['receiver']

    if proposer not in state['players'] or state['players'][proposer]['eliminated']:
        return False
    if receiver not in state['players'] or state['players'][receiver]['eliminated']:
        return False
    if len(set(give_properties)) != len(give_properties):
        return False
    if len(set(want_properties)) != len(want_properties):
        return False
    if set(give_properties) & set(want_properties):
        return False

    for index in give_properties:
        if state['owners'].get(str(index)) != proposer:
            return False
    for index in want_properties:
        if state['owners'].get(str(index)) != receiver:
            return False

    # No street of a built colour group may be traded: the print sends the
    # buildings to the bank first. A railroad or a utility has no group and
    # satisfies the condition on its own.
    for index in give_properties + want_properties:
        group = board.group_of(index)
        if group is not None and any(
            _level(state, other) > 0 for other in board.street_indexes(group)
        ):
            return False

    if (
        not give_properties
        and not want_properties
        and give['cash'] <= 0
        and want['cash'] <= 0
    ):
        return False

    proposer_player = state['players'][proposer]
    receiver_player = state['players'][receiver]
    if proposer_player['cash'] < give['cash']:
        return False
    if receiver_player['cash'] < want['cash']:
        return False

    # The cash each side has *after* the exchange has to cover the interest of
    # what it receives (S4/S6): nobody keeps what they cannot sustain.
    proposer_after = proposer_player['cash'] - give['cash'] + want['cash']
    receiver_after = receiver_player['cash'] - want['cash'] + give['cash']
    if proposer_after < _interest_total(state, want_properties):
        return False
    if receiver_after < _interest_total(state, give_properties):
        return False
    return True


def _trade_specs(state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
    """The trade actions ``seat`` may take: propose, accept/reject, withdraw.

    ``propose`` is always available to a seat that can act, while ``accept``,
    ``reject`` and ``withdraw`` list the ids of the offers this seat receives
    or made, in id order. ``accept`` only names the offers S4 still declares
    legal.
    """
    if _is_debtor(state, seat):
        return ()
    offers = offers_in_id_order(state)
    received = [offer for offer in offers if offer['receiver'] == seat]
    sent = [offer for offer in offers if offer['proposer'] == seat]

    specs = [ActionSpec(name=ACTION_PROPOSE, freeform=True, prompt=PROPOSE_PROMPT)]
    acceptable = tuple(
        offer['id'] for offer in received if offer_is_valid(state, offer)
    )
    if acceptable:
        specs.append(
            ActionSpec(name=ACTION_ACCEPT, options=acceptable, prompt='Aceptá un trato.')
        )
    if received:
        specs.append(
            ActionSpec(
                name=ACTION_REJECT,
                options=_offer_ids_in_order(received),
                prompt='Rechazá un trato.',
            )
        )
    if sent:
        specs.append(
            ActionSpec(
                name=ACTION_WITHDRAW,
                options=_offer_ids_in_order(sent),
                prompt='Retirá un trato.',
            )
        )
    return tuple(specs)


def _parse_field(chunk: str, key: str) -> str:
    """Return the value of ``key`` in ``chunk`` (``key=value``), or raise."""
    prefix = f'{key}='
    if not chunk.startswith(prefix):
        raise ValueError(f'invalid proposal field: {chunk!r}')
    return chunk[len(prefix):]


def _parse_indexes(raw: str) -> list[int]:
    """Parse a comma-separated list of board indexes, possibly empty."""
    if raw == '':
        return []
    indexes = []
    for piece in raw.split(','):
        if not piece.isdigit():
            raise ValueError(f'invalid property index: {piece!r}')
        index = int(piece)
        if not 0 <= index < board.BOARD_SIZE:
            raise ValueError(f'property index out of the board: {index!r}')
        if index in indexes:
            raise ValueError(f'repeated property index: {index!r}')
        indexes.append(index)
    return sorted(indexes)


def _parse_amount(raw: str) -> int:
    """Parse a never-empty non-negative whole amount."""
    if not raw.isdigit():
        raise ValueError(f'invalid cash amount: {raw!r}')
    return int(raw)


def _parse_proposal(state: Mapping, seat: str, value) -> dict:
    """Parse the composed ``propose`` value into ``{receiver, give, want}``.

    The grammar is S3's: ``to=<seat>;give=<idx,idx>;cash=<int>|<same for want>``.
    Any other shape raises ``ValueError``; the runtime turns that into a client
    error because the spec is freeform.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f'invalid proposal: {value!r}')
    if ' ' in value:
        raise ValueError(f'proposal contains spaces: {value!r}')
    give_part, separator, want_part = value.partition('|')
    if not separator or '|' in want_part:
        raise ValueError(f'invalid proposal: {value!r}')

    give_chunks = give_part.split(';')
    want_chunks = want_part.split(';')
    if len(give_chunks) != 3 or len(want_chunks) != 2:
        raise ValueError(f'invalid proposal: {value!r}')

    receiver = _parse_field(give_chunks[0], 'to')
    give = {
        'properties': _parse_indexes(_parse_field(give_chunks[1], 'give')),
        'cash': _parse_amount(_parse_field(give_chunks[2], 'cash')),
    }
    want = {
        'properties': _parse_indexes(_parse_field(want_chunks[0], 'want')),
        'cash': _parse_amount(_parse_field(want_chunks[1], 'cash')),
    }
    if receiver == seat:
        raise ValueError(f'{seat!r} cannot propose a trade to itself')
    if receiver not in solvent_seats(state):
        raise ValueError(f'{receiver!r} is not a solvent seat')
    return {'receiver': receiver, 'give': give, 'want': want}


def _require_offer(state: Mapping, offer_id) -> dict:
    """Return the live offer ``offer_id`` names, or raise."""
    offers = state.get('offers') or {}
    if not isinstance(offer_id, str) or offer_id not in offers:
        raise ValueError(f'unknown offer: {offer_id!r}')
    return offers[offer_id]


def _transfer_property(state, index: int, from_seat: str, to_seat: str) -> None:
    """Move a property between two seats, ownership map and list together."""
    state['owners'][str(index)] = to_seat
    state['players'][from_seat]['properties'].remove(index)
    state['players'][to_seat]['properties'].append(index)


def _charge_trade_interest(state, payer: str, indexes, events) -> None:
    """Charge ``payer`` 10 % of each mortgaged property it received (S6).

    The rounding is the same ceiling of a tenth of the printed mortgage value
    the mortgage increment uses, announced with ``reason: 'trade'``.
    """
    mortgaged = state.get('mortgaged') or {}
    for index in sorted(indexes):
        if not mortgaged.get(str(index)):
            continue
        amount = deeds.mortgage_lift_cost(index) - deeds.mortgage_value(index)
        state['players'][payer]['cash'] -= amount
        events.append(
            Fact(
                name='interest_paid',
                seat=payer,
                detail={'space': index, 'amount': amount, 'reason': 'trade'},
            )
        )


def _settle_trade(state, offer: Mapping, events) -> None:
    """Exchange the properties and the cash of an accepted offer (S6)."""
    proposer = offer['proposer']
    receiver = offer['receiver']
    give = offer['give']
    want = offer['want']

    state['players'][proposer]['cash'] += want['cash'] - give['cash']
    state['players'][receiver]['cash'] += give['cash'] - want['cash']
    for index in give['properties']:
        _transfer_property(state, index, proposer, receiver)
    for index in want['properties']:
        _transfer_property(state, index, receiver, proposer)

    # Each side pays the bank the 10 % interest of the mortgaged properties it
    # receives (S6); S4 already proved the post-exchange cash covers it.
    _charge_trade_interest(state, proposer, want['properties'], events)
    _charge_trade_interest(state, receiver, give['properties'], events)

    offers = dict(state.get('offers') or {})
    offers.pop(offer['id'], None)
    state['offers'] = offers
    events.append(
        Fact(name='offer_accepted', seat=receiver, detail={'offer': offer['id']})
    )
    events.append(
        Fact(
            name='trade_settled',
            seat=receiver,
            detail={
                'offer': offer['id'],
                'proposer': proposer,
                'receiver': receiver,
            },
        )
    )


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
    """Return the actions ``seat`` may take right now, and nothing else.

    The phase's own actions are appended to the trade actions of the offers the
    seat is a party to, never replaced by them: the seat on turn negotiates
    without losing ``roll``/``buy``/``end_turn`` (S5).
    """
    if is_finished(state) or seat not in state['players']:
        return ()
    if seat not in active_seats(state):
        return ()
    return _phase_specs(state, seat) + _trade_specs(state, seat)


def _phase_specs(state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
    """The phase's own actions for ``seat``, excluding the trade actions.

    A seat that only joins through an offer is not the phase's actor and must
    not receive the turn's actions; only the seat on turn (or an auction's
    eligible bidder) does.
    """
    player = state['players'][seat]
    phase = state['phase']
    if phase == PHASE_AWAITING_BID:
        return _bid_specs(state, seat)
    if seat not in _phase_actors(state):
        return ()
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

    if phase == PHASE_RAISING_CASH:
        return _raising_cash_specs(state, seat)

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
    handler = _HANDLERS.get(action.name)
    if handler is None:
        raise ValueError(f'unknown action: {action.name!r}')
    if action.name not in {spec.name for spec in legal_actions(state, seat)}:
        # Every solvent seat is active, so the phase gate cannot rely on
        # ``active_seats`` alone: the engine accepts only an action it actually
        # offered this seat, and the phase's actions belong to its actor.
        raise ValueError(f'{seat!r} cannot act right now')
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
        _eliminate(state, seat, None, events)
        events.append(Fact(name='seat_abandoned', seat=seat, detail={}))
    state['abandoned_seat'] = seat
    if state.get('debt') is not None and state['debt']['creditor'] == seat:
        # The recipient left the match, so the money the debt carries leaves
        # with it: the debtor ends up owing the bank, never an eliminated seat.
        state['debt']['creditor'] = None

    if len(solvent_seats(state)) <= 1:
        state['ended_by_abandon'] = True
        state['turn'] = None
        state['pending'] = None
        state['extra_roll'] = False
        state['auction'] = None
        state['debt'] = None
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
    # A finished match keeps no negotiation open (S7): every offer dies with it.
    transition.state['offers'] = {}
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


def _require_phase(state: Mapping, *phases: str) -> None:
    if state['phase'] not in phases:
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
    resolution = _resolve_landing(state, seat, faces, events, rng, extra=doubles)
    return _finish_step(state, resolution, doubles, events)


def _resolve_jail_roll(state, seat, faces, total, doubles, events, rng) -> Transition:
    """Resolve a roll made from jail (S7)."""
    player = state['players'][seat]
    if doubles:
        player['in_jail'] = False
        player['jail_turns'] = 0
        events.append(Fact(name='left_jail', seat=seat, detail={'method': 'doubles'}))
        _move(state, seat, total, events)
        resolution = _resolve_landing(state, seat, faces, events, rng, extra=False)
        # A double that opens the jail cell does not buy another turn.
        return _finish_step(state, resolution, False, events)

    player['jail_turns'] += 1
    if player['jail_turns'] < JAIL_TURNS_LIMIT:
        _pass_turn(state, events)
        return Transition(state=state, facts=tuple(events))

    if player['cash'] < JAIL_FINE:
        # The third-turn fine cannot be paid: the window opens with the throw
        # saved so paying resumes the movement with exactly these faces (S8).
        _open_debt(
            state,
            seat,
            JAIL_FINE,
            None,
            {'kind': 'jail_fine', 'faces': list(faces)},
            None,
            events,
        )
        return Transition(state=state, facts=tuple(events))
    player['cash'] -= JAIL_FINE
    player['in_jail'] = False
    player['jail_turns'] = 0
    events.append(Fact(name='left_jail', seat=seat, detail={'method': 'fine'}))
    _move(state, seat, total, events)
    resolution = _resolve_landing(state, seat, faces, events, rng, extra=False)
    return _finish_step(state, resolution, False, events)


def _finish_step(state, resolution, extra: bool, events) -> Transition:
    """Close the movement step according to what the landing produced."""
    if state.get('debt') is not None:
        # An open debt owns the phase: the step pauses and resumes on payment.
        return Transition(state=state, facts=tuple(events))
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


def _resolve_landing(state, seat: str, faces, events, rng, rent_rule=None, extra=False):
    """Resolve the space the seat stopped on.

    Returns ``'decision'`` when the space opened a pending decision, ``'jail'``
    when the seat was sent to jail (which ends the turn in the act) and ``None``
    when the turn can simply continue. ``rent_rule`` carries a card's own rent
    rule down to :func:`_rent`; an ordinary landing passes ``None``. ``extra``
    is the extra-roll flag of the roll being resolved, saved in a debt so the
    payment resumes with the same continuation (S8).
    """
    index = state['players'][seat]['position']
    space = board.space_at(index)
    kind = space.kind

    if kind in _SILENT_KINDS:
        return None

    deck = cards.deck_for_space(index)
    if deck is not None:
        return _resolve_card(
            state, seat, _draw(state, seat, deck, events), faces, events, rng, extra
        )

    if kind is board.SpaceKind.GO_TO_JAIL:
        _send_to_jail(state, seat, 'go_to_jail', events)
        return 'jail'

    if kind is board.SpaceKind.LUXURY_TAX:
        _charge_step(
            state,
            seat,
            LUXURY_TAX,
            None,
            Fact(
                name='tax_paid',
                seat=seat,
                detail={'space': index, 'amount': LUXURY_TAX, 'option': 'fixed'},
            ),
            extra,
            events,
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

    if _is_mortgaged(state, index):
        # A mortgaged property charges nothing: no rent, no fact (S5).
        return None

    amount = _rent(state, space, owner, faces, rent_rule)
    _charge_step(
        state,
        seat,
        amount,
        owner,
        Fact(
            name='rent_paid',
            seat=seat,
            detail={'from': seat, 'to': owner, 'space': index, 'amount': amount},
        ),
        extra,
        events,
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


def _resolve_card(state, seat: str, card, faces, events, rng, extra=False):
    """Apply one drawn card and resolve the space it leaves the token on."""
    effect = card.effect

    if effect == cards.ADVANCE:
        _advance_to(state, seat, card.space, events)
        return _resolve_landing(state, seat, faces, events, rng, extra=extra)

    if effect == cards.ADVANCE_NEAREST_RAILROAD:
        destination = _nearest_forward(
            state['players'][seat]['position'], board.RAILROAD_INDEXES
        )
        _advance_to(state, seat, destination, events)
        return _resolve_landing(
            state, seat, faces, events, rng, rent_rule=_RAILROAD_DOUBLED, extra=extra
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
        if _is_mortgaged(state, destination):
            # The card reaches a mortgaged utility: it charges nothing (S5).
            return None
        throw, _ = _throw(state, seat, rng, events)
        events.append(
            Fact(name='card_roll', seat=seat, detail={'dice': list(throw)})
        )
        amount = CARD_UTILITY_MULTIPLIER * sum(throw)
        _charge_step(
            state,
            seat,
            amount,
            owner,
            Fact(
                name='rent_paid',
                seat=seat,
                detail={
                    'from': seat,
                    'to': owner,
                    'space': destination,
                    'amount': amount,
                },
            ),
            extra,
            events,
        )
        return None

    if effect == cards.GO_BACK_THREE:
        _go_back(state, seat, 3, events)
        return _resolve_landing(state, seat, faces, events, rng, extra=extra)

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
        _charge_step(
            state,
            seat,
            card.amount,
            None,
            Fact(
                name='card_paid',
                seat=seat,
                detail={'amount': card.amount, 'to': None},
            ),
            extra,
            events,
        )
        return None

    if effect == cards.COLLECT_EACH_PLAYER:
        for other in solvent_seats(state):
            if other == seat:
                continue
            _card_collect(state, seat, card.amount, other, events)
        return None

    if effect == cards.PAY_EACH_PLAYER:
        others = [other for other in solvent_seats(state) if other != seat]
        _continue_card_shares(state, seat, card.amount, others, extra, events)
        return None

    if effect == cards.REPAIRS:
        amount = _repairs_amount(state, seat, card)
        _charge_step(
            state,
            seat,
            amount,
            None,
            Fact(
                name='card_paid',
                seat=seat,
                detail={'amount': amount, 'to': None},
            ),
            extra,
            events,
        )
        return None

    raise ValueError(f'unknown card effect: {effect!r}')


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
    if state.get('debt') is not None:
        # The debt owns the phase and the continuation until it is settled (S7).
        return
    state['pending'] = None
    state['extra_roll'] = False
    seat = state['turn']
    if seat is None or state['players'][seat]['eliminated']:
        _pass_turn(state, events)
        return
    state['phase'] = PHASE_AWAITING_ROLL if extra else PHASE_MANAGING


def _pass_turn(state, events) -> None:
    """Hand the turn to the next seat still in the match.

    A debt never survives a turn change: the window is closed defensively here
    so no stale record can leak into another seat's turn (S7).
    """
    state['debt'] = None
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
    A mortgaged property charges nothing at all (S5).
    """
    if _is_mortgaged(state, space.index):
        return 0
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


def _is_mortgaged(state: Mapping, index: int) -> bool:
    """Whether the space at ``index`` is mortgaged (S2).

    The read tolerates a match saved before this increment, which has no
    ``mortgaged`` key at all, exactly like ``buildings``.
    """
    return bool((state.get('mortgaged') or {}).get(str(index)))


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
    mortgaged = state.get('mortgaged') or {}
    buildable = []
    for index in board.STREET_INDEXES:
        if state['owners'].get(str(index)) != seat:
            continue
        if not _owns_group(state, seat, board.group_of(index)):
            continue
        if any(
            mortgaged.get(str(other))
            for other in board.street_indexes(board.group_of(index))
        ):
            # A group with any mortgaged property cannot be built on (S6).
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


def _mortgageable_indexes(state: Mapping, seat: str) -> tuple[int, ...]:
    """The spaces ``seat`` may mortgage right now (S3).

    A space is mortgageable when it is purchasable, its owner is the seat, it
    is not already mortgaged, and no street of its colour group holds a
    building. Railroads and utilities have no colour group, so the last
    condition is vacuously true for them.
    """
    mortgaged = state.get('mortgaged') or {}
    indexes = []
    for index in board.PURCHASABLE_INDEXES:
        if state['owners'].get(str(index)) != seat:
            continue
        if mortgaged.get(str(index)):
            continue
        group = board.group_of(index)
        if group is not None and any(
            _level(state, other) > 0
            for other in board.street_indexes(group)
        ):
            continue
        indexes.append(index)
    return tuple(indexes)


def _unmortgageable_indexes(state: Mapping, seat: str) -> tuple[int, ...]:
    """The mortgaged spaces ``seat`` may lift right now (S4).

    Only the seat's own mortgaged spaces whose lift cost the cash covers, in
    board order, so lifting can never be offered as a way to go into debt.
    """
    mortgaged = state.get('mortgaged') or {}
    cash = state['players'][seat]['cash']
    return tuple(
        index
        for index in board.PURCHASABLE_INDEXES
        if state['owners'].get(str(index)) == seat
        and mortgaged.get(str(index))
        and deeds.mortgage_lift_cost(index) <= cash
    )


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


def _open_debt(state, seat, amount, creditor, resume, fact, events) -> None:
    """Open the raising-cash window with the unpaid charge (S7).

    ``resume`` is the internal recipe for continuing the interrupted step and
    ``fact`` is the charge the payment would have emitted; neither is published.
    """
    state['debt'] = {
        'seat': seat,
        'creditor': creditor,
        'amount': amount,
        'resume': resume,
        'fact': fact,
    }
    state['phase'] = PHASE_RAISING_CASH
    events.append(
        Fact(
            name='debt_incurred',
            seat=seat,
            detail={'amount': amount, 'creditor': creditor},
        )
    )


def _charge_step(state, seat, amount, creditor, fact, extra, events) -> bool:
    """Settle a movement-step charge, opening a debt when the cash is short."""
    player = state['players'][seat]
    if player['cash'] >= amount:
        player['cash'] -= amount
        if creditor is not None:
            state['players'][creditor]['cash'] += amount
        events.append(fact)
        return True
    _open_debt(
        state,
        seat,
        amount,
        creditor,
        {'kind': 'settle_step', 'extra': extra},
        {'name': fact.name, 'seat': fact.seat, 'detail': dict(fact.detail)},
        events,
    )
    return False


def _continue_card_shares(state, seat, amount_each, creditors, extra, events) -> bool:
    """Pay a multi-player card in seat order, opening a debt when short (S8).

    Returns ``True`` when every share was paid and ``False`` when the window
    was reopened for the first share the cash could not cover, in which case
    the caller must not settle the step. A creditor that has left the match is
    paid through the bank, because no share may ever reach an eliminated seat:
    the money leaves the game with the recipient, the same rule ``abandon``
    applies to a single creditor.
    """
    for offset, creditor in enumerate(creditors):
        if state['players'][creditor]['eliminated']:
            # The share cannot be paid to a seat that is out, so it goes to the
            # bank. ``remaining`` keeps naming it, so the conversion belongs
            # here, where the payment is actually made.
            creditor = None
        player = state['players'][seat]
        if player['cash'] >= amount_each:
            player['cash'] -= amount_each
            if creditor is not None:
                state['players'][creditor]['cash'] += amount_each
            events.append(
                Fact(
                    name='card_paid',
                    seat=seat,
                    detail={'amount': amount_each, 'to': creditor},
                )
            )
            continue
        _open_debt(
            state,
            seat,
            amount_each,
            creditor,
            {
                'kind': 'card_shares',
                'extra': extra,
                'amount_each': amount_each,
                'remaining': list(creditors[offset + 1 :]),
            },
            {
                'name': 'card_paid',
                'seat': seat,
                'detail': {'amount': amount_each, 'to': creditor},
            },
            events,
        )
        return False
    return True


def _resume_jail_fine(state, seat, faces, events, rng) -> None:
    """Finish the third jail turn after its fine was paid (S8).

    The throw that hit the limit is the one the seat moves with, and it never
    grants an extra turn.
    """
    player = state['players'][seat]
    player['in_jail'] = False
    player['jail_turns'] = 0
    events.append(Fact(name='left_jail', seat=seat, detail={'method': 'fine'}))
    _move(state, seat, sum(faces), events)
    resolution = _resolve_landing(state, seat, faces, events, rng, extra=False)
    _finish_step(state, resolution, False, events)


def _pay_debt(state, seat, debt, events, rng) -> None:
    """Pay the open debt and resume exactly the step it interrupted (S7, S8)."""
    amount = debt['amount']
    creditor = debt['creditor']
    player = state['players'][seat]
    player['cash'] -= amount
    if creditor is not None:
        state['players'][creditor]['cash'] += amount
    state['debt'] = None
    fact = debt.get('fact')
    if fact is not None:
        events.append(
            Fact(name=fact['name'], seat=fact['seat'], detail=dict(fact['detail']))
        )
    resume = debt['resume']
    kind = resume['kind']
    if kind in ('settle_step', 'income_tax'):
        _settle_turn(state, resume['extra'], events)
    elif kind == 'jail_fine':
        _resume_jail_fine(state, seat, resume['faces'], events, rng)
    elif kind == 'card_shares':
        finished = _continue_card_shares(
            state,
            seat,
            resume['amount_each'],
            resume['remaining'],
            resume['extra'],
            events,
        )
        if finished:
            _settle_turn(state, resume['extra'], events)
    else:
        raise ValueError(f'unknown debt continuation: {kind!r}')


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
    events.append(
        Fact(name='bankrupt', seat=seat, detail={'creditor': creditor})
    )
    _eliminate(state, seat, creditor, events)
    return True


def _eliminate(state, seat: str, creditor, events=None) -> None:
    """Take ``seat`` out of the match, settling its assets (S7, S9, S11, S14).

    Every building goes back to the bank and its key leaves ``buildings``: a
    property is never transferred with buildings on it. When the creditor is a
    player it also collects the debtor's cash plus half of what the debtor had
    paid for those buildings, and then pays the 10 % interest of every
    mortgaged property it received (S9); when the creditor is the bank (taxes,
    fines and the disconnection expulsion) the buildings simply return and
    nothing is paid, and the properties are left unowned as S11 and S14 say --
    the print auctions them at once and S11 records that deviation, so what a
    bank-held space needs is no different from a space nobody ever bought.

    ``events`` is optional because the settlement is also reachable from
    :func:`abandon`; when it is a player that receives mortgaged property the
    channel is what lets the charge and a cascaded ``bankrupt`` be observed.
    """
    player = state['players'][seat]
    if player['eliminated']:
        return
    transferred = list(player['properties'])
    refund = _return_buildings(state, transferred)
    if creditor is not None:
        state['players'][creditor]['cash'] += player['cash'] + refund
    player['cash'] = 0
    mortgaged = state.setdefault('mortgaged', {})
    for index in transferred:
        if creditor is None:
            state['owners'].pop(str(index), None)
            # The bank absorbs the mortgage of a property it takes back: nobody
            # owns the space to owe it, and the next buyer starts from a clean
            # lot. The map is an invariant of ownership, never of the space.
            mortgaged.pop(str(index), None)
        else:
            state['owners'][str(index)] = creditor
            state['players'][creditor]['properties'].append(index)
    player['properties'] = []
    player['in_jail'] = False
    player['jail_turns'] = 0
    player['eliminated'] = True
    # An offer is between two live seats: a seat that leaves the match takes
    # every offer that names it, as proposer or as receiver (S7).
    _drop_offers_naming(state, seat)
    if creditor is not None:
        _charge_settlement_interest(state, creditor, transferred, events)


def _drop_offers_naming(state, seat: str) -> None:
    """Delete every live offer that names ``seat`` on either side."""
    offers = state.get('offers') or {}
    state['offers'] = {
        offer_id: offer
        for offer_id, offer in offers.items()
        if offer['proposer'] != seat and offer['receiver'] != seat
    }


def _charge_settlement_interest(state, creditor, indexes, events) -> None:
    """Charge the creditor 10 % of each mortgaged property it received (S9).

    The interest is the same ceiling of a tenth of the printed mortgage value
    that lifting a mortgage pays. A creditor that cannot pay it goes bankrupt
    to the bank, the faithful cascade of the printed rules: it cannot keep what
    it cannot sustain.
    """
    mortgaged = state.get('mortgaged') or {}
    charges = [
        (index, deeds.mortgage_lift_cost(index) - deeds.mortgage_value(index))
        for index in indexes
        if mortgaged.get(str(index))
    ]
    if not charges:
        return
    total = sum(amount for _, amount in charges)
    player = state['players'][creditor]
    if player['cash'] < total:
        _eliminate(state, creditor, None, events)
        if events is not None:
            events.append(
                Fact(name='bankrupt', seat=creditor, detail={'creditor': None})
            )
        return
    player['cash'] -= total
    if events is not None:
        for index, amount in charges:
            events.append(
                Fact(
                    name='interest_paid',
                    seat=creditor,
                    detail={
                        'space': index,
                        'amount': amount,
                        'reason': 'settlement',
                    },
                )
            )


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
    extra = state['extra_roll']
    _charge_step(
        state,
        seat,
        amount,
        None,
        Fact(
            name='tax_paid',
            seat=seat,
            detail={
                'space': board.INCOME_TAX_INDEX,
                'amount': amount,
                'option': option,
            },
        ),
        extra,
        events,
    )
    _settle_turn(state, extra, events)
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
    """Lower one development level on an offered street (S4).

    Offered in ``managing`` and in the raising-cash window, where selling is
    one of the ways to cover the debt (S7).
    """
    _require_phase(state, PHASE_MANAGING, PHASE_RAISING_CASH)
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


def _apply_mortgage(state: Mapping, seat: str, action, rng) -> Transition:
    """Mortgage an owned space, collecting its printed value from the bank (S3).

    Offered in ``managing`` and in the raising-cash window (S7).
    """
    _require_phase(state, PHASE_MANAGING, PHASE_RAISING_CASH)
    index = _read_offered_index(
        state, seat, action, _mortgageable_indexes(state, seat)
    )
    amount = deeds.mortgage_value(index)
    state = _copy(state)
    mortgaged = dict(state.get('mortgaged') or {})
    mortgaged[str(index)] = True
    state['mortgaged'] = mortgaged
    state['players'][seat]['cash'] += amount
    return Transition(
        state=state,
        facts=(
            Fact(
                name='property_mortgaged',
                seat=seat,
                detail={'space': index, 'amount': amount},
            ),
        ),
    )


def _apply_unmortgage(state: Mapping, seat: str, action, rng) -> Transition:
    """Lift a mortgage, paying the value plus interest to the bank (S4)."""
    _require_phase(state, PHASE_MANAGING)
    index = _read_offered_index(
        state, seat, action, _unmortgageable_indexes(state, seat)
    )
    mortgage = deeds.mortgage_value(index)
    amount = deeds.mortgage_lift_cost(index)
    interest = amount - mortgage
    state = _copy(state)
    state['players'][seat]['cash'] -= amount
    mortgaged = dict(state.get('mortgaged') or {})
    mortgaged.pop(str(index), None)
    state['mortgaged'] = mortgaged
    return Transition(
        state=state,
        facts=(
            Fact(
                name='property_unmortgaged',
                seat=seat,
                detail={
                    'space': index,
                    'mortgage': mortgage,
                    'interest': interest,
                    'amount': amount,
                },
            ),
            Fact(
                name='interest_paid',
                seat=seat,
                detail={
                    'space': index,
                    'amount': interest,
                    'reason': 'unmortgage',
                },
            ),
        ),
    )


def _apply_pay_debt(state: Mapping, seat: str, action, rng) -> Transition:
    """Pay the open debt and resume the interrupted step (S7, S8)."""
    _require_phase(state, PHASE_RAISING_CASH)
    debt = state.get('debt')
    if debt is None or debt.get('seat') != seat:
        raise ValueError(f'{seat!r} has no open debt')
    if state['players'][seat]['cash'] < debt['amount']:
        raise ValueError(f'{seat!r} cannot afford the debt')
    state = _copy(state)
    events = []
    _pay_debt(state, seat, state['debt'], events, rng)
    return Transition(state=state, facts=tuple(events))


def _apply_declare_bankruptcy(state: Mapping, seat: str, action, rng) -> Transition:
    """Resolve the debt by the stored creditor exactly like S11 (S7, S8)."""
    _require_phase(state, PHASE_RAISING_CASH)
    debt = state.get('debt')
    if debt is None or debt.get('seat') != seat:
        raise ValueError(f'{seat!r} has no open debt')
    creditor = debt['creditor']
    state = _copy(state)
    events = []
    state['debt'] = None
    events.append(
        Fact(name='bankrupt', seat=seat, detail={'creditor': creditor})
    )
    _eliminate(state, seat, creditor, events)
    _pass_turn(state, events)
    return Transition(state=state, facts=tuple(events))


def _apply_propose(state: Mapping, seat: str, action, rng) -> Transition:
    """Store a new offer composed by the client (S3, S4)."""
    _require_not_debtor(state, seat)
    parsed = _parse_proposal(state, seat, action.value)
    offer = {
        'id': '',
        'proposer': seat,
        'receiver': parsed['receiver'],
        'give': parsed['give'],
        'want': parsed['want'],
    }
    if not offer_is_valid(state, offer):
        raise ValueError(f'illegal offer terms: {action.value!r}')
    state = _copy(state)
    sequence = state.get('offer_seq') or 0
    offers = dict(state.get('offers') or {})
    offer['id'] = str(sequence + 1)
    offers[offer['id']] = offer
    state['offers'] = offers
    state['offer_seq'] = sequence + 1
    return Transition(
        state=state,
        facts=(
            Fact(
                name='offer_proposed',
                seat=seat,
                detail={
                    'offer': offer['id'],
                    'proposer': seat,
                    'receiver': offer['receiver'],
                    'give': offer['give'],
                    'want': offer['want'],
                },
            ),
        ),
    )


def _apply_reject(state: Mapping, seat: str, action, rng) -> Transition:
    """Delete an offer the receiver turns down (S5, S7)."""
    _require_not_debtor(state, seat)
    offer = _require_offer(state, action.value)
    if offer['receiver'] != seat:
        raise ValueError(f'{seat!r} did not receive offer {action.value!r}')
    state = _copy(state)
    offers = dict(state.get('offers') or {})
    offers.pop(offer['id'], None)
    state['offers'] = offers
    return Transition(
        state=state,
        facts=(Fact(name='offer_rejected', seat=seat, detail={'offer': offer['id']}),),
    )


def _apply_withdraw(state: Mapping, seat: str, action, rng) -> Transition:
    """Delete the proposer's own offer before it is answered (S5, S7)."""
    _require_not_debtor(state, seat)
    offer = _require_offer(state, action.value)
    if offer['proposer'] != seat:
        raise ValueError(f'{seat!r} did not make offer {action.value!r}')
    state = _copy(state)
    offers = dict(state.get('offers') or {})
    offers.pop(offer['id'], None)
    state['offers'] = offers
    return Transition(
        state=state,
        facts=(
            Fact(name='offer_withdrawn', seat=seat, detail={'offer': offer['id']}),
        ),
    )


def _apply_accept(state: Mapping, seat: str, action, rng) -> Transition:
    """Accept an offer and settle it, if S4 still holds (S5, S6)."""
    _require_not_debtor(state, seat)
    offer = _require_offer(state, action.value)
    if offer['receiver'] != seat:
        raise ValueError(f'{seat!r} did not receive offer {action.value!r}')
    if not offer_is_valid(state, offer):
        raise ValueError(f'offer {offer["id"]!r} is no longer valid')
    state = _copy(state)
    events = []
    _settle_trade(state, offer, events)
    return Transition(state=state, facts=tuple(events))


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
    ACTION_MORTGAGE: _apply_mortgage,
    ACTION_UNMORTGAGE: _apply_unmortgage,
    ACTION_PAY_DEBT: _apply_pay_debt,
    ACTION_DECLARE_BANKRUPTCY: _apply_declare_bankruptcy,
    ACTION_PROPOSE: _apply_propose,
    ACTION_ACCEPT: _apply_accept,
    ACTION_REJECT: _apply_reject,
    ACTION_WITHDRAW: _apply_withdraw,
}
