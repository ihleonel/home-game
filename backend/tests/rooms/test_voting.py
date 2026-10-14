from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.test import APIClient, APITestCase

from config.asgi import application
from modules.rooms.connections import register_connection, unregister_connection
from modules.rooms.features.membership.domain.rules import SPECTATOR_ROLE
from modules.rooms.models import ExpulsionBallot, ExpulsionVote, Participant, Room
from tests.games.support import SCOPING_GAME_ID, SCOPING_GAME_MARKERS


class ExpulsionVoteApiTests(APITestCase):
    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.initiator = self.create_participant('Guest One', Participant.Presence.ONLINE)
        self.other_voter = self.create_participant('Guest Two', Participant.Presence.ONLINE)
        self.target = self.create_participant(
            'Guest Three',
            Participant.Presence.INACTIVE,
            disconnected_at=timezone.now() - timedelta(seconds=61),
        )
        self.registered_connections = []
        self.register_participant_connection(self.initiator)
        self.register_participant_connection(self.other_voter)

    def tearDown(self):
        for room_id, session_id, channel_name in self.registered_connections:
            unregister_connection(room_id, session_id, channel_name)
        super().tearDown()

    def register_participant_connection(self, participant):
        channel_name = f'test-voter-{participant.public_id}'
        session_id = str(participant.session_id)
        register_connection(participant.room_id, session_id, channel_name)
        self.registered_connections.append(
            (participant.room_id, session_id, channel_name)
        )

    def create_participant(
        self,
        name,
        presence,
        disconnected_at=None,
        room=None,
        game_marker='guante-rojo',
        role=None,
    ):
        fields = {
            'room': room or self.room,
            'display_name': name,
            'game_marker': game_marker,
            'presence': presence,
            'disconnected_at': disconnected_at,
        }
        if role is not None:
            fields['role'] = role
        return Participant.objects.create(**fields)

    def start_vote(self, caller=None):
        return self.client.post(
            '/api/rooms/expulsion-votes/',
            {
                'session_id': str((caller or self.initiator).session_id),
                'target_ref': str(self.target.public_id),
            },
            format='json',
        )

    def cast_ballot(self, vote, voter, choice):
        return self.client.post(
            f"/api/rooms/expulsion-votes/{vote['vote_ref']}/ballots/",
            {'session_id': str(voter.session_id), 'choice': choice},
            format='json',
        )

    def test_vote_persists_fixed_voters_using_non_bearer_public_refs(self):
        response = self.start_vote()

        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        vote = ExpulsionVote.objects.get()
        self.assertEqual(vote.status, ExpulsionVote.Status.PENDING)
        self.assertEqual(
            set(vote.ballots.values_list('voter_id', flat=True)),
            {self.initiator.pk, self.other_voter.pk},
        )
        self.assertNotIn(self.target.pk, vote.ballots.values_list('voter_id', flat=True))
        self.assertEqual(response.data['vote']['eligible_count'], 2)
        self.assertEqual(len(response.data['vote']['ballots']), 2)
        for participant in response.data['room']['participants']:
            self.assertIn('participant_ref', participant)
            self.assertNotIn('session_id', participant)
            self.assertNotIn('id', participant)
        self.assertNotIn('session_id', response.data['vote'])
        self.assertTrue(
            all('session_id' not in ballot for ballot in response.data['vote']['ballots'])
        )
        target_ballot = self.cast_ballot(response.data['vote'], self.target, 'yes')
        self.assertEqual(target_ballot.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_start_vote_resolves_the_callers_active_room(self):
        other_room = Room.objects.create(game_id=SCOPING_GAME_ID)
        caller = self.create_participant(
            'Courier One',
            Participant.Presence.ONLINE,
            room=other_room,
            game_marker=SCOPING_GAME_MARKERS[0],
        )
        voter = self.create_participant(
            'Courier Two',
            Participant.Presence.ONLINE,
            room=other_room,
            game_marker=SCOPING_GAME_MARKERS[1],
        )
        target = self.create_participant(
            'Courier Three',
            Participant.Presence.INACTIVE,
            disconnected_at=timezone.now() - timedelta(seconds=61),
            room=other_room,
            game_marker=SCOPING_GAME_MARKERS[2],
        )
        self.register_participant_connection(caller)
        self.register_participant_connection(voter)

        response = self.client.post(
            '/api/rooms/expulsion-votes/',
            {
                'session_id': str(caller.session_id),
                'target_ref': str(target.public_id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(response.data['room']['game_id'], other_room.game_id)
        vote = ExpulsionVote.objects.get()
        self.assertEqual(vote.room_id, other_room.pk)
        self.assertEqual(
            set(vote.ballots.values_list('voter_id', flat=True)),
            {caller.pk, voter.pk},
        )

    def test_start_vote_rejects_a_session_ambiguous_across_rooms(self):
        other_room = Room.objects.create(game_id=SCOPING_GAME_ID)
        duplicate = self.create_participant(
            'Duplicate Courier Session',
            Participant.Presence.ONLINE,
            room=other_room,
            game_marker=SCOPING_GAME_MARKERS[0],
        )
        duplicate.session_id = self.initiator.session_id
        duplicate.save(update_fields=('session_id', 'updated_at'))

        response = self.start_vote()

        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertFalse(ExpulsionVote.objects.exists())

    def test_cast_ballot_resolves_the_room_from_the_vote_reference(self):
        other_room = Room.objects.create(game_id=SCOPING_GAME_ID)
        caller = self.create_participant(
            'Courier One',
            Participant.Presence.ONLINE,
            room=other_room,
            game_marker=SCOPING_GAME_MARKERS[0],
        )
        voter = self.create_participant(
            'Courier Two',
            Participant.Presence.ONLINE,
            room=other_room,
            game_marker=SCOPING_GAME_MARKERS[1],
        )
        target = self.create_participant(
            'Courier Three',
            Participant.Presence.INACTIVE,
            disconnected_at=timezone.now() - timedelta(seconds=61),
            room=other_room,
            game_marker=SCOPING_GAME_MARKERS[2],
        )
        vote = ExpulsionVote.objects.create(
            room=other_room,
            target=target,
            initiated_by=caller,
        )
        ExpulsionBallot.objects.create(vote=vote, voter=caller)
        ExpulsionBallot.objects.create(vote=vote, voter=voter)
        self.register_participant_connection(voter)

        response = self.cast_ballot(
            {'vote_ref': str(vote.public_id)}, voter, 'no'
        )

        vote.refresh_from_db()
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['room']['game_id'], other_room.game_id)
        self.assertEqual(response.data['vote']['status'], ExpulsionVote.Status.REJECTED)
        self.assertEqual(vote.status, ExpulsionVote.Status.REJECTED)
        self.assertIsNone(target.left_at)

    def test_joiner_after_vote_start_cannot_vote(self):
        response = self.start_vote()
        late_voter = self.create_participant('Late Guest', Participant.Presence.ONLINE)
        self.register_participant_connection(late_voter)

        ballot_response = self.cast_ballot(response.data['vote'], late_voter, 'yes')

        self.assertEqual(ballot_response.status_code, http_status.HTTP_403_FORBIDDEN)
        self.assertEqual(ExpulsionVote.objects.get().ballots.count(), 2)

    def test_spectator_target_is_not_a_participant_for_the_vote(self):
        spectator = self.create_participant(
            'Guest Spectator',
            Participant.Presence.ONLINE,
            role=SPECTATOR_ROLE,
        )
        self.register_participant_connection(spectator)

        response = self.client.post(
            '/api/rooms/expulsion-votes/',
            {
                'session_id': str(self.initiator.session_id),
                'target_ref': str(spectator.public_id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.data['detail'],
            'La persona propuesta no es un participante activo de la sala.',
        )
        self.assertFalse(ExpulsionVote.objects.exists())

    def test_spectator_present_at_vote_start_holds_no_ballot(self):
        spectator = self.create_participant(
            'Guest Spectator',
            Participant.Presence.ONLINE,
            role=SPECTATOR_ROLE,
        )
        self.register_participant_connection(spectator)

        response = self.start_vote()
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(response.data['vote']['eligible_count'], 2)

        ballot_response = self.cast_ballot(response.data['vote'], spectator, 'yes')

        self.assertEqual(ballot_response.status_code, http_status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            ballot_response.data['detail'],
            'No tenías derecho a votar cuando comenzó la votación.',
        )
        self.assertEqual(ExpulsionVote.objects.get().ballots.count(), 2)

    def test_vote_between_players_ignores_a_present_spectator(self):
        spectator = self.create_participant(
            'Guest Spectator',
            Participant.Presence.ONLINE,
            role=SPECTATOR_ROLE,
        )
        self.register_participant_connection(spectator)

        response = self.start_vote()

        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        vote = ExpulsionVote.objects.get()
        self.assertEqual(
            set(vote.ballots.values_list('voter_id', flat=True)),
            {self.initiator.pk, self.other_voter.pk},
        )
        self.assertNotIn(
            spectator.pk, vote.ballots.values_list('voter_id', flat=True)
        )
        self.assertEqual(response.data['vote']['eligible_count'], 2)

        first = self.cast_ballot(response.data['vote'], self.initiator, 'yes')
        self.assertEqual(first.data['vote']['status'], ExpulsionVote.Status.PENDING)
        approved = self.cast_ballot(response.data['vote'], self.other_voter, 'yes')
        self.assertEqual(approved.data['vote']['status'], ExpulsionVote.Status.APPROVED)

        self.target.refresh_from_db()
        self.assertIsNotNone(self.target.left_at)

    def test_no_ballot_rejects_vote_without_expelling_target(self):
        response = self.start_vote()

        rejected = self.cast_ballot(response.data['vote'], self.other_voter, 'no')

        self.target.refresh_from_db()
        self.assertEqual(rejected.status_code, http_status.HTTP_200_OK)
        self.assertEqual(rejected.data['vote']['status'], ExpulsionVote.Status.REJECTED)
        self.assertIsNone(self.target.left_at)
        self.assertEqual(self.target.presence, Participant.Presence.INACTIVE)
        self.assertTrue(
            any(
                item['participant_ref'] == str(self.target.public_id)
                for item in rejected.data['room']['participants']
            )
        )

    def test_unanimous_yes_expel_target_and_block_same_session_rejoin(self):
        response = self.start_vote()
        first_vote = self.cast_ballot(response.data['vote'], self.initiator, 'yes')
        self.assertEqual(first_vote.data['vote']['status'], ExpulsionVote.Status.PENDING)
        duplicate_ballot = self.cast_ballot(response.data['vote'], self.initiator, 'no')
        self.assertEqual(duplicate_ballot.status_code, http_status.HTTP_409_CONFLICT)

        approved = self.cast_ballot(response.data['vote'], self.other_voter, 'yes')

        self.target.refresh_from_db()
        self.assertEqual(approved.data['vote']['status'], ExpulsionVote.Status.APPROVED)
        self.assertIsNotNone(self.target.left_at)
        self.assertEqual(self.target.presence, Participant.Presence.OFFLINE)
        self.assertFalse(
            any(
                item['participant_ref'] == str(self.target.public_id)
                for item in approved.data['room']['participants']
            )
        )
        rejoin = self.client.post(
            '/api/rooms/join/',
            {
                'game_id': self.room.game_id,
                'session_id': str(self.target.session_id),
            },
            format='json',
        )
        self.assertEqual(rejoin.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_target_rejoin_past_the_grace_window_is_reaped_and_cancels_the_pending_vote(self):
        started = self.start_vote()

        rejoin = self.client.post(
            '/api/rooms/join/',
            {
                'game_id': self.room.game_id,
                'session_id': str(self.target.session_id),
            },
            format='json',
        )

        self.target.refresh_from_db()
        vote = ExpulsionVote.objects.get()
        self.assertEqual(rejoin.status_code, http_status.HTTP_200_OK)
        self.assertEqual(vote.status, ExpulsionVote.Status.CANCELLED)
        # The target was reaped before membership resolution, so the rejoin is
        # a fresh arrival and cancels the vote as a departure, not a reconnect.
        self.assertEqual(vote.resolution_reason, 'target_left')
        self.assertIsNone(self.target.left_at)
        self.assertEqual(self.target.presence, Participant.Presence.OFFLINE)
        self.assertIsNone(rejoin.data['room']['expulsion_vote'])
        self.assertEqual(started.status_code, http_status.HTTP_201_CREATED)

    def test_vote_requires_inactive_target_and_connected_initiator(self):
        self.target.presence = Participant.Presence.RECONNECTING
        self.target.disconnected_at = timezone.now() - timedelta(seconds=30)
        self.target.save(update_fields=('presence', 'disconnected_at'))
        self.assertEqual(self.start_vote().status_code, http_status.HTTP_409_CONFLICT)

        self.target.presence = Participant.Presence.INACTIVE
        self.target.disconnected_at = timezone.now() - timedelta(seconds=61)
        self.target.save(update_fields=('presence', 'disconnected_at'))
        self.initiator.presence = Participant.Presence.OFFLINE
        self.initiator.save(update_fields=('presence',))
        self.assertEqual(self.start_vote().status_code, http_status.HTTP_403_FORBIDDEN)


class ExpulsionVoteWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.first_voter = Participant.objects.create(
            room=self.room,
            display_name='Guest One',
            game_marker='guante-rojo',
            presence=Participant.Presence.ONLINE,
        )
        self.disconnecting_voter = Participant.objects.create(
            room=self.room,
            display_name='Guest Two',
            game_marker='guante-azul',
            presence=Participant.Presence.ONLINE,
        )
        self.target = Participant.objects.create(
            room=self.room,
            display_name='Guest Three',
            game_marker='guante-verde',
            presence=Participant.Presence.INACTIVE,
            disconnected_at=timezone.now() - timedelta(seconds=61),
        )

    def websocket_path(self, session_id):
        return f'/ws/rooms/active/?session_id={session_id}'

    def test_eligible_voter_disconnect_cancels_vote_without_shrinking_voter_set(self):
        client = APIClient()

        async def run_vote_disconnect():
            first_socket = WebsocketCommunicator(
                application,
                self.websocket_path(self.first_voter.session_id),
            )
            disconnecting_socket = WebsocketCommunicator(
                application,
                self.websocket_path(self.disconnecting_voter.session_id),
            )
            first_connected, _ = await first_socket.connect()
            disconnecting_connected, _ = await disconnecting_socket.connect()
            await first_socket.receive_json_from()
            await disconnecting_socket.receive_json_from()

            start_response = await database_sync_to_async(client.post)(
                '/api/rooms/expulsion-votes/',
                {
                    'session_id': str(self.first_voter.session_id),
                    'target_ref': str(self.target.public_id),
                },
                format='json',
            )
            first_start_event = await first_socket.receive_json_from()
            disconnecting_start_event = await disconnecting_socket.receive_json_from()

            await disconnecting_socket.disconnect()
            reconnecting_event = await first_socket.receive_json_from()
            cancelled_event = await first_socket.receive_json_from()
            await first_socket.disconnect()
            return (
                first_connected,
                disconnecting_connected,
                start_response,
                first_start_event,
                disconnecting_start_event,
                reconnecting_event,
                cancelled_event,
            )

        (
            first_connected,
            disconnecting_connected,
            start_response,
            first_start_event,
            disconnecting_start_event,
            reconnecting_event,
            cancelled_event,
        ) = async_to_sync(run_vote_disconnect)()

        vote = ExpulsionVote.objects.get()
        self.disconnecting_voter.refresh_from_db()
        self.assertTrue(first_connected)
        self.assertTrue(disconnecting_connected)
        self.assertEqual(start_response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(first_start_event['type'], 'expulsion_vote_started')
        self.assertEqual(disconnecting_start_event['type'], 'expulsion_vote_started')
        self.assertEqual(reconnecting_event['type'], 'participant_reconnecting')
        self.assertEqual(cancelled_event['type'], 'expulsion_vote_cancelled')
        self.assertEqual(cancelled_event['vote']['resolution_reason'], 'eligible_voter_disconnected')
        self.assertEqual(vote.status, ExpulsionVote.Status.CANCELLED)
        self.assertEqual(vote.ballots.count(), 2)
        self.assertTrue(all(ballot.choice is None for ballot in vote.ballots.all()))
        self.assertIsNone(self.disconnecting_voter.left_at)

    def test_vote_start_rejection_update_and_approval_are_broadcast(self):
        client = APIClient()

        async def api_post(path, data):
            return await database_sync_to_async(client.post)(
                path,
                data,
                format='json',
            )

        async def vote_lifecycle():
            first_socket = WebsocketCommunicator(
                application,
                self.websocket_path(self.first_voter.session_id),
            )
            second_socket = WebsocketCommunicator(
                application,
                self.websocket_path(self.disconnecting_voter.session_id),
            )
            await first_socket.connect()
            await second_socket.connect()
            await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            start_one = await api_post(
                '/api/rooms/expulsion-votes/',
                {
                    'session_id': str(self.first_voter.session_id),
                    'target_ref': str(self.target.public_id),
                },
            )
            started_one = await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            reject = await api_post(
                f"/api/rooms/expulsion-votes/{start_one.json()['vote']['vote_ref']}/ballots/",
                {'session_id': str(self.disconnecting_voter.session_id), 'choice': 'no'},
            )
            rejected = await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            start_two = await api_post(
                '/api/rooms/expulsion-votes/',
                {
                    'session_id': str(self.first_voter.session_id),
                    'target_ref': str(self.target.public_id),
                },
            )
            started_two = await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            first_yes = await api_post(
                f"/api/rooms/expulsion-votes/{start_two.json()['vote']['vote_ref']}/ballots/",
                {'session_id': str(self.first_voter.session_id), 'choice': 'yes'},
            )
            updated = await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            final_yes = await api_post(
                f"/api/rooms/expulsion-votes/{start_two.json()['vote']['vote_ref']}/ballots/",
                {'session_id': str(self.disconnecting_voter.session_id), 'choice': 'yes'},
            )
            approved = await first_socket.receive_json_from()
            await second_socket.receive_json_from()

            await first_socket.disconnect()
            await second_socket.disconnect()
            return start_one, started_one, reject, rejected, start_two, started_two, first_yes, updated, final_yes, approved

        (
            start_one,
            started_one,
            reject,
            rejected,
            start_two,
            started_two,
            first_yes,
            updated,
            final_yes,
            approved,
        ) = async_to_sync(vote_lifecycle)()

        self.target.refresh_from_db()
        self.assertEqual(start_one.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(started_one['type'], 'expulsion_vote_started')
        self.assertNotIn('session_id', started_one['vote'])
        self.assertEqual(reject.status_code, http_status.HTTP_200_OK)
        self.assertEqual(rejected['type'], 'expulsion_vote_rejected')
        self.assertEqual(start_two.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(started_two['type'], 'expulsion_vote_started')
        self.assertEqual(first_yes.status_code, http_status.HTTP_200_OK)
        self.assertEqual(updated['type'], 'expulsion_vote_updated')
        self.assertEqual(updated['vote']['yes_count'], 1)
        self.assertEqual(final_yes.status_code, http_status.HTTP_200_OK)
        self.assertEqual(approved['type'], 'expulsion_vote_approved')
        self.assertEqual(approved['vote']['status'], ExpulsionVote.Status.APPROVED)
        self.assertIsNotNone(self.target.left_at)
        self.assertEqual(self.target.presence, Participant.Presence.OFFLINE)
