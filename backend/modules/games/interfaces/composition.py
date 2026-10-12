"""Production composition root for the match runtime (FRG-06).

This is the **only** place the production runtime adapters are wired: the
Django-backed store and the Channels-backed projector are built here and
handed, together with the games registry, to the ``start_match`` and
``submit_action`` use cases. The interface layer never constructs its own
store, projector or registry, so swapping a production adapter is a change to
this module and nowhere else.

``presence`` is the existing rooms machinery reused to resolve a session to its
active room: the games API asks the rooms module for the room instead of
running a second session-to-room query.
"""

from dataclasses import dataclass

from ...rooms.features.presence.infrastructure.django_gateway import (
    DjangoPresenceGateway,
)
from ..composition import GAME_REGISTRY
from ..registry import GameRegistry
from ..runtime.infrastructure.channel_projector import ChannelMatchProjector
from ..runtime.infrastructure.django_store import DjangoMatchStore


@dataclass(frozen=True)
class MatchDependencies:
    """The runtime adapters and the room resolver the API composes once."""

    store: DjangoMatchStore
    projector: ChannelMatchProjector
    registry: GameRegistry
    presence: DjangoPresenceGateway


def compose_match_dependencies():
    """Build the production dependencies of the match API."""
    return MatchDependencies(
        store=DjangoMatchStore(),
        projector=ChannelMatchProjector(),
        registry=GAME_REGISTRY,
        presence=DjangoPresenceGateway(),
    )
