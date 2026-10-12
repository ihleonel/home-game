"""Integration coverage for ghost reaping against real rows.

Exercises the composed ``RoomDependencies.reaping`` entry point and, for the
gateway-specific contract, ``DjangoRoomReapingGateway`` directly. Events go
through the shared ``schedule_room_event`` helper, so the broadcasts are
captured on commit exactly as the REST and websocket adapters see them.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from modules.games.models import Match
from modules.rooms.constants import RECONNECT_GRACE_SECONDS
from modules.rooms.features.reaping.domain.entities import ReapOutcome
from modules.rooms.features.reaping.domain.rules import staleness_cutoff
from modules.rooms.features.reaping.infrastructure.django_gateway import (
    DjangoRoomReapingGateway,
)
from modules.rooms.interfaces.composition import compose_room_dependencies
from modules.rooms.models import ExpulsionVote, Participant, Room

BROADCAST_PATH = 'modules.rooms.infrastructure.events.broadcast_room_event'


def create_room(game_id='duelo'):
    return Room.objects.create(game_id=game_id)


def create_participant(
    room,
    *,
    presence=Participant.Presence.OFFLINE,
    disconnected_at=None,
    is_ready=False,
    left_at=None,
    display_name='Guest',
    game_marker='guante-rojo',
    session_id=None,
):
    return Participant.objects.create(
        room=room,
        session_id=session_id or uuid.uuid4(),
        display_name=display_name,
        game_marker=game_marker,
        presence=presence,
        disconnected_at=disconnected_at,
        is_ready=is_ready,
        left_at=left_at,
    )


def stale_moment(now=None):
    now = now or timezone.now()
    return now - timedelta(seconds=RECONNECT_GRACE_SECONDS + 30)


class ReapingIntegrationTests(TestCase):
    def test_stale_only_participant_is_reaped_and_emptied_room_is_deleted(self):
        room = create_room()
        stale = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=stale_moment(),
            is_ready=True,
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(1, 1, 1))
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertFalse(Participant.objects.filter(pk=stale.pk).exists())

        self.assertEqual(broadcast.call_count, 1)
        room_id, event_name, snapshot, departed_session_id, vote = (
            broadcast.call_args.args
        )
        self.assertEqual(room_id, room.pk)
        self.assertEqual(event_name, 'player_left')
        self.assertEqual(snapshot['game_id'], 'duelo')
        self.assertEqual(departed_session_id, stale.session_id)
        self.assertIsInstance(departed_session_id, uuid.UUID)
        self.assertIsNone(vote)

    def test_reaped_membership_is_left_offline_and_not_ready(self):
        room = create_room()
        ghost = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=stale_moment(),
            is_ready=True,
        )
        companion = create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            display_name='Companion',
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(1, 1, 0))
        ghost.refresh_from_db()
        self.assertIsNotNone(ghost.left_at)
        self.assertEqual(ghost.presence, Participant.Presence.OFFLINE)
        self.assertIsNone(ghost.disconnected_at)
        self.assertFalse(ghost.is_ready)

        companion.refresh_from_db()
        self.assertIsNone(companion.left_at)
        self.assertEqual(companion.presence, Participant.Presence.ONLINE)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())

    def test_participant_inside_the_grace_window_is_untouched(self):
        room = create_room()
        now = timezone.now()
        participant = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=now - timedelta(seconds=RECONNECT_GRACE_SECONDS - 5),
            is_ready=True,
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        participant.refresh_from_db()
        self.assertIsNone(participant.left_at)
        self.assertEqual(participant.presence, Participant.Presence.RECONNECTING)
        self.assertTrue(participant.is_ready)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        broadcast.assert_not_called()

    def test_room_with_in_progress_match_keeps_its_stale_participant(self):
        room = create_room()
        ghost = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
        )
        match = Match.objects.create(
            room=room,
            game_id='duelo',
            status=Match.Status.IN_PROGRESS,
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        ghost.refresh_from_db()
        self.assertIsNone(ghost.left_at)
        self.assertEqual(ghost.presence, Participant.Presence.INACTIVE)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        self.assertTrue(Match.objects.filter(pk=match.pk).exists())
        broadcast.assert_not_called()

    def test_second_run_over_the_same_state_reaps_nothing(self):
        room = create_room()
        ghost = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=stale_moment(),
        )
        create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            display_name='Companion',
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                first = dependencies.reaping.reap(room_id=room.pk)
                second = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(first, ReapOutcome(1, 1, 0))
        self.assertEqual(second, ReapOutcome(0, 0, 0))
        self.assertEqual(broadcast.call_count, 1)
        ghost.refresh_from_db()
        self.assertIsNotNone(ghost.left_at)

    def test_pending_expulsion_vote_involving_the_reaped_participant_is_cancelled(
        self,
    ):
        room = create_room()
        ghost = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Ghost',
        )
        initiator = create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            display_name='Host',
        )
        vote = ExpulsionVote.objects.create(
            room=room,
            target=ghost,
            initiated_by=initiator,
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                dependencies.reaping.reap(room_id=room.pk)

        vote.refresh_from_db()
        self.assertEqual(vote.status, ExpulsionVote.Status.CANCELLED)
        self.assertTrue(vote.resolution_reason)
        self.assertIsNotNone(vote.resolved_at)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())


class DjangoRoomReapingGatewayTests(TestCase):
    def test_cutoff_is_filtered_in_sql_and_session_id_passes_through(self):
        room = create_room()
        now = timezone.now()
        old = now - timedelta(seconds=RECONNECT_GRACE_SECONDS + 30)
        stale_reconnecting = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=old,
        )
        stale_inactive = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=old,
        )
        create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=now - timedelta(seconds=RECONNECT_GRACE_SECONDS - 5),
        )
        create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            disconnected_at=old,
        )
        create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=None,
        )
        create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=old,
            left_at=now,
        )

        gateway = DjangoRoomReapingGateway()
        cutoff = staleness_cutoff(now, RECONNECT_GRACE_SECONDS)

        with CaptureQueriesContext(connection) as queries:
            reapable = gateway.reapable_participants_for_update(
                [room.pk], cutoff=cutoff
            )

        expected_ids = {stale_reconnecting.pk, stale_inactive.pk}
        self.assertEqual({participant.id for participant in reapable}, expected_ids)
        self.assertEqual(
            [participant.id for participant in reapable], sorted(expected_ids)
        )

        by_id = {
            stale_reconnecting.pk: stale_reconnecting,
            stale_inactive.pk: stale_inactive,
        }
        for participant in reapable:
            self.assertIsInstance(participant.session_id, uuid.UUID)
            self.assertEqual(
                participant.session_id, by_id[participant.id].session_id
            )

        sql = ' '.join(query['sql'].lower() for query in queries.captured_queries)
        self.assertRegex(sql, r'disconnected_at"?\s*<=')
        self.assertRegex(sql, r'presence"?\s+in')
        self.assertRegex(sql, r'left_at"?\s+is\s+null')

    def test_active_room_ids_scopes_to_a_single_room_in_primary_key_order(self):
        first = create_room('duelo')
        second = create_room('otro-juego')
        third = create_room('tercer-juego')
        gateway = DjangoRoomReapingGateway()

        self.assertEqual(
            gateway.active_room_ids(), (first.pk, second.pk, third.pk)
        )
        self.assertEqual(gateway.active_room_ids(room_id=second.pk), (second.pk,))
