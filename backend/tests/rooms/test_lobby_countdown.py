"""End-to-end tests for the socket-announced lobby countdown (CDS-03).

Every test drives the real REST ready path and the real ``RoomConsumer`` over
an in-memory channel layer, following the ``async_to_sync(coro)()`` and
``WebsocketCommunicator`` pattern of ``test_websockets.py``. The duration is
patched on the compatibility module (``modules.rooms.consumers``) where it
matters, so the socket path and its in-process timer agree on it.
"""

import asyncio

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from unittest.mock import patch

from config.asgi import application
from modules.games.models import Match
from modules.rooms.models import Participant, Room

COUNTDOWN_PATCH = 'modules.rooms.consumers.LOBBY_COUNTDOWN_SECONDS'


class LobbyCountdownWebSocketTests(TransactionTestCase):
    def create_room_with_guests(self, *names):
        room = Room.objects.create(game_id='duelo')
        markers = ('guante-rojo', 'guante-azul', 'guante-verde')
        participants = [
            Participant.objects.create(
                room=room,
                display_name=name,
                game_marker=markers[index],
            )
            for index, name in enumerate(names)
        ]
        return room, participants

    def websocket_path(self, session_id):
        return f'/ws/rooms/active/?session_id={session_id}'

    async def connect(self, session_id):
        """Connect a socket and read only its opening ``room.snapshot``.

        The presence event that the connect path publishes is group-sent and
        queued behind the coroutine, so it can arrive after the countdown a
        later ``receive_until`` is looking for. Tests therefore never assume
        the position of any message past the snapshot.
        """
        socket = WebsocketCommunicator(
            application, self.websocket_path(session_id)
        )
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        snapshot = await socket.receive_json_from()
        self.assertEqual(snapshot['type'], 'room.snapshot')
        return socket

    async def receive_until(self, socket, wanted_type, limit=10, timeout=2):
        """Receive messages until one has ``wanted_type``, then stop.

        Returns every message received up to and including the wanted one, so
        a caller can assert on events that raced ahead of it. A timeout or the
        limit is a real test failure, surfaced by the missing message.
        """
        messages = []
        for _ in range(limit):
            try:
                message = await socket.receive_json_from(timeout=timeout)
            except asyncio.TimeoutError:
                break
            messages.append(message)
            if message.get('type') == wanted_type:
                break
        return messages

    async def mark_ready(self, client, session_id, is_ready):
        response = await database_sync_to_async(client.patch)(
            '/api/rooms/ready/',
            {'session_id': str(session_id), 'is_ready': is_ready},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_both_ready_players_receive_the_countdown_without_a_match(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        client = APIClient()

        async def scenario():
            first = await self.connect(participants[0].session_id)
            second = await self.connect(participants[1].session_id)

            await self.mark_ready(client, participants[0].session_id, True)
            await self.mark_ready(client, participants[1].session_id, True)

            first_messages = await self.receive_until(first, 'match_countdown')
            second_messages = await self.receive_until(second, 'match_countdown')

            await first.disconnect()
            await second.disconnect()
            return first_messages, second_messages

        with patch(COUNTDOWN_PATCH, 5):
            first_messages, second_messages = async_to_sync(scenario)()

        first_countdown = next(
            message for message in first_messages
            if message['type'] == 'match_countdown'
        )
        second_countdown = next(
            message for message in second_messages
            if message['type'] == 'match_countdown'
        )
        # Both sockets see the announcement with the full remaining time.
        self.assertEqual(
            first_countdown['countdown'],
            {'seconds': 5, 'remaining_seconds': 5},
        )
        self.assertEqual(
            second_countdown['countdown'],
            {'seconds': 5, 'remaining_seconds': 5},
        )
        self.assertTrue(
            all(
                participant['is_ready']
                for participant in first_countdown['room']['participants']
            )
        )
        # The announcement alone must never open the match.
        self.assertEqual(
            Match.objects.filter(
                room=room, status=Match.Status.IN_PROGRESS
            ).count(),
            0,
        )

    def test_a_lone_ready_player_never_receives_a_countdown(self):
        room, participants = self.create_room_with_guests('Guest One')
        participants[0].is_ready = True
        participants[0].save(update_fields=('is_ready',))

        async def scenario():
            socket = await self.connect(participants[0].session_id)
            await self.receive_until(socket, 'participant_online')
            quiet = await socket.receive_nothing(timeout=0.2)
            await socket.disconnect()
            return quiet

        with patch(COUNTDOWN_PATCH, 5):
            quiet = async_to_sync(scenario)()

        self.assertTrue(quiet)

    def test_not_ready_cancels_the_countdown_and_ready_rearms_it(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        client = APIClient()

        async def scenario():
            first = await self.connect(participants[0].session_id)
            second = await self.connect(participants[1].session_id)

            await self.mark_ready(client, participants[0].session_id, True)
            await self.mark_ready(client, participants[1].session_id, True)
            await self.receive_until(first, 'match_countdown')
            await self.receive_until(second, 'match_countdown')

            await self.mark_ready(client, participants[0].session_id, False)
            first_cancelled = await self.receive_until(
                first, 'match_countdown_cancelled'
            )
            second_cancelled = await self.receive_until(
                second, 'match_countdown_cancelled'
            )

            await self.mark_ready(client, participants[0].session_id, True)
            first_rearmed = await self.receive_until(first, 'match_countdown')
            second_rearmed = await self.receive_until(second, 'match_countdown')

            await first.disconnect()
            await second.disconnect()
            return first_cancelled, second_cancelled, first_rearmed, second_rearmed

        with patch(COUNTDOWN_PATCH, 30):
            (
                first_cancelled,
                second_cancelled,
                first_rearmed,
                second_rearmed,
            ) = async_to_sync(scenario)()

        for messages in (first_cancelled, second_cancelled):
            cancellation = next(
                message for message in messages
                if message['type'] == 'match_countdown_cancelled'
            )
            self.assertEqual(
                cancellation['countdown'], {'reason': 'lobby_changed'}
            )
        for messages in (first_rearmed, second_rearmed):
            rearmed = next(
                message for message in messages
                if message['type'] == 'match_countdown'
            )
            self.assertEqual(
                rearmed['countdown'],
                {'seconds': 30, 'remaining_seconds': 30},
            )

    def test_expired_countdown_starts_the_match_and_seats_both_players(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        client = APIClient()

        async def scenario():
            first = await self.connect(participants[0].session_id)
            second = await self.connect(participants[1].session_id)

            await self.mark_ready(client, participants[0].session_id, True)
            await self.mark_ready(client, participants[1].session_id, True)

            first_messages = await self.receive_until(first, 'match.snapshot')
            second_messages = await self.receive_until(second, 'match.snapshot')

            await first.disconnect()
            await second.disconnect()
            return first_messages, second_messages

        with patch(COUNTDOWN_PATCH, 0):
            first_messages, second_messages = async_to_sync(scenario)()

        first_snapshot = next(
            message for message in first_messages
            if message['type'] == 'match.snapshot'
        )
        second_snapshot = next(
            message for message in second_messages
            if message['type'] == 'match.snapshot'
        )
        self.assertEqual(first_snapshot['seat_index'], 0)
        self.assertEqual(second_snapshot['seat_index'], 1)
        self.assertEqual(
            first_snapshot['match_ref'], second_snapshot['match_ref']
        )
        self.assertEqual(
            Match.objects.filter(
                room=room, status=Match.Status.IN_PROGRESS
            ).count(),
            1,
        )

    def test_connecting_while_armed_receives_the_remaining_seconds(self):
        room, participants = self.create_room_with_guests('Guest One', 'Guest Two')
        for participant in participants:
            participant.is_ready = True
            participant.save(update_fields=('is_ready',))

        async def scenario():
            first = await self.connect(participants[0].session_id)
            await self.receive_until(first, 'match_countdown')

            second = await self.connect(participants[1].session_id)
            messages = await self.receive_until(second, 'match_countdown')

            await first.disconnect()
            await second.disconnect()
            return messages

        with patch(COUNTDOWN_PATCH, 30):
            messages = async_to_sync(scenario)()

        countdown = next(
            message for message in messages
            if message['type'] == 'match_countdown'
        )
        self.assertEqual(countdown['countdown']['seconds'], 30)
        self.assertGreaterEqual(countdown['countdown']['remaining_seconds'], 0)
        self.assertLessEqual(countdown['countdown']['remaining_seconds'], 30)
