import logging
from urllib.parse import parse_qs
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from ...games.interfaces.match_abandon import abandon_seat_for_session
from ...games.interfaces.match_lookup import resolve_seat_subscription
from ...games.interfaces.match_presence import (
    publish_match_presence,
    resolve_match_presence,
)
from ..constants import LOBBY_COUNTDOWN_SECONDS, RECONNECT_GRACE_SECONDS
from ..infrastructure.connections import register_connection, unregister_connection
from ..infrastructure.events import room_event_message, room_group_name
from ..features.countdown.application.use_cases import (
    expire_lobby_countdown,
    sync_lobby_countdown,
)
from ..features.countdown.domain.rules import COUNTDOWN_EVENT
from ..features.presence.application.use_cases import (
    find_active_membership,
    mark_inactive,
    mark_online,
    mark_reconnecting,
)
from ..features.presence.infrastructure.channel_events import (
    add_to_room_group,
    publish_room_event,
    remove_from_room_group,
)
from ..features.presence.infrastructure.grace_timer import (
    GRACE_TASKS,
    cancel_grace_task,
    publish_inactive_after_grace as run_inactive_after_grace,
    schedule_grace_expiry,
)
from .composition import compose_room_dependencies

logger = logging.getLogger(__name__)

# One process-wide countdown gateway, built once at import. The in-memory timer
# registry it wraps must be shared by every socket in a room: a gateway built
# per consumer would arm a second countdown for the same room and each socket
# would leak its own timer entry. Building it here performs no database access;
# the registry itself is the module-level singleton in the timer module.
LOBBY_GATEWAY = compose_room_dependencies().countdown


def _session_id_from_scope(scope):
    try:
        query = parse_qs(scope.get('query_string', b'').decode('utf-8'))
    except UnicodeDecodeError:
        return None
    tokens = query.get('session_id', [])
    if len(tokens) != 1:
        return None
    try:
        return str(UUID(tokens[0]))
    except (AttributeError, ValueError):
        return None


@database_sync_to_async
def _active_membership(session_id):
    dependencies = compose_room_dependencies()
    return find_active_membership(dependencies.presence, session_id)


@database_sync_to_async
def _mark_online(room_id, session_id):
    dependencies = compose_room_dependencies()
    return mark_online(
        dependencies.presence,
        room_id,
        session_id,
        dependencies.vote_cancellation,
    )


@database_sync_to_async
def _mark_reconnecting(room_id, session_id):
    dependencies = compose_room_dependencies()
    return mark_reconnecting(
        dependencies.presence,
        room_id,
        session_id,
        dependencies.vote_cancellation,
    )


@database_sync_to_async
def _mark_inactive_event(room_id, session_id, disconnected_at, grace_seconds):
    dependencies = compose_room_dependencies()
    return mark_inactive(
        dependencies.presence,
        room_id,
        session_id,
        disconnected_at,
        grace_seconds,
    )


@database_sync_to_async
def _mark_inactive(room_id, session_id, disconnected_at):
    event = mark_inactive(
        compose_room_dependencies().presence,
        room_id,
        session_id,
        disconnected_at,
        RECONNECT_GRACE_SECONDS,
    )
    return event.snapshot if event is not None else None


@database_sync_to_async
def _broadcast_match_presence(room_id):
    return publish_match_presence(room_id)


@database_sync_to_async
def _resolve_room_match_presence(room_id):
    return resolve_match_presence(room_id)


@database_sync_to_async
def _abandon_expired_seat(room_id, session_id):
    return abandon_seat_for_session(room_id, session_id)


async def _publish_presence_safely(room_id):
    """Publish the room's match presence without ever raising.

    Presence is a side channel of the socket's own presence path: a transport
    failure here must never abort the presence transition that triggered it nor
    the grace timer that called it. It is logged and swallowed, exactly like
    ``RoomConsumer.sync_lobby``.
    """
    try:
        await _broadcast_match_presence(room_id)
    except Exception:
        logger.exception(
            'Unable to publish the match presence of room %s.', room_id
        )


async def _abandon_expired_seat_safely(room_id, session_id):
    """Resolve an expired seat without letting a failure kill the grace timer.

    The use case is idempotent, so a trigger with nothing to abandon is a
    harmless no-op; an unexpected failure is logged and swallowed for the same
    reason as the presence publish above.
    """
    try:
        await _abandon_expired_seat(room_id, session_id)
    except Exception:
        logger.exception(
            'Unable to abandon the expired seat of session %s in room %s.',
            session_id,
            room_id,
        )


async def _expire_presence(room_id, session_id, disconnected_at, grace_seconds):
    presence_event = await _mark_inactive_event(
        room_id, session_id, disconnected_at, grace_seconds
    )
    if presence_event is not None:
        # The participant is now inactive. Announce the new seat presence and
        # resolve the seat with the game, in that order, so the remaining
        # seats see the expulsion before the match outcome it produced (S2).
        await _publish_presence_safely(room_id)
        await _abandon_expired_seat_safely(room_id, session_id)
    return presence_event


# The match resolver runs only plain ORM queries, but it is still a database
# read, so it must be wrapped for the async consumer like the presence calls.
_resolve_seat_subscription = database_sync_to_async(resolve_seat_subscription)


async def publish_inactive_after_grace(
    room_id,
    session_id,
    disconnected_at,
    layer,
    grace_seconds=RECONNECT_GRACE_SECONDS,
):
    await run_inactive_after_grace(
        room_id,
        session_id,
        disconnected_at,
        layer,
        grace_seconds,
        _expire_presence,
    )


class RoomConsumer(AsyncJsonWebsocketConsumer):
    def reconnect_grace_seconds(self):
        return RECONNECT_GRACE_SECONDS

    def lobby_countdown_seconds(self):
        return LOBBY_COUNTDOWN_SECONDS

    async def connect(self):
        self.room_id = None
        self.session_id = _session_id_from_scope(self.scope)
        self.room_group = None
        self.match_groups = set()
        self.match_ref = None
        self.connection_registered = False

        if self.session_id is None:
            await self.close(code=4401)
            return

        membership = await _active_membership(self.session_id)
        if membership is None:
            await self.close(code=4401)
            return

        self.room_id, self.session_id = membership
        self.room_group = room_group_name(self.room_id)
        await add_to_room_group(
            self.channel_layer, self.room_group, self.channel_name
        )
        register_connection(self.room_id, self.session_id, self.channel_name)
        self.connection_registered = True
        cancel_grace_task(self.room_id, self.session_id)

        online = await _mark_online(self.room_id, self.session_id)
        if online is None:
            await self.close(code=4401)
            return
        snapshot, events = online

        await self.accept()
        await self.send_json({'type': 'room.snapshot', 'room': snapshot})
        for event in events:
            await publish_room_event(
                self.channel_layer,
                self.room_id,
                event.name,
                event.snapshot,
                vote=event.vote,
            )

        # Announce this seat's arrival before it joins its own match group, so
        # it learns the table's presence from the snapshot below and the seats
        # already in the match see it online without receiving it twice.
        await _publish_presence_safely(self.room_id)

        subscription = await _resolve_seat_subscription(
            self.room_id, self.session_id
        )
        if subscription is not None:
            await self._join_match_group(subscription)
            presence = await _resolve_room_match_presence(self.room_id)
            await self.send_json(
                self._match_snapshot_message(subscription, presence)
            )

        # A socket arriving while a countdown is already armed learns the
        # remaining seconds from the shared timer; otherwise the arriving
        # socket reconciles the lobby, so an already fully ready room arms its
        # countdown on the first socket that reaches it.
        armed = LOBBY_GATEWAY.current_countdown(self.room_id)
        if armed is not None:
            await self.send_json(
                {
                    'type': COUNTDOWN_EVENT,
                    'room': snapshot,
                    'countdown': armed.payload(),
                }
            )
            return
        await self.sync_lobby(self.room_id, snapshot)

    async def sync_lobby(self, room_id, snapshot):
        """Reconcile the room's lobby countdown against ``snapshot``.

        The expire callback closes over the module-level gateway and the plain
        integer room id only, never ``self``: an armed countdown must not keep
        a disconnected consumer alive through its own timer.
        """
        gateway = LOBBY_GATEWAY

        async def on_expire():
            await expire_lobby_countdown(gateway, room_id)

        try:
            await sync_lobby_countdown(
                gateway,
                room_id,
                snapshot,
                seconds=self.lobby_countdown_seconds(),
                on_expire=on_expire,
            )
        except Exception:
            logger.exception(
                'Unable to sync the lobby countdown for room %s.', room_id
            )

    async def _join_match_group(self, subscription):
        """Join the single match group this socket is entitled to, once.

        A socket joins exactly one match group: its own seat group when it
        occupies a seat, or the public group when it is a spectator. Joining
        both would deliver one event twice, and the public view that arrives
        last would hide the seat's own pending pick. Connect-time resolution
        and ``match_started`` can both ask for the same group, so it is never
        joined twice: Channels would add the channel again and every event
        would reach the socket twice.

        The single subscription is per match, not just per group. A room that
        finishes one match and starts another is the ordinary path, so a
        socket that kept the finished match's group while joining the new
        match's would hold two match groups at once even though each group is
        joined only once. When the incoming subscription belongs to a
        different match than the one already held, the groups held for the
        previous match are left before the new one is joined, so a socket
        holds exactly one match group at any moment, whatever sequence of
        matches its room goes through.
        """
        if subscription.group in self.match_groups:
            return
        if (
            self.match_ref is not None
            and subscription.match_ref != self.match_ref
        ):
            for previous in self.match_groups:
                await self.channel_layer.group_discard(
                    previous, self.channel_name
                )
            self.match_groups.clear()
        await self.channel_layer.group_add(subscription.group, self.channel_name)
        self.match_groups.add(subscription.group)
        self.match_ref = subscription.match_ref

    @staticmethod
    def _match_snapshot_message(subscription, presence):
        """Build the opening snapshot, carrying the resolved seat presence.

        ``presence`` is resolved by the caller because the snapshot is a pure
        formatter: the seat presence belongs to the match, not to the socket's
        own seat, so it is the same list for every socket of the match (S6).
        """
        return {
            'type': 'match.snapshot',
            'match_ref': subscription.match_ref,
            'seat_index': subscription.seat_index,
            'view': subscription.view,
            'seats': presence.payload() if presence is not None else [],
        }

    async def match_started(self, event):
        """Subscribe on match start and send the seat its opening snapshot.

        The projector drives this through the room group with the match ref,
        so a socket already in the room learns a match exists and joins the one
        match group it is entitled to. The seat is resolved from the socket's
        own session, so a socket only ever learns the seat it occupies and a
        seatless participant subscribes as a spectator of the public group.
        """
        subscription = await _resolve_seat_subscription(
            self.room_id, self.session_id, event['match_ref']
        )
        if subscription is None:
            return
        await self._join_match_group(subscription)
        presence = await _resolve_room_match_presence(self.room_id)
        await self.send_json(
            self._match_snapshot_message(subscription, presence)
        )

    async def game_presence(self, event):
        """Forward the match's seat presence to this socket (S1, S6).

        The frame is already state-free and public: it carries only indexes and
        presence values, never a play, so a seat and a spectator receive the
        same thing and no seat's view can leak through this path.
        """
        await self.send_json(
            {
                'type': 'match.presence',
                'match_ref': event['match_ref'],
                'seats': event['seats'],
            }
        )

    async def game_event(self, event):
        """Forward a match event to this socket's single subscription.

        A socket is only ever a member of exactly one match group: its own
        seat group when seated, or the public group when a spectator. Those
        are exactly the groups the projector fans a seat's own view and the
        state-free public view to. This handler therefore cannot be handed
        another seat's view, and it must never resolve or forward a view for
        any other seat. It forwards only the fields the client needs and drops
        the projector's ``room_id`` and ``facts``.
        """
        await self.send_json(
            {
                'type': 'match.event',
                'event': event['event'],
                'match_ref': event['match_ref'],
                'version': event['version'],
                'view': event['view'],
            }
        )

    async def room_event(self, event):
        client_event = {'type': event['event'], 'room': event['room']}
        if 'vote' in event:
            client_event['vote'] = event['vote']
        if 'countdown' in event:
            client_event['countdown'] = event['countdown']
        if event.get('departed_session_id') == self.session_id:
            cancel_grace_task(self.room_id, self.session_id)
            await self.send_json(client_event)
            await self.close(code=4001)
            return
        await self.send_json(client_event)
        # The leaving socket returned above, so only the sockets that stay
        # reconcile the lobby after this event.
        await self.sync_lobby(self.room_id, event['room'])

    async def disconnect(self, close_code):
        if self.room_group is not None:
            await remove_from_room_group(
                self.channel_layer, self.room_group, self.channel_name
            )
        for group in self.match_groups:
            await self.channel_layer.group_discard(group, self.channel_name)

        if not self.connection_registered:
            return
        self.connection_registered = False
        if not unregister_connection(self.room_id, self.session_id, self.channel_name):
            return

        reconnecting = await _mark_reconnecting(self.room_id, self.session_id)
        if reconnecting is None:
            return
        snapshot, disconnected_at, events = reconnecting
        for event in events:
            await publish_room_event(
                self.channel_layer,
                self.room_id,
                event.name,
                event.snapshot,
                vote=event.vote,
            )

        # The seat is reconnecting now: the remaining seats must learn it in
        # the match's own messages, not only in the room's presence.
        await _publish_presence_safely(self.room_id)

        schedule_grace_expiry(
            self.room_id,
            self.session_id,
            disconnected_at,
            self.channel_layer,
            self.reconnect_grace_seconds(),
            _expire_presence,
        )
