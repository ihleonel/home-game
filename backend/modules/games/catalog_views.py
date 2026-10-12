"""Read-only catalog endpoint for the games app (FRG-07).

Catalog data is game metadata, so it is owned by ``games`` and derived from the
production ``GAME_REGISTRY`` instead of a room-local static list. The DTO shape
(``{'id', 'label', 'description', 'markers': ({'id', 'label'}, ...)}``) is
produced by ``GameRegistry.list_games`` and must not drift, because the
frontend consumes it unchanged.

This lives outside ``views.py`` to keep that module focused on the match
runtime transport adapters; the catalog is a separate, stateless read.
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from .composition import GAME_REGISTRY


@api_view(['GET'])
def game_catalog(request):
    """Return every registered game as the frontend catalog DTO."""
    return Response(list(GAME_REGISTRY.list_games()))
