from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from config.asgi import application
from .models import Participant, Room


class RoomWebSocketTests(TransactionTestCase):
    def create_room_with_guests(self, *names):
        room = Room.objects.create(game_id='starlight-garden')
        participants = [
            Participant.objects.create(
                room=room,
                display_name=name,
                game_marker='silver-leaf',
            )
            for name in names
        ]
        return room, participants

    def websocket_path(self, session_id):
        return f'/ws/rooms/active/?session_id={session_id}'

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
                    'game_marker': 'moonstone',
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
                    'game_marker': 'night-bloom',
                },
            )
            join_event = await communicator.receive_json_from()
            joined_session_id = join_response.json()['session_id']

            ready_response = await api_request(
                'patch',
                '/api/rooms/ready/',
                {'session_id': joined_session_id, 'is_ready': True},
            )
            ready_event = await communicator.receive_json_from()

            leave_response = await api_request(
                'post',
                '/api/rooms/leave/',
                {'session_id': joined_session_id},
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
        self.assertEqual(join_event['type'], 'player_joined')
        self.assertEqual(len(join_event['room']['participants']), 3)
        self.assertEqual(ready_status, 200)
        self.assertEqual(ready_event['type'], 'ready_changed')
        self.assertTrue(
            next(
                participant['is_ready']
                for participant in ready_event['room']['participants']
                if participant['display_name'] == 'Guest Three'
            )
        )
        self.assertEqual(leave_status, 204)
        self.assertEqual(leave_event['type'], 'player_left')
        self.assertEqual(
            {participant['display_name'] for participant in leave_event['room']['participants']},
            {'Guest One', 'Guest Two'},
        )

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

        with patch('rooms.consumers.RECONNECT_GRACE_SECONDS', 0):
            reconnecting_event, inactive_event = async_to_sync(expire_grace)()

        disconnected_guest.refresh_from_db()
        self.assertEqual(reconnecting_event['type'], 'participant_reconnecting')
        self.assertEqual(inactive_event['type'], 'participant_inactive')
        self.assertEqual(disconnected_guest.presence, Participant.Presence.INACTIVE)
        self.assertIsNone(disconnected_guest.left_at)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        self.assertEqual(Participant.objects.filter(room=room).count(), 2)
