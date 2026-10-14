"""Shared view projection helper for the runtime use cases.

This lives outside ``application/__init__.py`` so the package holds only its
docstring and no logic; the use cases import it explicitly.
"""

from typing import Mapping

from ...contracts import GameDefinition
from .ports import MatchRecord


def seat_views(definition: GameDefinition, record: MatchRecord) -> Mapping:
    """Return every seat's view plus the public (``None``) view."""
    views = {
        seat.seat_id: definition.view(record.state, seat.seat_id)
        for seat in record.seats
    }
    views[None] = definition.view(record.state, None)
    return views
