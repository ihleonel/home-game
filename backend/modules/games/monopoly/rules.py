"""Pure rules for ``monopoly``, the classic property trading game (S5-S12).

Plain data transforms: the rules never mutate their inputs and never import
Django, DRF or Channels. The mutable match state lives in the caller and is
threaded through as an opaque mapping, exactly like ``ta_te_ti``.

The increment these rules implement is the playable core: dice, movement, GO,
purchases, rents, taxes, jail, bankruptcy, elimination and the end of the
match. Chance and Community Chest decks, house and hotel building, mortgages,
auctions and trading are later increments and are deliberately absent (S16):
landing on a card space is a stop without a consequence, `managing` offers only
`end_turn`, and an unaffordable debt goes straight to bankruptcy because the
raise-cash route does not exist yet.

The edition is the classic 1999-2007 rulebook (S2): $1.500 to start, Income Tax
at $200 or 10 % of total worth, Luxury Tax at $75.
"""

import copy
from typing import Mapping, Sequence

from ..contracts import Action, ActionSpec, Fact, Outcome, Transition
from . import board, deeds

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

# The three phases the state persists (S6). Resolving a space happens inside
# the same transition as the roll, so it is not a phase of its own.
PHASE_AWAITING_ROLL = 'awaiting_roll'
PHASE_AWAITING_DECISION = 'awaiting_decision'
PHASE_MANAGING = 'managing'

ACTION_ROLL = 'roll'
ACTION_PAY_JAIL_FINE = 'pay_jail_fine'
ACTION_BUY = 'buy'
ACTION_DECLINE = 'decline'
ACTION_PAY_INCOME_TAX_FIXED = 'pay_income_tax_fixed'
ACTION_PAY_INCOME_TAX_PERCENT = 'pay_income_tax_percent'
ACTION_END_TURN = 'end_turn'

# Spaces that stop the token without asking anything. Chance and Community
# Chest are here because the decks arrive in a later increment (S16).
_SILENT_KINDS = frozenset(
    (
        board.SpaceKind.GO,
        board.SpaceKind.JAIL,
        board.SpaceKind.FREE_PARKING,
        board.SpaceKind.CHANCE,
        board.SpaceKind.COMMUNITY_CHEST,
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


def initial_state(seat_ids: Sequence[str], first_seat: str) -> dict:
    """Open a match with every player at GO, solvent and holding $1.500.

    ``first_seat`` is supplied by the caller (the definition draws it from a
    ``RandomSource``); the rules never choose an opening seat themselves.
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
        'bank': {'houses': STARTING_HOUSES, 'hotels': STARTING_HOTELS},
        'phase': PHASE_AWAITING_ROLL,
        'turn': first_seat,
        'last_roll': None,
        'pending': None,
        'doubles_count': 0,
        'extra_roll': False,
        'ended_by_abandon': False,
        'abandoned_seat': None,
    }


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


def total_worth(state: Mapping, seat: str) -> int:
    """Return cash plus the printed prices of the seat's properties.

    Buildings cost price joins this in the building increment, and the mortgage
    state of a property deliberately does not change its printed price (S10).
    """
    player = state['players'][seat]
    return player['cash'] + sum(
        deeds.purchase_price(index) for index in player['properties']
    )


def legal_actions(state: Mapping, seat: str) -> tuple[ActionSpec, ...]:
    """Return the actions ``seat`` may take right now, and nothing else."""
    if is_finished(state) or seat not in state['players']:
        return ()
    if state['turn'] != seat:
        return ()
    player = state['players'][seat]
    if player['eliminated']:
        return ()

    phase = state['phase']
    if phase == PHASE_AWAITING_ROLL:
        specs = [ActionSpec(name=ACTION_ROLL, prompt='Tirá los dados.')]
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
        return (ActionSpec(name=ACTION_END_TURN, prompt='Terminá tu turno.'),)

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
    if state['turn'] != seat:
        raise ValueError(f'not {seat!r} turn')
    handler = _HANDLERS.get(action.name)
    if handler is None:
        raise ValueError(f'unknown action: {action.name!r}')
    return _with_finish_fact(handler(state, seat, rng))


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
        state['phase'] = PHASE_AWAITING_ROLL
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


def _apply_roll(state: Mapping, seat: str, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_ROLL)
    if rng is None:
        raise ValueError('rolling requires a RandomSource')
    state = _copy(state)
    events = []
    faces = [rng.roll(DICE_SIDES) for _ in range(DICE_COUNT)]
    total = sum(faces)
    doubles = faces[0] == faces[1]
    state['last_roll'] = list(faces)
    events.append(
        Fact(
            name='roll_recorded',
            seat=seat,
            detail={'dice': list(faces), 'doubles': doubles},
        )
    )

    if state['players'][seat]['in_jail']:
        return _resolve_jail_roll(state, seat, faces, total, doubles, events)

    if doubles:
        state['doubles_count'] += 1
        if state['doubles_count'] >= DOUBLES_TO_JAIL:
            # The third double goes straight to jail instead of moving.
            _send_to_jail(state, seat, 'three_doubles', events)
            _pass_turn(state, events)
            return Transition(state=state, facts=tuple(events))

    _move(state, seat, total, events)
    resolution = _resolve_landing(state, seat, faces, events)
    return _finish_step(state, resolution, doubles, events)


def _resolve_jail_roll(state, seat, faces, total, doubles, events) -> Transition:
    """Resolve a roll made from jail (S7)."""
    player = state['players'][seat]
    if doubles:
        player['in_jail'] = False
        player['jail_turns'] = 0
        events.append(Fact(name='left_jail', seat=seat, detail={'method': 'doubles'}))
        _move(state, seat, total, events)
        resolution = _resolve_landing(state, seat, faces, events)
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
    resolution = _resolve_landing(state, seat, faces, events)
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


def _resolve_landing(state, seat: str, faces, events):
    """Resolve the space the seat stopped on.

    Returns ``'decision'`` when the space opened a pending decision, ``'jail'``
    when the seat was sent to jail (which ends the turn in the act) and ``None``
    when the turn can simply continue.
    """
    index = state['players'][seat]['position']
    space = board.space_at(index)
    kind = space.kind

    if kind in _SILENT_KINDS:
        return None

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
        state['phase'] = PHASE_AWAITING_DECISION
        state['pending'] = {'kind': 'purchase', 'space': index}
        events.append(
            Fact(name='purchase_offered', seat=seat, detail={'space': index})
        )
        return 'decision'

    if owner == seat:
        return None

    amount = _rent(state, space, owner, faces)
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


def _rent(state, space, owner: str, faces) -> int:
    """Return what ``owner`` charges a token stopping on ``space`` (S9)."""
    if space.kind is board.SpaceKind.STREET:
        deed = deeds.deed_for(space.index)
        if _owns_group(state, owner, space.group):
            return deed.set_rent
        return deed.base_rent
    if space.kind is board.SpaceKind.RAILROAD:
        owned = sum(
            1 for index in board.RAILROAD_INDEXES
            if state['owners'].get(str(index)) == owner
        )
        return deeds.RAILROAD_RENTS[owned - 1]
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
    """Take ``seat`` out of the match, settling its assets."""
    player = state['players'][seat]
    if player['eliminated']:
        return
    if creditor is not None:
        state['players'][creditor]['cash'] += player['cash']
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


def _apply_pay_jail_fine(state: Mapping, seat: str, rng) -> Transition:
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


def _apply_buy(state: Mapping, seat: str, rng) -> Transition:
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


def _apply_decline(state: Mapping, seat: str, rng) -> Transition:
    _require_phase(state, PHASE_AWAITING_DECISION)
    index = _require_pending(state, 'purchase')['space']
    state = _copy(state)
    events = [
        Fact(name='purchase_declined', seat=seat, detail={'space': index})
    ]
    _settle_turn(state, state['extra_roll'], events)
    return Transition(state=state, facts=tuple(events))


def _apply_income_tax_fixed(state: Mapping, seat: str, rng) -> Transition:
    return _pay_income_tax(state, seat, 'fixed', INCOME_TAX_FIXED)


def _apply_income_tax_percent(state: Mapping, seat: str, rng) -> Transition:
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


def _apply_end_turn(state: Mapping, seat: str, rng) -> Transition:
    _require_phase(state, PHASE_MANAGING)
    state = _copy(state)
    events = []
    _pass_turn(state, events)
    return Transition(state=state, facts=tuple(events))


_HANDLERS = {
    ACTION_ROLL: _apply_roll,
    ACTION_PAY_JAIL_FINE: _apply_pay_jail_fine,
    ACTION_BUY: _apply_buy,
    ACTION_DECLINE: _apply_decline,
    ACTION_PAY_INCOME_TAX_FIXED: _apply_income_tax_fixed,
    ACTION_PAY_INCOME_TAX_PERCENT: _apply_income_tax_percent,
    ACTION_END_TURN: _apply_end_turn,
}
