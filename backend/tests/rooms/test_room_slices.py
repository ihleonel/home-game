from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone, translation

from modules.rooms.constants import RECONNECT_GRACE_SECONDS
from modules.rooms.events import room_snapshot
from modules.rooms.features.membership.domain.rules import (
    is_disconnected_presence,
    membership_change,
    resolve_entry_role,
)
from modules.rooms.features.presence.domain.rules import (
    grace_expired,
    remaining_seconds,
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


class EntryRoleDomainTests(SimpleTestCase):
    def test_explicit_spectator_wins_over_a_free_seat(self):
        self.assertEqual(
            resolve_entry_role(
                as_spectator=True,
                match_in_progress=False,
                active_players=0,
                max_seats=2,
            ),
            'spectator',
        )

    def test_match_in_progress_wins_over_a_free_seat(self):
        self.assertEqual(
            resolve_entry_role(
                as_spectator=False,
                match_in_progress=True,
                active_players=0,
                max_seats=2,
            ),
            'spectator',
        )

    def test_full_room_without_a_match_is_a_spectator(self):
        self.assertEqual(
            resolve_entry_role(
                as_spectator=False,
                match_in_progress=False,
                active_players=2,
                max_seats=2,
            ),
            'spectator',
        )

    def test_free_seat_without_a_match_is_a_player(self):
        self.assertEqual(
            resolve_entry_role(
                as_spectator=False,
                match_in_progress=False,
                active_players=1,
                max_seats=2,
            ),
            'player',
        )


class ReadinessDomainTests(SimpleTestCase):
    def test_change_distinguishes_requested_value_from_state_transition(self):
        self.assertEqual(readiness_change(False, True).value, True)
        self.assertTrue(readiness_change(False, True).changed)
        self.assertFalse(readiness_change(True, True).changed)


class PresenceDomainTests(SimpleTestCase):
    NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime_timezone.utc)

    def test_remaining_seconds_reports_the_whole_seconds_left_in_the_window(self):
        self.assertEqual(
            remaining_seconds(self.NOW - timedelta(seconds=20), self.NOW, 60),
            40,
        )
        self.assertEqual(
            remaining_seconds(self.NOW - timedelta(seconds=59), self.NOW, 60),
            1,
        )

    def test_remaining_seconds_never_promises_a_closed_window(self):
        # Exactly at the deadline the window is already closed: the same
        # comparison that reports the seat as inactive reports no time left.
        deadline = self.NOW - timedelta(seconds=60)
        self.assertTrue(grace_expired(deadline, self.NOW, 60))
        self.assertIsNone(remaining_seconds(deadline, self.NOW, 60))
        self.assertIsNone(
            remaining_seconds(self.NOW - timedelta(seconds=61), self.NOW, 60)
        )

    def test_remaining_seconds_floors_below_one_second_to_zero(self):
        self.assertEqual(
            remaining_seconds(
                self.NOW - timedelta(seconds=59, milliseconds=500),
                self.NOW,
                60,
            ),
            0,
        )

    def test_remaining_seconds_without_a_disconnect_time_has_nothing_to_measure(self):
        self.assertIsNone(remaining_seconds(None, self.NOW, 60))


class EventSnapshotContractTests(TestCase):
    def test_event_snapshot_matches_rest_room_contract_without_using_its_serializer(self):
        # One clock for the whole test: the disconnect instant is measured from
        # it and both readers are pinned to it below.
        read_at = timezone.now()
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
        counting = Participant.objects.create(
            room=room,
            display_name='Guest Three',
            game_marker='guante-azul',
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=read_at - timedelta(seconds=20),
        )
        Participant.objects.create(
            room=room,
            display_name='Guest Four',
            game_marker='guante-verde',
            role=Participant.Role.SPECTATOR,
        )
        vote = ExpulsionVote.objects.create(
            room=room,
            target=target,
            initiated_by=caller,
        )
        ExpulsionBallot.objects.create(vote=vote, voter=caller)

        # Both readers are held to one clock: the countdown is the same field
        # on both sides of the contract, and a reconnecting participant is
        # exactly the case where a drifting clock would show up.
        with patch('django.utils.timezone.now', return_value=read_at):
            snapshot = room_snapshot(room)
            serialized = dict(RoomSerializer(room).data)

        self.assertEqual(snapshot, serialized)
        self.assertEqual(
            {entry['role'] for entry in snapshot['participants']},
            {'player', 'spectator'},
        )
        counting_entry = next(
            entry
            for entry in snapshot['participants']
            if entry['display_name'] == counting.display_name
        )
        self.assertEqual(counting_entry['presence'], 'reconnecting')
        self.assertEqual(
            counting_entry['remaining_seconds'],
            RECONNECT_GRACE_SECONDS - 20,
        )
