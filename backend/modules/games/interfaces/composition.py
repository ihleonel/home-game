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

``reaping`` is reused from the rooms composition root for the same reason: the
match-start path must remove a ghost-ready membership before it resolves the
seats, and it must do so with the one grace window the rooms module owns.
"""

from dataclasses import dataclass

from ...rooms.features.presence.infrastructure.django_gateway import (
    DjangoPresenceGateway,
)
from ...rooms.features.readiness.application.use_cases import reset_readiness
from ...rooms.features.readiness.infrastructure.django_gateway import (
    DjangoReadinessGateway,
)
from ...rooms.features.reaping.application.service import ReapingService
from ...rooms.interfaces.composition import compose_room_dependencies
from ..composition import GAME_REGISTRY
from ..registry import GameRegistry
from ..runtime.infrastructure.channel_projector import ChannelMatchProjector
from ..runtime.infrastructure.django_store import DjangoMatchStore


class DjangoMatchLifecycle:
    """``MatchLifecycle`` adapter over the rooms readiness slice.

    Finishing a match has a room-level consequence in this product, so the
    runtime reaches it through the port instead of importing ``rooms``; this
    adapter is where that consequence is actually applied.
    """

    def __init__(self, readiness=None):
        self._readiness = (
            readiness if readiness is not None else DjangoReadinessGateway()
        )

    def on_match_finished(self, *, match_ref, room_id):
        reset_readiness(self._readiness, room_id)


@dataclass(frozen=True)
class MatchDependencies:
    """The runtime adapters and the room resolver the API composes once."""

    store: DjangoMatchStore
    projector: ChannelMatchProjector
    registry: GameRegistry
    presence: DjangoPresenceGateway
    lifecycle: DjangoMatchLifecycle
    reaping: ReapingService


def compose_match_dependencies():
    """Build the production dependencies of the match API."""
    return MatchDependencies(
        store=DjangoMatchStore(),
        projector=ChannelMatchProjector(),
        registry=GAME_REGISTRY,
        presence=DjangoPresenceGateway(),
        lifecycle=DjangoMatchLifecycle(),
        # Reuse the rooms composition root instead of re-binding the grace
        # constant here: the reaping service must resolve the window once.
        reaping=compose_room_dependencies().reaping,
    )
