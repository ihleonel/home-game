"""Integration coverage for ghost reaping against real rows.

Exercises the composed ``RoomDependencies.reaping`` entry point and, for the
gateway-specific contract, ``DjangoRoomReapingGateway`` directly. Events go
through the shared ``schedule_room_event`` helper, so the broadcasts are
captured on commit exactly as the REST and websocket adapters see them.
"""

import re
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from modules.games.models import Match
from modules.rooms.constants import RECONNECT_GRACE_SECONDS
from modules.rooms.connections import register_connection, unregister_connection
from modules.rooms.features.reaping.domain.entities import ReapOutcome
from modules.rooms.features.reaping.domain.rules import GRACE, STARTUP, staleness_cutoff
from modules.rooms.features.reaping.infrastructure.django_gateway import (
    DjangoRoomReapingGateway,
)
from modules.rooms.interfaces.composition import compose_room_dependencies
from modules.rooms.models import ExpulsionVote, ExpulsionVoteTarget, Participant, Room

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


def fresh_moment(now=None):
    now = now or timezone.now()
    return now - timedelta(seconds=RECONNECT_GRACE_SECONDS - 5)


def age_participant(participant, *, updated_at):
    """Backdate the auto-managed ``updated_at`` of a real row."""
    Participant.objects.filter(pk=participant.pk).update(updated_at=updated_at)
    participant.refresh_from_db()
    return participant


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

    def test_never_socketed_offline_participant_is_reaped_and_room_deleted(self):
        # A membership created over REST whose socket never opens stays at
        # presence='offline' with disconnected_at=NULL. It must age out on the
        # same grace window, counted from updated_at, or it holds the room open
        # forever.
        room = create_room()
        never_socketed = age_participant(
            create_participant(room, presence=Participant.Presence.OFFLINE),
            updated_at=stale_moment(),
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(1, 1, 1))
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertFalse(
            Participant.objects.filter(pk=never_socketed.pk).exists()
        )
        broadcast.assert_called_once()

    def test_fresh_offline_participant_is_kept_for_the_grace_window(self):
        # The fresh-arrival and revived-membership case: a row that just joined
        # or just came back over REST still has to be able to open its socket.
        room = create_room()
        fresh = create_participant(room, presence=Participant.Presence.OFFLINE)
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        fresh.refresh_from_db()
        self.assertIsNone(fresh.left_at)
        self.assertEqual(fresh.presence, Participant.Presence.OFFLINE)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        broadcast.assert_not_called()

    def test_online_participant_is_never_reaped_under_the_grace_policy(self):
        # An online row belongs to a live socket; even a stale updated_at must
        # not reap it on the hot paths.
        room = create_room()
        online = age_participant(
            create_participant(room, presence=Participant.Presence.ONLINE),
            updated_at=stale_moment(),
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        online.refresh_from_db()
        self.assertIsNone(online.left_at)
        self.assertEqual(online.presence, Participant.Presence.ONLINE)
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

    def test_startup_reaps_an_online_row_that_grace_keeps(self):
        room = create_room()
        online = create_participant(room, presence=Participant.Presence.ONLINE)
        create_participant(
            room,
            presence=Participant.Presence.OFFLINE,
            display_name='Fresh',
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                grace = dependencies.reaping.reap(room_id=room.pk)
        self.assertEqual(grace, ReapOutcome(0, 0, 0))
        online.refresh_from_db()
        self.assertIsNone(online.left_at)

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                startup = dependencies.reaping.reap(
                    room_id=room.pk, policy=STARTUP
                )
        self.assertEqual(startup, ReapOutcome(1, 2, 1))
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertEqual(broadcast.call_count, 2)

    def test_room_with_in_progress_match_is_skipped_under_both_policies(self):
        room = create_room()
        ghost = create_participant(room, presence=Participant.Presence.ONLINE)
        match = Match.objects.create(
            room=room,
            game_id='duelo',
            status=Match.Status.IN_PROGRESS,
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH) as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                grace = dependencies.reaping.reap(room_id=room.pk)
                startup = dependencies.reaping.reap(
                    room_id=room.pk, policy=STARTUP
                )

        self.assertEqual(grace, ReapOutcome(0, 0, 0))
        self.assertEqual(startup, ReapOutcome(0, 0, 0))
        ghost.refresh_from_db()
        self.assertIsNone(ghost.left_at)
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

    def test_pending_vote_target_is_left_alone_by_the_sweep(self):
        # The sweep owns this state now (S3): a target already covered by a
        # pending vote is not reaped out from under it.
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
            initiated_by=initiator,
        )
        ExpulsionVoteTarget.objects.create(vote=vote, participant=ghost)
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                dependencies.reaping.reap(room_id=room.pk)

        vote.refresh_from_db()
        self.assertEqual(vote.status, ExpulsionVote.Status.PENDING)
        ghost.refresh_from_db()
        self.assertIsNone(ghost.left_at)
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
                [room.pk], policy=GRACE, cutoff=cutoff
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

    def test_grace_filter_reaps_offline_past_cutoff_and_spares_fresh_offline(self):
        room = create_room()
        now = timezone.now()
        cutoff = staleness_cutoff(now, RECONNECT_GRACE_SECONDS)
        old = now - timedelta(seconds=RECONNECT_GRACE_SECONDS + 30)
        fresh = now - timedelta(seconds=RECONNECT_GRACE_SECONDS - 5)
        stale_offline = age_participant(
            create_participant(room, presence=Participant.Presence.OFFLINE),
            updated_at=old,
        )
        fresh_offline = age_participant(
            create_participant(room, presence=Participant.Presence.OFFLINE),
            updated_at=fresh,
        )
        # A live socket is never touched, however old its row looks.
        online = age_participant(
            create_participant(room, presence=Participant.Presence.ONLINE),
            updated_at=old,
        )

        gateway = DjangoRoomReapingGateway()

        with CaptureQueriesContext(connection) as queries:
            reapable = gateway.reapable_participants_for_update(
                [room.pk], policy=GRACE, cutoff=cutoff
            )

        self.assertEqual(
            {participant.id for participant in reapable}, {stale_offline.pk}
        )
        self.assertNotIn(fresh_offline.pk, {p.id for p in reapable})
        self.assertNotIn(online.pk, {p.id for p in reapable})
        self.assertEqual(reapable[0].updated_at, old)

        sql = ' '.join(query['sql'].lower() for query in queries.captured_queries)
        self.assertRegex(sql, r'updated_at"?\s*<=')
        self.assertRegex(sql, r'disconnected_at"?\s*<=')

    def test_startup_filter_is_presence_agnostic_and_excludes_left_rows(self):
        room = create_room()
        now = timezone.now()
        cutoff = staleness_cutoff(now, RECONNECT_GRACE_SECONDS)
        online = create_participant(room, presence=Participant.Presence.ONLINE)
        offline = create_participant(room, presence=Participant.Presence.OFFLINE)
        reconnecting = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=now - timedelta(seconds=5),
        )
        create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=now,
            left_at=now,
        )
        gateway = DjangoRoomReapingGateway()

        with CaptureQueriesContext(connection) as queries:
            reapable = gateway.reapable_participants_for_update(
                [room.pk], policy=STARTUP, cutoff=cutoff
            )

        self.assertEqual(
            {participant.id for participant in reapable},
            {online.pk, offline.pk, reconnecting.pk},
        )
        sql = ' '.join(query['sql'].lower() for query in queries.captured_queries)
        self.assertIsNone(re.search(r'presence"?\s+in', sql))
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


class SweepVotingIntegrationTests(TestCase):
    """The composed ``reap()`` now votes, not only reaps (S3, S4).

    The connected electorate comes from the in-process connection registry, so
    these tests register real-format connections exactly as the socket path
    does.
    """

    def setUp(self):
        self.connections = []

    def tearDown(self):
        for room_id, session_id, channel_name in self.connections:
            unregister_connection(room_id, session_id, channel_name)

    def connect(self, participant):
        channel_name = f'sweep-{participant.public_id}'
        session_id = str(participant.session_id)
        register_connection(participant.room_id, session_id, channel_name)
        self.connections.append(
            (participant.room_id, session_id, channel_name)
        )
        return participant

    def test_two_absences_with_one_connected_voter_are_reaped_not_voted(self):
        room = create_room()
        first = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Ghost One',
        )
        second = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Ghost Two',
        )
        voter = self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter'
            )
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(1, 2, 0))
        self.assertFalse(ExpulsionVote.objects.exists())
        for ghost in (first, second):
            ghost.refresh_from_db()
            self.assertIsNotNone(ghost.left_at)
        voter.refresh_from_db()
        self.assertIsNone(voter.left_at)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())

    def test_two_absences_with_two_connected_voters_open_one_automatic_batch(self):
        room = create_room()
        first = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Ghost One',
        )
        second = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Ghost Two',
        )
        first_voter = self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter One'
            )
        )
        second_voter = self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter Two'
            )
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        vote = ExpulsionVote.objects.get()
        self.assertEqual(vote.status, ExpulsionVote.Status.PENDING)
        self.assertEqual(vote.origin, ExpulsionVote.Origin.AUTOMATIC)
        self.assertIsNone(vote.initiated_by_id)
        self.assertEqual(
            set(vote.targets.values_list('participant_id', flat=True)),
            {first.pk, second.pk},
        )
        self.assertEqual(
            set(vote.ballots.values_list('voter_id', flat=True)),
            {first_voter.pk, second_voter.pk},
        )
        for ghost in (first, second):
            ghost.refresh_from_db()
            self.assertIsNone(ghost.left_at)

    def test_a_second_absence_while_a_vote_is_pending_does_not_break_the_constraint(self):
        room = create_room()
        covered = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Covered',
        )
        newcomer = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Newcomer',
        )
        self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter One'
            )
        )
        self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter Two'
            )
        )
        vote = compose_room_dependencies().expulsion_voting.create_vote(
            room.pk, (covered.pk,), origin='automatic'
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        self.assertEqual(ExpulsionVote.objects.count(), 1)
        stored = ExpulsionVote.objects.get(pk=vote.id)
        self.assertEqual(stored.status, ExpulsionVote.Status.PENDING)
        for ghost in (covered, newcomer):
            ghost.refresh_from_db()
            self.assertIsNone(ghost.left_at)

    def test_a_rejected_vote_spends_the_absence_and_the_sweep_reaps_the_target(self):
        # Real gateway coverage for ``absence_is_spent_for_update`` (S2): a
        # rejected vote that started after the absence covers it, so the sweep
        # reaps the target instead of voting again.
        room = create_room()
        target = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Target',
        )
        self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter One'
            )
        )
        self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter Two'
            )
        )
        rejected = ExpulsionVote.objects.create(
            room=room,
            status=ExpulsionVote.Status.REJECTED,
            resolution_reason='voter_rejected',
        )
        ExpulsionVoteTarget.objects.create(vote=rejected, participant=target)
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(1, 1, 0))
        target.refresh_from_db()
        self.assertIsNotNone(target.left_at)
        self.assertFalse(
            ExpulsionVote.objects.filter(
                status=ExpulsionVote.Status.PENDING
            ).exists()
        )

    def test_a_cancelled_vote_does_not_spend_the_absence_and_the_room_votes_again(self):
        # Real gateway coverage for the other half of the rule: a cancelled vote
        # never spends the absence, so with the quorum connected the sweep opens
        # a fresh automatic vote instead of reaping.
        room = create_room()
        target = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Target',
        )
        self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter One'
            )
        )
        self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter Two'
            )
        )
        cancelled = ExpulsionVote.objects.create(
            room=room,
            status=ExpulsionVote.Status.CANCELLED,
            resolution_reason='target_reconnected',
        )
        ExpulsionVoteTarget.objects.create(vote=cancelled, participant=target)
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        target.refresh_from_db()
        self.assertIsNone(target.left_at)
        fresh = ExpulsionVote.objects.get(status=ExpulsionVote.Status.PENDING)
        self.assertEqual(fresh.origin, ExpulsionVote.Origin.AUTOMATIC)
        self.assertEqual(
            list(fresh.targets.values_list('participant_id', flat=True)),
            [target.pk],
        )

    def test_zero_connected_voters_with_only_absences_deletes_the_room(self):
        room = create_room()
        create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
        )
        create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Second',
        )
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(1, 2, 1))
        self.assertFalse(ExpulsionVote.objects.exists())
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())

    def test_a_pending_vote_target_survives_the_next_sweep(self):
        # The measured ``target_left`` regression: the sweep owns the state, so
        # a target already covered by a pending vote is left alone instead of
        # being reaped out from under the vote.
        room = create_room()
        ghost = create_participant(
            room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Ghost',
        )
        voter = self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter'
            )
        )
        second_voter = self.connect(
            create_participant(
                room, presence=Participant.Presence.ONLINE, display_name='Voter Two'
            )
        )
        gateway = compose_room_dependencies().expulsion_voting
        vote = gateway.create_vote(room.pk, (ghost.pk,), origin='automatic')
        dependencies = compose_room_dependencies()

        with patch(BROADCAST_PATH):
            with self.captureOnCommitCallbacks(execute=True):
                outcome = dependencies.reaping.reap(room_id=room.pk)

        self.assertEqual(outcome, ReapOutcome(0, 0, 0))
        ghost.refresh_from_db()
        self.assertIsNone(ghost.left_at)
        stored = ExpulsionVote.objects.get(pk=vote.id)
        self.assertEqual(stored.status, ExpulsionVote.Status.PENDING)
        self.assertIsNone(voter.left_at)
        self.assertIsNone(second_voter.left_at)
