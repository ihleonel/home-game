"""Interface-layer projection of a match's public seat identity (S1).

The match screen must name each seat with its player's visible name and marker,
never with a client-invented seat number. That identity is owned by the
backend: this resolver reads the persisted ``MatchSeat`` rows and the
``Participant`` behind each one and returns one public entry per seat, in
``index`` order.

The marker label is resolved centrally from the game's own ``seat_options``
catalog through the shared ``GAME_REGISTRY`` rather than stored on the seat, so
a catalog relabel is reflected without a data migration. When the marker id is
not part of that catalog -- or the game is not registered at all -- the raw
marker id is exposed as the last resort, so an entry never loses its marker.

The list is public: it carries only the seat's identity and no pick, no
pending choice and no other hidden value. It is therefore identical for the
seated participant and for a spectator, and it is a sibling of the presence
payload rather than an extension of it.
"""

from ..composition import GAME_REGISTRY
from ..models import MatchSeat


def resolve_match_roster(match):
    """Return the public identity of every seat of ``match``, by ``index``.

    Each entry is a dict with exactly ``seat_id``, ``index``, ``display_name``,
    ``game_marker`` and ``game_marker_label``. The name and marker come from the
    seated participant; the label comes from the game's catalog when the marker
    belongs to it, and falls back to the raw marker id otherwise.
    """
    definition = GAME_REGISTRY.get(match.game_id)
    labels = _seat_option_labels(definition)
    seats = (
        MatchSeat.objects.filter(match=match)
        .select_related('participant')
        .order_by('index')
    )
    return tuple(
        {
            'seat_id': seat.seat_id,
            'index': seat.index,
            'display_name': seat.participant.display_name,
            'game_marker': seat.participant.game_marker,
            'game_marker_label': labels.get(
                seat.participant.game_marker, seat.participant.game_marker
            ),
        }
        for seat in seats
    )


def _seat_option_labels(definition):
    """Return the ``id -> label`` catalog of a game definition, or ``{}``.

    An unregistered game has no catalog, so every marker falls back to its own
    id rather than raising.
    """
    if definition is None:
        return {}
    return {option.id: option.label for option in definition.seat_options}
