import json

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from config.asgi import application
from modules.games.interfaces.match_lookup import GAME_REGISTRY
from modules.games.models import Match
from modules.games.runtime.application.start_match import start_match
from modules.games.runtime.application.submit_action import submit_action
from modules.games.runtime.infrastructure.channel_projector import (
    ChannelMatchProjector,
    match_seat_group_name,
)
from modules.games.runtime.infrastructure.django_store import DjangoMatchStore
from modules.rooms.constants import RECONNECT_GRACE_SECONDS
from modules.rooms.models import Participant, Room
from tests.games.support import (
    FakeLifecycle,
    SCOPING_GAME_ID,
    SCOPING_GAME_MARKERS,
)


class RoomWebSocketTests(TransactionTestCase):
    def create_room_with_guests(self, *names):
        room = Room.objects.create(game_id='duelo')
        participants = [
            Participant.objects.create(
                room=room,
                display_name=name,
                game_marker='guante-rojo',
            )
            for name in names
        ]
        return room, participants

    def websocket_path(self, session_id):
        return f'/ws/rooms/active/?session_id={session_id}'

    def start_match_for(self, room, participants):
        """Drive the real match runtime so the projector broadcasts for real.

        The room suite already triggers its broadcasts through a synchronous
        use case driven from the async test; this is the match-runtime analogue.
        """
        return start_match(
            room_id=room.id,
            game_id='duelo',
            seats=(
                (0, str(participants[0].public_id), 'guante-rojo'),
                (1, str(participants[1].public_id), 'guante-azul'),
            ),
            store=DjangoMatchStore(),
            registry=GAME_REGISTRY,
            projector=ChannelMatchProjector(),
        )

    def submit_for(self, match_ref, participant, value, expected_version):
        """Drive one real action through the match runtime.

        The lifecycle is the shared recording fake rather than the real room
        adapter: finishing a match would otherwise broadcast a room-level
        event to these sockets, and this module is about match groups, not
        the room reset that the games API suite already exercises.
        """
        return submit_action(
            match_ref=match_ref,
            participant_ref=str(participant.public_id),
            action_name='pick',
            action_value=value,
            expected_version=expected_version,
            store=DjangoMatchStore(),
            registry=GAME_REGISTRY,
            projector=ChannelMatchProjector(),
            lifecycle=FakeLifecycle(),
        )

    async def connect_two_guests_in_a_match(self, room, participants):
        """Connect both seats, drain presence, start the match, and drain it.

        Returns the two sockets and the ``match.snapshot`` each seat received
        from the socket-side subscription, so a test can assert on the view
        that reached the wire rather than on an internal object.
        """
        first, second = participants
        first_socket = WebsocketCommunicator(
            application, self.websocket_path(first.session_id)
        )
        second_socket = WebsocketCommunicator(
            application, self.websocket_path(second.session_id)
        )
        await first_socket.connect()
        await first_socket.receive_json_from()
        await first_socket.receive_json_from()
        await second_socket.connect()
        await second_socket.receive_json_from()
        await second_socket.receive_json_from()
        await first_socket.receive_json_from()

        match = await database_sync_to_async(self.start_match_for)(
            room, participants
        )
        first_snapshot = await first_socket.receive_json_from()
        second_snapshot = await second_socket.receive_json_from()
        return first_socket, second_socket, match, first_snapshot, second_snapshot

    def test_socket_requires_an_active_participant_token(self):
        room, participants = self.create_room_with_guests('Guest One')
        participants[0].left_at = timezone.now()
        participants[0].save(update_fields=('left_at',))

        async def connect_with_token(session_id):
            communicator = WebsocketCommunicator(
                application,
                self.websocket_path(session_id),
            )
            return await communicator.connect()

        connected, close_code = async_to_sync(connect_with_token)(participants[0].session_id)

        self.assertFalse(connected)
        self.assertEqual(close_code, 4401)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())

    def test_socket_rejects_a_session_ambiguous_across_active_rooms(self):
        first_room, participants = self.create_room_with_guests('Guest One')
        other_room = Room.objects.create(game_id=SCOPING_GAME_ID)
        ambiguous_participant = Participant.objects.create(
            room=other_room,
            session_id=participants[0].session_id,
            display_name='Courier One',
            game_marker=SCOPING_GAME_MARKERS[0],
        )

        async def connect_with_ambiguous_token():
            communicator = WebsocketCommunicator(
                application,
                self.websocket_path(participants[0].session_id),
            )
            result = await communicator.connect()
            if result[0]:
                await communicator.disconnect()
            return result

        connected, close_code = async_to_sync(connect_with_ambiguous_token)()

        self.assertFalse(connected)
        self.assertEqual(close_code, 4401)
        participants[0].refresh_from_db()
        ambiguous_participant.refresh_from_db()
        self.assertEqual(participants[0].presence, Participant.Presence.OFFLINE)
        self.assertEqual(
            ambiguous_participant.presence, Participant.Presence.OFFLINE
        )
        self.assertTrue(Room.objects.filter(pk=first_room.pk).exists())

    def test_room_events_and_snapshots_stay_isolated_between_games(self):
        first_room, first_participants = self.create_room_with_guests('Garden Guest')
        other_room = Room.objects.create(game_id=SCOPING_GAME_ID)
        other_participant = Participant.objects.create(
            room=other_room,
            display_name='Courier Guest',
            game_marker=SCOPING_GAME_MARKERS[0],
        )
        client = APIClient()

        async def connect_and_broadcast():
            first_socket = WebsocketCommunicator(
                application,
                self.websocket_path(first_participants[0].session_id),
            )
            other_socket = WebsocketCommunicator(
                application,
                self.websocket_path(other_participant.session_id),
            )
            first_connected, _ = await first_socket.connect()
            first_snapshot = await first_socket.receive_json_from()
            await first_socket.receive_json_from()
            other_connected, _ = await other_socket.connect()
            other_snapshot = await other_socket.receive_json_from()
            await other_socket.receive_json_from()

            response = await database_sync_to_async(client.post)(
                '/api/rooms/join/',
                {
                    'game_id': first_room.game_id,
                    'display_name': 'Garden Guest Two',
                    'game_marker': 'guante-azul',
                },
                format='json',
            )
            first_event = await first_socket.receive_json_from()
            self.assertTrue(await other_socket.receive_nothing(timeout=0.05))

            await first_socket.disconnect()
            await other_socket.disconnect()
            return (
                first_connected,
                first_snapshot,
                other_connected,
                other_snapshot,
                response,
                first_event,
            )

        (
            first_connected,
            first_snapshot,
            other_connected,
            other_snapshot,
            response,
            first_event,
        ) = async_to_sync(connect_and_broadcast)()

        self.assertTrue(first_connected)
        self.assertTrue(other_connected)
        self.assertEqual(first_snapshot['room']['game_id'], first_room.game_id)
        self.assertEqual(other_snapshot['room']['game_id'], other_room.game_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(first_event['type'], 'player_joined')
        self.assertEqual(first_event['room']['game_id'], first_room.game_id)

    def test_connect_sends_snapshot_and_disconnect_starts_grace_without_deleting(self):
        room, participants = self.create_room_with_guests('Guest One')
        participant = participants[0]

        async def connect_and_disconnect():
            communicator = WebsocketCommunicator(
                application,
                self.websocket_path(participant.session_id),
            )
            connected, _ = await communicator.connect()
            snapshot = await communicator.receive_json_from()
            online_event = await communicator.receive_json_from()
            await communicator.disconnect()
            return connected, snapshot, online_event

        connected, snapshot, online_event = async_to_sync(connect_and_disconnect)()

        participant.refresh_from_db()
        self.assertTrue(connected)
        self.assertEqual(snapshot['type'], 'room.snapshot')
        self.assertEqual(snapshot['room']['participants'][0]['presence'], 'online')
        self.assertNotIn('session_id', snapshot['room']['participants'][0])
        self.assertEqual(online_event['type'], 'participant_online')
        self.assertEqual(participant.presence, Participant.Presence.RECONNECTING)
        self.assertIsNotNone(participant.disconnected_at)
        self.assertIsNone(participant.left_at)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())

    def test_rest_join_ready_and_leave_changes_are_broadcast_to_room_sockets(self):
        room, participants = self.create_room_with_guests('Guest One')
        owner = participants[0]
        client = APIClient()

        async def api_request(method, path, data):
            request = getattr(client, method)
            return await database_sync_to_async(request)(path, data, format='json')

        async def exchange_events():
            communicator = WebsocketCommunicator(
                application,
                self.websocket_path(owner.session_id),
            )
            connected, _ = await communicator.connect()
            initial = await communicator.receive_json_from()
            await communicator.receive_json_from()

            create_response = await api_request(
                'post',
                '/api/rooms/',
                {
                    'game_id': room.game_id,
                    'display_name': 'Guest Two',
                    'game_marker': 'guante-azul',
                },
            )
            create_event = await communicator.receive_json_from()
            created_session_id = create_response.json()['session_id']

            join_response = await api_request(
                'post',
                '/api/rooms/join/',
                {
                    'game_id': room.game_id,
                    'display_name': 'Guest Three',
                    'game_marker': 'guante-verde',
                },
            )
            join_event = await communicator.receive_json_from()

            ready_response = await api_request(
                'patch',
                '/api/rooms/ready/',
                {'session_id': created_session_id, 'is_ready': True},
            )
            ready_event = await communicator.receive_json_from()

            not_ready_response = await api_request(
                'patch',
                '/api/rooms/ready/',
                {'session_id': created_session_id, 'is_ready': False},
            )
            not_ready_event = await communicator.receive_json_from()

            leave_response = await api_request(
                'post',
                '/api/rooms/leave/',
                {'session_id': created_session_id},
            )
            leave_event = await communicator.receive_json_from()
            await communicator.disconnect()
            return (
                connected,
                initial,
                create_response.status_code,
                create_event,
                create_response.json(),
                created_session_id,
                join_response.status_code,
                join_event,
                ready_response.status_code,
                ready_event,
                not_ready_response.status_code,
                not_ready_event,
                leave_response.status_code,
                leave_event,
            )

        (
            connected,
            initial,
            create_status,
            create_event,
            create_payload,
            created_session_id,
            join_status,
            join_event,
            ready_status,
            ready_event,
            not_ready_status,
            not_ready_event,
            leave_status,
            leave_event,
        ) = async_to_sync(exchange_events)()

        self.assertTrue(connected)
        self.assertEqual(initial['type'], 'room.snapshot')
        self.assertEqual(create_status, 200)
        self.assertEqual(create_event['type'], 'player_joined')
        self.assertEqual(create_payload['session_id'], created_session_id)
        self.assertEqual(len(create_event['room']['participants']), 2)
        self.assertEqual(join_status, 200)
        # The room already held two players, so this third session becomes a
        # spectator and announces itself with its own event (S2).
        self.assertEqual(join_event['type'], 'spectator_joined')
        self.assertEqual(len(join_event['room']['participants']), 3)
        self.assertEqual(join_event['room']['participants'][2]['role'], 'spectator')
        self.assertEqual(ready_status, 200)
        self.assertEqual(ready_event['type'], 'ready_changed')
        self.assertTrue(
            next(
                participant['is_ready']
                for participant in ready_event['room']['participants']
                if participant['display_name'] == 'Guest Two'
            )
        )
        self.assertEqual(not_ready_status, 200)
        self.assertEqual(not_ready_event['type'], 'ready_changed')
        self.assertFalse(
            next(
                participant['is_ready']
                for participant in not_ready_event['room']['participants']
                if participant['display_name'] == 'Guest Two'
            )
        )
        self.assertEqual(leave_status, 204)
        self.assertEqual(leave_event['type'], 'player_left')
        self.assertEqual(
            {participant['display_name'] for participant in leave_event['room']['participants']},
            {'Guest One', 'Guest Three'},
        )

    def test_a_spectator_promotion_is_broadcast_to_the_room_sockets(self):
        room, participants = self.create_room_with_guests('Guest One')
        spectator = Participant.objects.create(
            room=room,
            display_name='Guest Two',
            game_marker='guante-azul',
            role=Participant.Role.SPECTATOR,
        )
        client = APIClient()

        async def promote():
            communicator = WebsocketCommunicator(
                application,
                self.websocket_path(spectator.session_id),
            )
            connected, _ = await communicator.connect()
            initial = await communicator.receive_json_from()
            await communicator.receive_json_from()
            response = await database_sync_to_async(client.post)(
                '/api/rooms/play/',
                {'session_id': str(spectator.session_id)},
                format='json',
            )
            event = await communicator.receive_json_from()
            await communicator.disconnect()
            return connected, initial, response, event

        connected, initial, response, event = async_to_sync(promote)()

        self.assertTrue(connected)
        # The snapshot the socket received carries the S6 seat limits for the
        # game, so the lobby can offer the promotion without guessing.
        self.assertEqual(
            initial['room']['seat_limits'], {'min_seats': 2, 'max_seats': 2}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event['type'], 'player_promoted')
        entry = next(
            participant
            for participant in event['room']['participants']
            if participant['participant_ref'] == str(spectator.public_id)
        )
        self.assertEqual(entry['role'], 'player')
        self.assertFalse(entry['is_ready'])

    def test_reconnect_restores_membership_and_receives_a_fresh_snapshot(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        returning_guest = participants[0]
        observer = participants[1]
        client = APIClient()

        async def reconnect_flow():
            observer_socket = WebsocketCommunicator(
                application,
                self.websocket_path(observer.session_id),
            )
            observer_connected, _ = await observer_socket.connect()
            await observer_socket.receive_json_from()
            await observer_socket.receive_json_from()

            first_socket = WebsocketCommunicator(
                application,
                self.websocket_path(returning_guest.session_id),
            )
            guest_connected, _ = await first_socket.connect()
            await first_socket.receive_json_from()
            await first_socket.receive_json_from()
            await observer_socket.receive_json_from()
            await first_socket.disconnect()
            reconnecting_event = await observer_socket.receive_json_from()

            rejoin_response = await database_sync_to_async(client.post)(
                '/api/rooms/join/',
                {
                    'game_id': room.game_id,
                    'session_id': str(returning_guest.session_id),
                },
                format='json',
            )
            rejoined_event = await observer_socket.receive_json_from()

            second_socket = WebsocketCommunicator(
                application,
                self.websocket_path(rejoin_response.json()['session_id']),
            )
            reconnected, _ = await second_socket.connect()
            fresh_snapshot = await second_socket.receive_json_from()
            online_event = await second_socket.receive_json_from()
            observer_online_event = await observer_socket.receive_json_from()

            await second_socket.disconnect()
            await observer_socket.disconnect()
            return (
                observer_connected,
                guest_connected,
                reconnecting_event,
                rejoin_response,
                reconnected,
                fresh_snapshot,
                online_event,
                rejoined_event,
                observer_online_event,
            )

        (
            observer_connected,
            guest_connected,
            reconnecting_event,
            rejoin_response,
            reconnected,
            fresh_snapshot,
            online_event,
            rejoined_event,
            observer_online_event,
        ) = async_to_sync(reconnect_flow)()

        returning_guest.refresh_from_db()
        self.assertTrue(observer_connected)
        self.assertTrue(guest_connected)
        self.assertEqual(reconnecting_event['type'], 'participant_reconnecting')
        self.assertEqual(rejoin_response.status_code, 200)
        self.assertEqual(rejoin_response.json()['session_id'], str(returning_guest.session_id))
        # The room snapshot that announces the reconnect carries the
        # server-computed countdown for the seat that is counting down.
        reconnecting_roster = {
            participant['participant_ref']: participant
            for participant in reconnecting_event['room']['participants']
        }
        returning_entry = reconnecting_roster[str(returning_guest.public_id)]
        self.assertEqual(returning_entry['presence'], 'reconnecting')
        self.assertIsInstance(returning_entry['remaining_seconds'], int)
        self.assertGreater(returning_entry['remaining_seconds'], 0)
        self.assertLessEqual(
            returning_entry['remaining_seconds'], RECONNECT_GRACE_SECONDS
        )
        self.assertTrue(reconnected)
        self.assertEqual(fresh_snapshot['type'], 'room.snapshot')
        self.assertEqual(fresh_snapshot['room']['game_id'], room.game_id)
        self.assertEqual(online_event['type'], 'participant_online')
        self.assertEqual(rejoined_event['type'], 'player_joined')
        self.assertEqual(observer_online_event['type'], 'participant_online')
        self.assertEqual(returning_guest.presence, Participant.Presence.RECONNECTING)
        self.assertIsNone(returning_guest.left_at)

    def test_grace_expiry_publishes_inactive_without_removing_participant(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        disconnected_guest = participants[0]
        observer = participants[1]

        async def expire_grace():
            observer_socket = WebsocketCommunicator(
                application,
                self.websocket_path(observer.session_id),
            )
            await observer_socket.connect()
            await observer_socket.receive_json_from()
            await observer_socket.receive_json_from()

            guest_socket = WebsocketCommunicator(
                application,
                self.websocket_path(disconnected_guest.session_id),
            )
            await guest_socket.connect()
            await guest_socket.receive_json_from()
            await guest_socket.receive_json_from()
            await observer_socket.receive_json_from()

            await guest_socket.disconnect()
            reconnecting_event = await observer_socket.receive_json_from()
            inactive_event = await observer_socket.receive_json_from(timeout=2)
            await observer_socket.disconnect()
            return reconnecting_event, inactive_event

        with patch('modules.rooms.consumers.RECONNECT_GRACE_SECONDS', 0):
            reconnecting_event, inactive_event = async_to_sync(expire_grace)()

        disconnected_guest.refresh_from_db()
        self.assertEqual(reconnecting_event['type'], 'participant_reconnecting')
        self.assertEqual(inactive_event['type'], 'participant_inactive')
        self.assertEqual(disconnected_guest.presence, Participant.Presence.INACTIVE)
        self.assertIsNone(disconnected_guest.left_at)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        self.assertEqual(Participant.objects.filter(room=room).count(), 2)

    def test_each_socket_receives_only_its_own_match_view(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        first, second = participants

        async def exchange():
            (
                first_socket,
                second_socket,
                match,
                first_snapshot,
                second_snapshot,
            ) = await self.connect_two_guests_in_a_match(room, participants)

            await database_sync_to_async(self.submit_for)(
                match.match_ref, first, 'rock', match.version
            )
            first_events = [await first_socket.receive_json_from()]
            second_events = [await second_socket.receive_json_from()]
            self.assertTrue(await first_socket.receive_nothing(timeout=0.05))
            self.assertTrue(await second_socket.receive_nothing(timeout=0.05))

            await first_socket.disconnect()
            await second_socket.disconnect()
            return (
                first_snapshot,
                second_snapshot,
                first_events,
                second_events,
            )

        (
            first_snapshot,
            second_snapshot,
            first_events,
            second_events,
        ) = async_to_sync(exchange)()

        self.assertEqual(first_snapshot['type'], 'match.snapshot')
        self.assertEqual(second_snapshot['type'], 'match.snapshot')
        self.assertEqual(first_snapshot['view']['you'], 'seat-0')
        self.assertEqual(second_snapshot['view']['you'], 'seat-1')
        self.assertEqual(first_snapshot['seat_index'], 0)
        self.assertEqual(second_snapshot['seat_index'], 1)
        self.assertEqual(
            first_snapshot['match_ref'], second_snapshot['match_ref']
        )

        # One action produces exactly one event per seat: a regression that
        # re-added the public group to a seated socket would queue a second one.
        self.assertEqual(len(first_events), 1)
        self.assertEqual(len(second_events), 1)

        # The acting seat's own messages carry its committed pick; the opponent's
        # raw payload must not contain it anywhere, not merely be missing a field.
        self.assertIn('rock', json.dumps(first_events))
        self.assertNotIn('rock', json.dumps(second_events))

    def test_one_event_per_socket_and_seated_sockets_never_get_the_public_view(self):
        room, participants = self.create_room_with_guests(
            'Guest One', 'Guest Two', 'Guest Three'
        )
        first, second, spectator = participants

        async def drain(socket):
            events = [await socket.receive_json_from()]
            while not await socket.receive_nothing(timeout=0.05):
                events.append(await socket.receive_json_from())
            return events

        async def exchange():
            first_socket = WebsocketCommunicator(
                application, self.websocket_path(first.session_id)
            )
            second_socket = WebsocketCommunicator(
                application, self.websocket_path(second.session_id)
            )
            spectator_socket = WebsocketCommunicator(
                application, self.websocket_path(spectator.session_id)
            )

            await first_socket.connect()
            await first_socket.receive_json_from()
            await first_socket.receive_json_from()

            await second_socket.connect()
            await second_socket.receive_json_from()
            await second_socket.receive_json_from()
            await first_socket.receive_json_from()

            await spectator_socket.connect()
            await spectator_socket.receive_json_from()
            await spectator_socket.receive_json_from()
            await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            match = await database_sync_to_async(self.start_match_for)(
                room, participants[:2]
            )
            first_snapshot = await first_socket.receive_json_from()
            second_snapshot = await second_socket.receive_json_from()
            spectator_snapshot = await spectator_socket.receive_json_from()

            await database_sync_to_async(self.submit_for)(
                match.match_ref, first, 'rock', match.version
            )
            first_events = await drain(first_socket)
            second_events = await drain(second_socket)
            spectator_events = await drain(spectator_socket)

            await first_socket.disconnect()
            await second_socket.disconnect()
            await spectator_socket.disconnect()
            return (
                first_snapshot,
                second_snapshot,
                spectator_snapshot,
                first_events,
                second_events,
                spectator_events,
            )

        (
            first_snapshot,
            second_snapshot,
            spectator_snapshot,
            first_events,
            second_events,
            spectator_events,
        ) = async_to_sync(exchange)()

        # Exactly one match.event per socket for the single action.
        self.assertEqual(len(first_events), 1)
        self.assertEqual(len(second_events), 1)
        self.assertEqual(len(spectator_events), 1)
        self.assertEqual(first_events[0]['type'], 'match.event')
        self.assertEqual(second_events[0]['type'], 'match.event')
        self.assertEqual(spectator_events[0]['type'], 'match.event')

        # Each seated socket receives its own view, never the public one.
        self.assertEqual(first_events[0]['view']['you'], 'seat-0')
        self.assertEqual(first_events[0]['view']['your_pick'], 'rock')
        self.assertNotIn('both_picked', first_events[0]['view'])
        self.assertEqual(second_events[0]['view']['you'], 'seat-1')
        self.assertIsNone(second_events[0]['view']['your_pick'])
        self.assertTrue(second_events[0]['view']['opponent_has_picked'])
        self.assertNotIn('both_picked', second_events[0]['view'])
        self.assertNotIn('rock', json.dumps(second_events))

        # The spectator receives the public view, which carries no seat's value.
        self.assertNotIn('you', spectator_events[0]['view'])
        self.assertFalse(spectator_events[0]['view']['both_picked'])
        self.assertNotIn('rock', json.dumps(spectator_events))
        self.assertIsNone(spectator_snapshot['seat_index'])
        self.assertNotIn('you', spectator_snapshot['view'])

    def test_opponent_action_arrives_as_a_match_event_with_a_progress_boolean(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        first, second = participants

        async def exchange():
            (
                first_socket,
                second_socket,
                match,
                _,
                _,
            ) = await self.connect_two_guests_in_a_match(room, participants)

            await database_sync_to_async(self.submit_for)(
                match.match_ref, first, 'rock', match.version
            )
            first_events = [await first_socket.receive_json_from()]
            second_events = [await second_socket.receive_json_from()]
            self.assertTrue(await first_socket.receive_nothing(timeout=0.05))
            self.assertTrue(await second_socket.receive_nothing(timeout=0.05))

            await first_socket.disconnect()
            await second_socket.disconnect()
            return first_events, second_events

        first_events, second_events = async_to_sync(exchange)()

        self.assertEqual(len(first_events), 1)
        self.assertEqual(len(second_events), 1)

        second_seat_event = next(
            message
            for message in second_events
            if message['view'].get('you') == 'seat-1'
        )
        first_seat_event = next(
            message
            for message in first_events
            if message['view'].get('you') == 'seat-0'
        )

        self.assertEqual(second_seat_event['type'], 'match.event')
        self.assertEqual(second_seat_event['event'], 'match_updated')
        self.assertEqual(second_seat_event['version'], 1)
        self.assertEqual(second_seat_event['match_ref'], first_seat_event['match_ref'])
        self.assertIsNone(second_seat_event['view']['your_pick'])
        self.assertTrue(second_seat_event['view']['opponent_has_picked'])
        self.assertEqual(first_seat_event['view']['your_pick'], 'rock')
        self.assertNotIn('rock', json.dumps(second_events))

    def test_socket_connecting_after_the_match_started_receives_a_snapshot(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        second = participants[1]
        self.start_match_for(room, participants)

        async def connect_mid_match():
            communicator = WebsocketCommunicator(
                application, self.websocket_path(second.session_id)
            )
            connected, _ = await communicator.connect()
            messages = []
            for _ in range(3):
                messages.append(await communicator.receive_json_from())
            await communicator.disconnect()
            return connected, messages

        connected, messages = async_to_sync(connect_mid_match)()

        self.assertTrue(connected)
        snapshots = [
            message
            for message in messages
            if message['type'] == 'match.snapshot'
        ]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]['seat_index'], 1)
        self.assertEqual(snapshots[0]['view']['you'], 'seat-1')
        self.assertIsNone(snapshots[0]['view']['your_pick'])
        # S6/S8: a socket that arrives mid-match learns the table's presence from
        # its own snapshot. The connecting socket is already online -- it was
        # marked online before the snapshot was built -- while the other seat
        # has no socket, so it reports as inactive rather than leaking the raw
        # `offline` value. ``remaining_seconds`` is part of every seat entry and
        # is null for both seats here: neither one is inside a reconnect
        # window.
        self.assertEqual(
            snapshots[0]['seats'],
            [
                {'index': 0, 'presence': 'inactive', 'remaining_seconds': None},
                {'index': 1, 'presence': 'online', 'remaining_seconds': None},
            ],
        )
        # S1/S2: the snapshot also carries the additive public ``roster``. It is
        # a sibling of the presence payload, which is asserted unchanged above.
        self.assertEqual(
            [
                {
                    'seat_id': entry['seat_id'],
                    'index': entry['index'],
                    'display_name': entry['display_name'],
                    'game_marker': entry['game_marker'],
                    'game_marker_label': entry['game_marker_label'],
                }
                for entry in snapshots[0]['roster']
            ],
            [
                {
                    'seat_id': 'seat-0',
                    'index': 0,
                    'display_name': 'Guest One',
                    'game_marker': 'guante-rojo',
                    'game_marker_label': 'Guante rojo',
                },
                {
                    'seat_id': 'seat-1',
                    'index': 1,
                    'display_name': 'Guest Two',
                    'game_marker': 'guante-rojo',
                    'game_marker_label': 'Guante rojo',
                },
            ],
        )

    def test_a_rematch_leaves_each_socket_in_exactly_one_match_group(self):
        """A socket holds one match group whatever sequence of matches runs.

        A room that finishes a match and starts a second one is the ordinary
        path, not an exotic one. A socket that keeps the finished match's seat
        group while joining the new match's holds two match groups at once, so
        the single-subscription invariant is false on a rematch even though it
        holds for the first match. Membership is read from the in-memory
        channel layer's groups directly, which is authoritative.
        """
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        first, second = participants
        layer = get_channel_layer()

        async def drain(socket):
            messages = []
            while not await socket.receive_nothing(timeout=0.05):
                messages.append(await socket.receive_json_from())
            return messages

        async def play_to_completion(match):
            """Play seat 0's rock into seat 1's scissors until the match ends."""
            record = match
            for picker, value in (
                (first, 'rock'),
                (second, 'scissors'),
                (first, 'rock'),
                (second, 'scissors'),
            ):
                record = await database_sync_to_async(self.submit_for)(
                    record.match_ref, picker, value, record.version
                )
            return record

        async def exchange():
            first_socket = WebsocketCommunicator(
                application, self.websocket_path(first.session_id)
            )
            second_socket = WebsocketCommunicator(
                application, self.websocket_path(second.session_id)
            )
            await first_socket.connect()
            await first_socket.receive_json_from()
            await first_socket.receive_json_from()
            await second_socket.connect()
            await second_socket.receive_json_from()
            await second_socket.receive_json_from()
            await first_socket.receive_json_from()

            first_match = await database_sync_to_async(self.start_match_for)(
                room, participants
            )
            await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            finished = await play_to_completion(first_match)
            first_match_events = await drain(first_socket)
            second_match_events = await drain(second_socket)

            # Each finished match's seat group holds exactly its one socket, so
            # it identifies that socket's channel before the rematch.
            old_seat_zero = match_seat_group_name(finished.match_ref, 0)
            old_seat_one = match_seat_group_name(finished.match_ref, 1)
            first_channel = next(iter(layer.groups[old_seat_zero]))
            second_channel = next(iter(layer.groups[old_seat_one]))

            second_match = await database_sync_to_async(self.start_match_for)(
                room, participants
            )
            await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            membership = {
                group: sorted(channels)
                for group, channels in layer.groups.items()
                if group.startswith('match_')
            }

            await database_sync_to_async(self.submit_for)(
                second_match.match_ref, first, 'rock', second_match.version
            )
            rematch_first_events = await drain(first_socket)
            rematch_second_events = await drain(second_socket)

            await first_socket.disconnect()
            await second_socket.disconnect()
            return (
                first_channel,
                second_channel,
                finished.match_ref,
                second_match.match_ref,
                membership,
                len(first_match_events),
                len(second_match_events),
                rematch_first_events,
                rematch_second_events,
            )

        (
            first_channel,
            second_channel,
            first_match_ref,
            second_match_ref,
            membership,
            first_match_event_count,
            second_match_event_count,
            rematch_first_events,
            rematch_second_events,
        ) = async_to_sync(exchange)()

        # The first match played to completion: four picks, four events each.
        self.assertEqual(first_match_event_count, 4)
        self.assertEqual(second_match_event_count, 4)

        # Authoritative membership: each socket is in exactly one match group
        # and it is the new match's group.
        def groups_of(channel):
            return {
                group
                for group, channels in membership.items()
                if channel in channels
            }

        new_seat_zero = match_seat_group_name(second_match_ref, 0)
        new_seat_one = match_seat_group_name(second_match_ref, 1)
        self.assertEqual(groups_of(first_channel), {new_seat_zero})
        self.assertEqual(groups_of(second_channel), {new_seat_one})

        # The finished match's groups no longer hold either socket's channel.
        self.assertNotIn(
            first_channel,
            membership.get(match_seat_group_name(first_match_ref, 0), []),
        )
        self.assertNotIn(
            second_channel,
            membership.get(match_seat_group_name(first_match_ref, 1), []),
        )

        # One action in the second match still delivers one event per socket.
        self.assertEqual(len(rematch_first_events), 1)
        self.assertEqual(len(rematch_second_events), 1)
        self.assertEqual(rematch_first_events[0]['type'], 'match.event')
        self.assertEqual(rematch_second_events[0]['type'], 'match.event')
        self.assertEqual(rematch_first_events[0]['match_ref'], second_match_ref)

    def test_a_disconnect_announces_the_rival_seat_as_reconnecting(self):
        room, participants = self.create_room_with_guests(
            'Guest One', 'Guest Two'
        )
        first, second = participants

        async def exchange():
            (
                first_socket,
                second_socket,
                match,
                _,
                _,
            ) = await self.connect_two_guests_in_a_match(room, participants)

            await second_socket.disconnect()

            messages = []
            while True:
                message = await first_socket.receive_json_from(timeout=2)
                messages.append(message)
                if message['type'] == 'match.presence':
                    break

            await first_socket.disconnect()
            return match, messages

        match, messages = async_to_sync(exchange)()

        presence = next(
            message
            for message in messages
            if message['type'] == 'match.presence'
        )
        self.assertEqual(presence['match_ref'], match.match_ref)
        self.assertEqual(
            {seat['index']: seat['presence'] for seat in presence['seats']},
            {0: 'online', 1: 'reconnecting'},
        )

    def test_grace_expiry_resolves_the_match_for_the_remaining_seat(self):
        room, participants = self.create_room_with_guests(
            'Guest One', 'Guest Two'
        )
        first, second = participants

        async def exchange():
            (
                first_socket,
                second_socket,
                match,
                _,
                _,
            ) = await self.connect_two_guests_in_a_match(room, participants)

            await second_socket.disconnect()

            messages = []
            while True:
                message = await first_socket.receive_json_from(timeout=2)
                messages.append(message)
                if (
                    message['type'] == 'match.event'
                    and message['event'] == 'match_finished'
                ):
                    break

            await first_socket.disconnect()
            return match, messages

        with patch('modules.rooms.consumers.RECONNECT_GRACE_SECONDS', 0):
            match, messages = async_to_sync(exchange)()

        # The expired seat is announced as inactive before the outcome reaches
        # the remaining seat, so it can tell "not coming back" from "gone".
        presences = [
            message
            for message in messages
            if message['type'] == 'match.presence'
        ]
        self.assertTrue(presences)
        self.assertEqual(
            {
                seat['index']: seat['presence']
                for seat in presences[-1]['seats']
            },
            {0: 'online', 1: 'inactive'},
        )

        finished_event = next(
            message
            for message in messages
            if message['type'] == 'match.event'
            and message['event'] == 'match_finished'
        )
        self.assertEqual(finished_event['match_ref'], match.match_ref)
        self.assertTrue(finished_event['view']['ended_by_abandon'])
        self.assertEqual(finished_event['view']['winner'], 'seat-0')

        finished = Match.objects.get(public_id=match.match_ref)
        self.assertEqual(finished.status, Match.Status.FINISHED)
        self.assertEqual(finished.winner_seat, 'seat-0')
