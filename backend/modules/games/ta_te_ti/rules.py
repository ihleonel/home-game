"""Pure rules for ``ta_te_ti``, a tic-tac-toe match for exactly two seats.

The rules are plain data transforms: they never mutate their inputs and never
import Django, DRF, or Channels. The mutable match state lives in the caller
and is threaded through as an opaque mapping.

The board is a flat list of nine cells (``0..8``, row by row), each holding a
``seat_id`` or ``None``. Symbols are derived from the seat's index order --
``X`` for the first seat, ``O`` for the second -- so the cosmetic room marker
never changes the board. The seat on turn is stored in ``turn`` and is ``None``
once the match is finished.
"""

from typing import Iterable, Mapping, Sequence

from ..contracts import Outcome

BOARD_SIZE = 9
SYMBOLS = ('X', 'O')

# The eight standard lines: three rows, three columns, two diagonals. The
# table is the single source of what "three in a row" means.
LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


def initial_state(seat_ids: Iterable[str], first_seat: str) -> dict:
    """Open a match on an empty board with ``first_seat`` on turn.

    ``first_seat`` is supplied by the caller (the definition draws it from a
    ``RandomSource``); the rules never choose an opening seat themselves.
    Raises ``ValueError`` if the seat count is not exactly two or if
    ``first_seat`` is not one of them, so an invalid opening can never reach
    the board.
    """
    seat_ids = tuple(seat_ids)
    if len(seat_ids) != 2:
        raise ValueError(f'ta-te-ti needs exactly two seats, got {len(seat_ids)}')
    if first_seat not in seat_ids:
        raise ValueError(f'unknown seat: {first_seat!r}')
    return {
        'board': [None] * BOARD_SIZE,
        'seats': seat_ids,
        'turn': first_seat,
        'winner': None,
        'winner_line': None,
        'finished': False,
        'ended_by_abandon': False,
        'abandoned_seat': None,
    }


def symbols(state: Mapping) -> dict:
    """Return the ``seat_id -> 'X' | 'O'`` map, keyed by seat index order."""
    return {
        seat: SYMBOLS[index]
        for index, seat in enumerate(state['seats'])
        if index < len(SYMBOLS)
    }


def other_seat(state: Mapping, seat: str) -> str:
    """Return the only seat that is not ``seat``.

    Raises ``ValueError`` if ``seat`` is not one of the match's seats, before
    any caller can build a state around the unknown value.
    """
    if seat not in state['seats']:
        raise ValueError(f'unknown seat: {seat!r}')
    return next(other for other in state['seats'] if other != seat)


def winning_line(board: Sequence, seat: str) -> tuple[int, int, int] | None:
    """Return the line ``seat`` has completed, or ``None``."""
    for line in LINES:
        if all(board[cell] == seat for cell in line):
            return line
    return None


def _parse_cell(value) -> int:
    """Return the cell index for a pick value, or raise ``ValueError``.

    The wire value is the string form of the index (the runtime checks it
    against the ``legal_actions`` options before calling here); a non-numeric,
    negative or out-of-range value is still rejected loudly so it can never
    silently index the board from the end.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'illegal cell value: {value!r}')
    try:
        cell = int(value)
    except ValueError:
        raise ValueError(f'illegal cell value: {value!r}') from None
    if not 0 <= cell < BOARD_SIZE:
        raise ValueError(f'illegal cell value: {value!r}')
    return cell


def apply_pick(state: Mapping, seat: str, value) -> dict:
    """Return a new state with ``seat``'s pick placed on the board.

    The input state is never mutated. The pick marks its cell with the seat id
    and either moves the turn to the other seat, or -- when it completes one
    of the eight lines -- freezes the match with ``winner`` and
    ``winner_line``. A pick that fills the last free cell without a line
    freezes the match as a draw (``finished`` true, ``winner`` ``None``).

    Raises ``ValueError`` if the match is already finished (a resolved match
    is frozen and re-applying would rewrite an outcome already recorded and
    broadcast), if ``seat`` is not a seat of the match, if it is not the
    seat on turn (``legal_actions`` returns ``()`` for that same call), or if
    the value is not a free cell. Every one of these is a programming-error
    trap reported loudly rather than swallowed.
    """
    if state['finished']:
        raise ValueError('cannot pick in a finished match')

    if seat not in state['seats']:
        raise ValueError(f'unknown seat: {seat!r}')

    if state['turn'] != seat:
        raise ValueError(f'seat is not on turn: {seat!r}')

    cell = _parse_cell(value)
    board = list(state['board'])
    if board[cell] is not None:
        raise ValueError(f'cell already taken: {value!r}')
    board[cell] = seat

    line = winning_line(board, seat)
    if line is not None:
        return {
            **state,
            'board': board,
            'turn': None,
            'winner': seat,
            'winner_line': line,
            'finished': True,
        }

    if all(cell_value is not None for cell_value in board):
        return {**state, 'board': board, 'turn': None, 'finished': True}

    return {**state, 'board': board, 'turn': other_seat(state, seat)}


def abandon(state: Mapping, seat: str) -> dict:
    """Return a new state resolving ``seat``'s expulsion for the other seat.

    The input state is never mutated. ``ta_te_ti`` has exactly two seats, so
    the seat that stays wins outright: the new state records ``seat`` in
    ``abandoned_seat``, names the other seat as ``winner`` and freezes the
    match, and :func:`outcome` reports the abandonment reason.

    Raises ``ValueError`` if the match is already finished (resolving an
    abandonment on top of it would silently re-point ``winner``) or if ``seat``
    is not one of the match's seats (there is no opponent to promote).
    """
    if state['finished']:
        raise ValueError('cannot abandon a finished match')

    remaining = other_seat(state, seat)
    return {
        **state,
        'winner': remaining,
        'winner_line': None,
        'finished': True,
        'ended_by_abandon': True,
        'abandoned_seat': seat,
        'turn': None,
    }


def is_finished(state: Mapping) -> bool:
    """Return whether the match is over, including a draw."""
    return state['finished']


def outcome(state: Mapping) -> Outcome | None:
    """Return the final outcome once the match is finished, else ``None``.

    A finished match reports ``three_in_a_row`` when a seat completed a line,
    ``win_by_abandon`` when it was resolved by an expulsion, and ``draw`` when
    the board filled without a line. The reason is read off the persisted
    state alone, so a client can tell the three endings apart.
    """
    if not state['finished']:
        return None
    if state['ended_by_abandon']:
        return Outcome(winner_seat=state['winner'], reason='win_by_abandon')
    if state['winner'] is not None:
        return Outcome(winner_seat=state['winner'], reason='three_in_a_row')
    return Outcome(winner_seat=None, reason='draw')
