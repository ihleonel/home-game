from django.test import SimpleTestCase, TestCase
from django.utils import translation

from modules.rooms.events import room_snapshot
from modules.rooms.features.membership.domain.rules import (
    is_disconnected_presence,
    membership_change,
)
from modules.rooms.features.readiness.domain.rules import readiness_change
from modules.rooms.models import ExpulsionBallot, ExpulsionVote, Participant, Room
from modules.rooms.serializers import RoomRequestSerializer, RoomSerializer


class RoomRequestSerializerTests(SimpleTestCase):
    def test_framework_validation_messages_use_spanish(self):
        with translation.override('es-es'):
            serializer = RoomRequestSerializer(data={})

            self.assertFalse(serializer.is_valid())

        self.assertEqual(
            str(serializer.errors['game_id'][0]),
            'Este campo es requerido.',
        )


class MembershipDomainTests(SimpleTestCase):
    def test_rejoin_emits_join_event_and_resets_leave_and_presence_fields(self):
        change = membership_change(
            was_left=True,
            was_disconnected=True,
            current_display_name='Guest',
            current_game_marker='badge-a',
            data={'display_name': 'Guest Updated'},
        )

        self.assertEqual(change.event_name, 'player_joined')
        self.assertEqual(
            dict(change.updates),
            {
                'display_name': 'Guest Updated',
                'left_at': None,
                'presence': 'offline',
                'disconnected_at': None,
            },
        )

    def test_unchanged_active_membership_does_not_emit_an_event(self):
        change = membership_change(
            was_left=False,
            was_disconnected=False,
            current_display_name='Guest',
            current_game_marker='badge-a',
            data={'display_name': 'Guest', 'game_marker': 'badge-a'},
        )

        self.assertEqual(change.updates, ())
        self.assertIsNone(change.event_name)

    def test_only_reconnecting_and_inactive_presence_counts_as_disconnected(self):
        self.assertTrue(is_disconnected_presence('reconnecting'))
        self.assertTrue(is_disconnected_presence('inactive'))
        self.assertFalse(is_disconnected_presence('offline'))


class ReadinessDomainTests(SimpleTestCase):
    def test_change_distinguishes_requested_value_from_state_transition(self):
        self.assertEqual(readiness_change(False, True).value, True)
        self.assertTrue(readiness_change(False, True).changed)
        self.assertFalse(readiness_change(True, True).changed)


class EventSnapshotContractTests(TestCase):
    def test_event_snapshot_matches_rest_room_contract_without_using_its_serializer(self):
        room = Room.objects.create(game_id='duelo')
        caller = Participant.objects.create(
            room=room,
            display_name='Guest One',
            game_marker='guante-rojo',
            presence=Participant.Presence.ONLINE,
        )
        target = Participant.objects.create(
            room=room,
            display_name='Guest Two',
            game_marker='guante-azul',
            presence=Participant.Presence.INACTIVE,
        )
        vote = ExpulsionVote.objects.create(
            room=room,
            target=target,
            initiated_by=caller,
        )
        ExpulsionBallot.objects.create(vote=vote, voter=caller)

        self.assertEqual(room_snapshot(room), dict(RoomSerializer(room).data))
