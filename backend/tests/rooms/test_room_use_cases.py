from collections import deque
from unittest.mock import Mock
from uuid import uuid4

from django.test import SimpleTestCase

from modules.rooms.features.membership.application.ports import RoomMembershipPorts
from modules.rooms.features.membership.application.use_cases import (
    create_or_discover_room,
    join_room,
    leave_room,
)
from modules.rooms.features.membership.domain.entities import (
    ActiveRoom,
    ParticipantMembership,
)
from modules.rooms.features.membership.domain.errors import (
    ActiveRoomGameConflict,
    MissingParticipantIdentity,
    ReadyParticipantCannotLeave,
)
from modules.rooms.features.readiness.application.ports import ReadinessPorts
from modules.rooms.features.readiness.application.use_cases import set_ready_state
from modules.rooms.features.readiness.domain.entities import ReadinessParticipant
from modules.rooms.features.readiness.domain.errors import (
    ActiveRoomNotFound,
    SpectatorCannotBeReady,
)
from tests.games.support import SCOPING_GAME_ID

from .support import ports_fake


class MembershipUseCaseTests(SimpleTestCase):
    def test_create_or_discover_sequences_creation_snapshot_and_event(self):
        participant = _participant()
        vote_cancellation = Mock()
        reaping = Mock()
        # A first join has no pending expulsion vote, so the use case must not
        # publish a cancellation event. Leaving the default Mock return value in
        # place would make it publish one and consume an extra snapshot.
        vote_cancellation.target_reconnected.return_value = None
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'duelo'), True),
            participant_for_session_for_update=None,
            has_in_progress_match=False,
            count_active_players=0,
            game_max_seats=2,
            create_participant=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )

        response, created = create_or_discover_room(
            ports, _new_member_data(), vote_cancellation, reaping
        )

        self.assertTrue(created)
        self.assertEqual(response, {
            'room': {'revision': 1},
            'session_id': str(participant.session_id),
            'participant_ref': str(participant.public_id),
        })
        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'create_or_lock_active_room',
                'participant_for_session_for_update',
                'has_in_progress_match',
                'count_active_players',
                'game_max_seats',
                'create_participant',
                'room_snapshot',
                'room_snapshot',
                'schedule_room_event',
                'commit',
            ],
        )
        ports.create_participant.assert_called_once_with(
            12, 'Guest One', 'guante-rojo', 'player'
        )
        ports.schedule_room_event.assert_called_once_with(
            12, 'player_joined', {'revision': 2}
        )
        vote_cancellation.target_reconnected.assert_called_once_with(
            12, participant.id
        )

    def test_new_participant_in_a_full_room_resolves_to_spectator(self):
        participant = _participant()
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'duelo'), True),
            participant_for_session_for_update=None,
            has_in_progress_match=False,
            count_active_players=2,
            game_max_seats=2,
            create_participant=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )
        vote_cancellation = Mock()
        vote_cancellation.target_reconnected.return_value = None

        create_or_discover_room(
            ports, _new_member_data(), vote_cancellation, Mock()
        )

        ports.create_participant.assert_called_once_with(
            12, 'Guest One', 'guante-rojo', 'spectator'
        )
        ports.schedule_room_event.assert_called_once_with(
            12, 'spectator_joined', {'revision': 2}
        )

    def test_match_in_progress_resolves_to_spectator_even_with_a_free_seat(self):
        participant = _participant()
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'duelo'), True),
            participant_for_session_for_update=None,
            has_in_progress_match=True,
            count_active_players=0,
            game_max_seats=2,
            create_participant=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )
        vote_cancellation = Mock()
        vote_cancellation.target_reconnected.return_value = None

        create_or_discover_room(
            ports, _new_member_data(), vote_cancellation, Mock()
        )

        ports.create_participant.assert_called_once_with(
            12, 'Guest One', 'guante-rojo', 'spectator'
        )
        ports.schedule_room_event.assert_called_once_with(
            12, 'spectator_joined', {'revision': 2}
        )

    def test_explicit_spectator_resolves_to_spectator_with_a_free_seat(self):
        participant = _participant()
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'duelo'), True),
            participant_for_session_for_update=None,
            has_in_progress_match=False,
            count_active_players=0,
            game_max_seats=2,
            create_participant=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )
        vote_cancellation = Mock()
        vote_cancellation.target_reconnected.return_value = None
        data = {**_new_member_data(), 'as_spectator': True}

        create_or_discover_room(ports, data, vote_cancellation, Mock())

        ports.create_participant.assert_called_once_with(
            12, 'Guest One', 'guante-rojo', 'spectator'
        )
        ports.schedule_room_event.assert_called_once_with(
            12, 'spectator_joined', {'revision': 2}
        )

    def test_free_seat_without_a_match_resolves_to_player(self):
        participant = _participant()
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'duelo'), True),
            participant_for_session_for_update=None,
            has_in_progress_match=False,
            count_active_players=1,
            game_max_seats=2,
            create_participant=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )
        vote_cancellation = Mock()
        vote_cancellation.target_reconnected.return_value = None

        create_or_discover_room(
            ports, _new_member_data(), vote_cancellation, Mock()
        )

        ports.create_participant.assert_called_once_with(
            12, 'Guest One', 'guante-rojo', 'player'
        )
        ports.schedule_room_event.assert_called_once_with(
            12, 'player_joined', {'revision': 2}
        )

    def test_existing_session_keeps_its_role_and_skips_entry_resolution(self):
        participant = _participant()
        ports = _ports(
            active_room_for_update=ActiveRoom(12, 'duelo'),
            participant_for_session_for_update=participant,
            save_membership_changes=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )
        vote_cancellation = Mock()
        vote_cancellation.session_was_removed.return_value = False
        vote_cancellation.target_reconnected.return_value = None
        data = {
            'game_id': 'duelo',
            'session_id': participant.session_id,
            'display_name': 'Guest One',
            'as_spectator': True,
        }

        join_room(ports, data, vote_cancellation, Mock())

        ports.create_participant.assert_not_called()
        ports.has_in_progress_match.assert_not_called()
        ports.count_active_players.assert_not_called()
        ports.game_max_seats.assert_not_called()

    def test_game_conflict_is_decided_before_membership_or_vote_work(self):
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, SCOPING_GAME_ID), False)
        )
        vote_cancellation = Mock()
        reaping = Mock()

        with self.assertRaises(ActiveRoomGameConflict):
            create_or_discover_room(
                ports, _new_member_data(), vote_cancellation, reaping
            )

        self.assertEqual(
            ports.timeline,
            ['begin', 'create_or_lock_active_room', 'rollback'],
        )

    def test_identity_requirement_is_checked_before_new_participant_persistence(self):
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'duelo'), True),
            participant_for_session_for_update=None,
        )
        vote_cancellation = Mock()
        reaping = Mock()

        with self.assertRaises(MissingParticipantIdentity) as error:
            create_or_discover_room(
                ports, {'game_id': 'duelo'}, vote_cancellation, reaping
            )

        self.assertEqual(set(error.exception.fields), {'display_name', 'game_marker'})
        ports.create_participant.assert_not_called()
        self.assertEqual(ports.timeline[-1], 'rollback')

    def test_rejoin_applies_domain_changes_and_keeps_vote_cancellation_events(self):
        participant = _participant(presence='reconnecting')
        ports = _ports(
            active_room_for_update=ActiveRoom(12, 'duelo'),
            participant_for_session_for_update=participant,
            save_membership_changes=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2}, {'revision': 3})),
        )
        vote_cancellation = Mock()
        vote_cancellation.session_was_removed.return_value = False
        vote_cancellation.target_reconnected.return_value = {'status': 'cancelled'}
        reaping = Mock()
        data = {
            'game_id': 'duelo',
            'session_id': participant.session_id,
            'display_name': 'Guest Updated',
        }

        response = join_room(ports, data, vote_cancellation, reaping)

        self.assertEqual(response['session_id'], str(participant.session_id))
        vote_cancellation.target_reconnected.assert_called_once_with(
            12, participant.id
        )
        ports.save_membership_changes.assert_called_once_with(
            participant.id,
            {
                'display_name': 'Guest Updated',
                'presence': 'offline',
                'disconnected_at': None,
            },
        )
        self.assertEqual(
            [call.args[1] for call in ports.schedule_room_event.call_args_list],
            ['player_joined', 'expulsion_vote_cancelled'],
        )
        self.assertEqual(
            ports.schedule_room_event.call_args_list[1].kwargs['vote'],
            {'status': 'cancelled'},
        )

    def test_ready_participant_cannot_leave_before_any_membership_or_event_work(self):
        participant = _participant(is_ready=True)
        ports = _ports(
            active_room_for_update=ActiveRoom(12, 'duelo'),
            active_participant_for_session_for_update=participant,
        )
        vote_cancellation = Mock()

        with self.assertRaises(ReadyParticipantCannotLeave):
            leave_room(
                ports, {'session_id': participant.session_id}, vote_cancellation
            )

        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'active_room_for_update',
                'active_participant_for_session_for_update',
                'rollback',
            ],
        )
        ports.save_membership_changes.assert_not_called()
        vote_cancellation.participant_left.assert_not_called()
        ports.room_snapshot.assert_not_called()
        ports.schedule_room_event.assert_not_called()

    def test_leave_sequences_state_change_vote_hooks_cleanup_and_events(self):
        participant = _participant()
        ports = _ports(
            active_room_for_update=ActiveRoom(12, 'duelo'),
            active_participant_for_session_for_update=participant,
            save_membership_changes=participant,
            room_snapshot={'room': 'snapshot'},
            has_active_participants=False,
            now='leave-time',
        )
        vote_cancellation = Mock()
        vote_cancellation.participant_left.return_value = {'status': 'cancelled'}

        leave_room(ports, {'session_id': participant.session_id}, vote_cancellation)

        ports.save_membership_changes.assert_called_once_with(
            participant.id,
            {
                'left_at': 'leave-time',
                'presence': 'offline',
                'disconnected_at': None,
            },
        )
        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'active_room_for_update',
                'active_participant_for_session_for_update',
                'now',
                'save_membership_changes',
                'room_snapshot',
                'has_active_participants',
                'delete_room',
                'schedule_room_event',
                'schedule_room_event',
                'commit',
            ],
        )
        vote_cancellation.participant_left.assert_called_once_with(
            12, participant.id
        )

    def test_create_reaps_before_locking_or_creating_the_room(self):
        participant = _participant()
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'duelo'), True),
            participant_for_session_for_update=None,
            create_participant=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )
        vote_cancellation = Mock()
        vote_cancellation.target_reconnected.return_value = None
        reaping = _reaping(ports)

        create_or_discover_room(
            ports, _new_member_data(), vote_cancellation, reaping
        )

        reaping.reap.assert_called_once_with()
        self.assertEqual(ports.timeline[0], 'begin')
        self.assertLess(
            ports.timeline.index('reap'),
            ports.timeline.index('create_or_lock_active_room'),
        )
        self.assertLess(ports.timeline.index('reap'), ports.timeline.index('commit'))

    def test_join_reaps_before_resolving_the_room(self):
        participant = _participant()
        ports = _ports(
            active_room_for_update=ActiveRoom(12, 'duelo'),
            participant_for_session_for_update=participant,
            save_membership_changes=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )
        vote_cancellation = Mock()
        vote_cancellation.session_was_removed.return_value = False
        vote_cancellation.target_reconnected.return_value = None
        reaping = _reaping(ports)
        data = {
            'game_id': 'duelo',
            'session_id': participant.session_id,
            'display_name': 'Guest Updated',
        }

        join_room(ports, data, vote_cancellation, reaping)

        reaping.reap.assert_called_once_with()
        self.assertEqual(ports.timeline[0], 'begin')
        self.assertLess(
            ports.timeline.index('reap'),
            ports.timeline.index('active_room_for_update'),
        )
        self.assertLess(ports.timeline.index('reap'), ports.timeline.index('commit'))

    def test_join_without_a_room_returns_none_after_reaping(self):
        ports = _ports(active_room_for_update=None)
        vote_cancellation = Mock()
        reaping = _reaping(ports)

        result = join_room(
            ports, {'game_id': 'duelo'}, vote_cancellation, reaping
        )

        self.assertIsNone(result)
        reaping.reap.assert_called_once_with()
        self.assertEqual(
            ports.timeline,
            ['begin', 'reap', 'active_room_for_update', 'commit'],
        )


class ReadinessUseCaseTests(SimpleTestCase):
    def test_readiness_change_is_saved_and_published_inside_unit_of_work(self):
        participant = ReadinessParticipant(id=24, is_ready=False)
        ports = _ports(
            active_room_for_update=12,
            active_participant_for_session_for_update=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )

        response = set_ready_state(
            ports, {'session_id': uuid4(), 'is_ready': True}
        )

        self.assertEqual(response, {'room': {'revision': 1}})
        ports.save_readiness.assert_called_once_with(participant.id, True)
        ports.schedule_room_event.assert_called_once_with(
            12, 'ready_changed', {'revision': 2}
        )
        self.assertEqual(
            ports.timeline,
            [
                'begin',
                'active_room_for_update',
                'active_participant_for_session_for_update',
                'save_readiness',
                'room_snapshot',
                'room_snapshot',
                'schedule_room_event',
                'commit',
            ],
        )

    def test_noop_readiness_still_persists_and_publishes(self):
        participant = ReadinessParticipant(id=24, is_ready=True)
        ports = _ports(
            active_room_for_update=12,
            active_participant_for_session_for_update=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )

        set_ready_state(ports, {'session_id': uuid4(), 'is_ready': True})

        ports.save_readiness.assert_called_once_with(participant.id, True)
        ports.schedule_room_event.assert_called_once()

    def test_missing_room_is_decided_by_the_use_case(self):
        ports = _ports(active_room_for_update=None)

        with self.assertRaises(ActiveRoomNotFound):
            set_ready_state(ports, {'session_id': uuid4(), 'is_ready': True})

        self.assertEqual(ports.timeline, ['begin', 'active_room_for_update', 'rollback'])
        ports.active_participant_for_session_for_update.assert_not_called()

    def test_a_spectator_cannot_be_marked_ready_whatever_the_requested_value(self):
        for requested in (True, False):
            with self.subTest(requested=requested):
                participant = ReadinessParticipant(
                    id=24, is_ready=False, role='spectator'
                )
                ports = _ports(
                    active_room_for_update=12,
                    active_participant_for_session_for_update=participant,
                )

                with self.assertRaises(SpectatorCannotBeReady):
                    set_ready_state(
                        ports, {'session_id': uuid4(), 'is_ready': requested}
                    )

                ports.save_readiness.assert_not_called()
                ports.schedule_room_event.assert_not_called()


def _ports(**results):
    return ports_fake(RoomMembershipPorts, ReadinessPorts, **results)


def _reaping(ports):
    """Reaping collaborator that leaves a marker in the ports timeline."""
    reaping = Mock()
    reaping.reap.side_effect = lambda **kwargs: ports.timeline.append('reap')
    return reaping


def _new_member_data():
    # The client posts its session id, so the use case looks the participant up
    # before falling through to creation; a visitor with no session id is a
    # different branch and is covered by its own identity-requirement test.
    return {
        'game_id': 'duelo',
        'session_id': uuid4(),
        'display_name': 'Guest One',
        'game_marker': 'guante-rojo',
    }


def _participant(presence='offline', is_ready=False):
    return ParticipantMembership(
        id=24,
        session_id=uuid4(),
        public_id=uuid4(),
        display_name='Guest One',
        game_marker='guante-rojo',
        presence=presence,
        was_left=False,
        is_ready=is_ready,
    )
