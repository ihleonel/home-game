"""Pure rules for ``duelo``, a rock-paper-scissors match, best of three.

The rules are plain data transforms: they never mutate their inputs and never
import Django, DRF, or Channels. The mutable match state lives in the caller
and is threaded through as an opaque mapping.
"""

from typing import Iterable, Mapping

from ..contracts import Outcome

CHOICES = ('rock', 'paper', 'scissors')
BEATS = {'rock': 'scissors', 'scissors': 'paper', 'paper': 'rock'}
WINS_NEEDED = 2


def initial_state(seat_ids: Iterable[str]) -> dict:
    """Open a match with one empty round for the given seat ids."""
    seat_ids = tuple(seat_ids)
    return {
        'round': 1,
        'scores': {seat_id: 0 for seat_id in seat_ids},
        'picks': {seat_id: None for seat_id in seat_ids},
        'reveal': None,
        'winner': None,
        'history': (),
    }


def resolve(first_pick: str, second_pick: str) -> str | None:
    """Resolve a duel, returning ``'first'``, ``'second'`` or ``None`` on a draw.

    Raises ``ValueError`` if either pick is not a legal choice, so an illegal
    value can never fall through to a phantom ``'second'`` win or leak a
    ``KeyError`` from the lookup table.
    """
    if first_pick not in CHOICES or second_pick not in CHOICES:
        raise ValueError(f'illegal pick value: {first_pick!r}, {second_pick!r}')
    if first_pick == second_pick:
        return None
    if BEATS[first_pick] == second_pick:
        return 'first'
    return 'second'


def apply_pick(state: Mapping, seat: str, value: str) -> dict:
    """Return a new state with ``seat``'s pick recorded and its round advanced.

    The input state is never mutated. While the other pick is still missing the
    new state only records this pick. Once both picks are present the round is
    resolved: ``reveal`` and ``history`` are updated and the winner's score is
    incremented. A score reaching ``WINS_NEEDED`` sets ``winner`` and freezes
    the match; otherwise the round number advances and both picks reset.

    Raises ``ValueError`` if the match is already finished. A finished match
    keeps both picks recorded, so resolving it again would silently score the
    winner a second time, duplicate ``history`` and rewrite ``reveal``. This is
    a programming-error trap and is reported loudly rather than swallowed.

    Raises ``ValueError`` if ``seat`` is not one of the match's seats, before
    any new state is built. Accepting an unknown seat would append a third key
    to ``picks`` while ``scores`` still held the real seats, a silent
    corruption that only surfaced later as an unpacking error once both real
    seats had picked.

    Raises ``ValueError`` if ``seat`` already holds a non-``None`` pick. The
    definition's ``legal_actions`` returns ``()`` for a seat that has already
    picked, so accepting that same call here would contradict the declared
    rules and let a seat silently overwrite a commitment that was already
    recorded and broadcast. Guarding this keeps ``apply_pick`` and
    ``legal_actions`` self-consistent whenever accepting the pick would change
    the result.

    Raises ``ValueError`` if ``value`` is not a legal choice, before any state
    is built, so an illegal pick can never reach ``resolve``.

    The ``action`` name is deliberately not validated. The name does not
    influence the outcome: the value alone governs the round resolution, and
    the illegal-value guard already protects the result, so a non-``pick`` name
    cannot change the outcome.
    """
    if state['winner'] is not None:
        raise ValueError('cannot apply a pick to a finished match')

    if seat not in state['picks']:
        raise ValueError(f'unknown seat: {seat!r}')

    if state['picks'][seat] is not None:
        raise ValueError(f'seat has already picked: {seat!r}')

    if value not in CHOICES:
        raise ValueError(f'illegal pick value: {value!r}')

    picks = {**state['picks'], seat: value}

    if any(pick is None for pick in picks.values()):
        return {**state, 'picks': picks}

    first, second = tuple(picks)
    result = resolve(picks[first], picks[second])
    reveal = {
        'round': state['round'],
        'picks': dict(picks),
        'winner': None if result is None else (first if result == 'first' else second),
    }

    scores = dict(state['scores'])
    round_winner = reveal['winner']
    if round_winner is not None:
        scores[round_winner] += 1

    new_state = {
        **state,
        'picks': picks,
        'scores': scores,
        'reveal': reveal,
        'history': (*state['history'], reveal),
    }

    if round_winner is not None and scores[round_winner] >= WINS_NEEDED:
        return {**new_state, 'winner': round_winner}

    return {
        **new_state,
        'round': state['round'] + 1,
        'picks': {seat_id: None for seat_id in picks},
    }


def winner(state: Mapping) -> str | None:
    """Return the seat that has won the match, or ``None``."""
    return state['winner']


def is_finished(state: Mapping) -> bool:
    """Return whether the match already has a winner."""
    return state['winner'] is not None


def outcome(state: Mapping) -> Outcome | None:
    """Return the final outcome once the match is finished, else ``None``."""
    if state['winner'] is None:
        return None
    return Outcome(winner_seat=state['winner'], reason='best_of_three')
