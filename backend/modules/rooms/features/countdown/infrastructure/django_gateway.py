"""Production adapter for the lobby countdown ports.

The Django/Channels side of the slice: resolves game limits from the registry,
prepares a lobby under one transaction, opens the match through the shared
interface sequence, and publishes room events. The timer stays an injected
in-memory collaborator.
"""

from channels.db import database_sync_to_async
from django.db import transaction

from .....games.composition import GAME_REGISTRY
from .....games.interfaces.match_start import (
    MatchAlreadyInProgress,
    open_match_for_room,
)
from .....games.models import Match
from ....infrastructure.events import broadcast_room_event
from ....infrastructure.snapshots import room_snapshot
from ....models import Room
from ..application.ports import LobbyLimits, LobbyState
from ..domain.rules import lobby_is_ready
from .timer import LOBBY_TIMER


class DjangoLobbyCountdownGateway:
    def __init__(self, reaping, timer=LOBBY_TIMER):
        self._reaping = reaping
        self._timer = timer

    def game_limits(self, game_id):
        definition = GAME_REGISTRY.get(game_id)
        if definition is None:
            return None
        return LobbyLimits(
            min_seats=definition.min_seats, max_seats=definition.max_seats
        )

    def current_countdown(self, room_id):
        return self._timer.current(room_id)

    def arm_countdown(self, room_id, seconds, on_expire):
        return self._timer.arm(room_id, seconds, on_expire)

    def cancel_countdown(self, room_id):
        return self._timer.cancel(room_id)

    async def prepare_lobby(self, room_id):
        return await database_sync_to_async(self._prepare_lobby)(room_id)

    def _prepare_lobby(self, room_id):
        with transaction.atomic():
            self._reaping.reap(room_id=room_id)
            room = Room.objects.filter(pk=room_id).first()
            if room is None:
                return None
            has_match = Match.objects.filter(
                room_id=room_id, status=Match.Status.IN_PROGRESS
            ).exists()
            snapshot = room_snapshot(room)
        limits = self.game_limits(snapshot.get('game_id'))
        seatable = (
            not has_match
            and limits is not None
            and lobby_is_ready(snapshot, limits.min_seats, limits.max_seats)
        )
        return LobbyState(snapshot=snapshot, seatable=seatable)

    async def start_match(self, room_id):
        await database_sync_to_async(self._start_match)(room_id)

    def _start_match(self, room_id):
        room = Room.objects.filter(pk=room_id).first()
        if room is None:
            return
        # Import the games composition root lazily: it imports
        # ``modules.rooms.interfaces.composition``, which imports this module,
        # so a module-level import would close an import cycle.
        from .....games.interfaces.composition import compose_match_dependencies

        dependencies = compose_match_dependencies()
        try:
            open_match_for_room(
                room=room,
                reaping=dependencies.reaping,
                store=dependencies.store,
                registry=dependencies.registry,
                projector=dependencies.projector,
                rng=dependencies.rng,
            )
        except MatchAlreadyInProgress:
            # A concurrent starter won the race and already opened the match.
            return

    async def broadcast(self, room_id, event_name, snapshot, countdown):
        await database_sync_to_async(broadcast_room_event)(
            room_id, event_name, snapshot, countdown=countdown
        )
