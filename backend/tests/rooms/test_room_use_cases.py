from collections import deque
from contextlib import contextmanager
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
)
from modules.rooms.features.readiness.application.ports import ReadinessPorts
from modules.rooms.features.readiness.application.use_cases import set_ready_state
from modules.rooms.features.readiness.domain.entities import ReadinessParticipant
from modules.rooms.features.readiness.domain.errors import ActiveRoomNotFound


class MembershipUseCaseTests(SimpleTestCase):
    def test_create_or_discover_sequences_creation_snapshot_and_event(self):
        participant = _participant()
        vote_cancellation = Mock()
        # A first join has no pending expulsion vote, so the use case must not
        # publish a cancellation event. Leaving the default Mock return value in
        # place would make it publish one and consume an extra snapshot.
        vote_cancellation.target_reconnected.return_value = None
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'starlight-garden'), True),
            participant_for_session_for_update=None,
            create_participant=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2})),
        )

        response, created = create_or_discover_room(
            ports, _new_member_data(), vote_cancellation
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
                'create_participant',
                'room_snapshot',
                'room_snapshot',
                'schedule_room_event',
                'commit',
            ],
        )
        ports.schedule_room_event.assert_called_once_with(
            12, 'player_joined', {'revision': 2}
        )
        vote_cancellation.target_reconnected.assert_called_once_with(
            12, participant.id
        )

    def test_game_conflict_is_decided_before_membership_or_vote_work(self):
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'cloud-couriers'), False)
        )
        vote_cancellation = Mock()

        with self.assertRaises(ActiveRoomGameConflict):
            create_or_discover_room(ports, _new_member_data(), vote_cancellation)

        self.assertEqual(
            ports.timeline,
            ['begin', 'create_or_lock_active_room', 'rollback'],
        )

    def test_identity_requirement_is_checked_before_new_participant_persistence(self):
        ports = _ports(
            create_or_lock_active_room=(ActiveRoom(12, 'starlight-garden'), True),
            participant_for_session_for_update=None,
        )
        vote_cancellation = Mock()

        with self.assertRaises(MissingParticipantIdentity) as error:
            create_or_discover_room(
                ports, {'game_id': 'starlight-garden'}, vote_cancellation
            )

        self.assertEqual(set(error.exception.fields), {'display_name', 'game_marker'})
        ports.create_participant.assert_not_called()
        self.assertEqual(ports.timeline[-1], 'rollback')

    def test_rejoin_applies_domain_changes_and_keeps_vote_cancellation_events(self):
        participant = _participant(presence='reconnecting')
        ports = _ports(
            active_room_for_update=ActiveRoom(12, 'starlight-garden'),
            participant_for_session_for_update=participant,
            session_was_removed=False,
            save_membership_changes=participant,
            room_snapshot=deque(({'revision': 1}, {'revision': 2}, {'revision': 3})),
        )
        vote_cancellation = Mock()
        vote_cancellation.session_was_removed.return_value = False
        vote_cancellation.target_reconnected.return_value = {'status': 'cancelled'}
        data = {
            'game_id': 'starlight-garden',
            'session_id': participant.session_id,
            'display_name': 'Guest Updated',
        }

        response = join_room(ports, data, vote_cancellation)

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

    def test_leave_sequences_state_change_vote_hooks_cleanup_and_events(self):
        participant = _participant()
        ports = _ports(
            active_room_for_update=ActiveRoom(12, 'starlight-garden'),
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


_UNSET = object()


def _declared_ports():
    """Port names declared by the protocols this fake stands in for."""
    protocols = (RoomMembershipPorts, ReadinessPorts)
    return {
        name
        for protocol in protocols
        for name, member in vars(protocol).items()
        if not name.startswith('_') and callable(member)
    }


def _ports(**results):
    ports = Mock()
    ports.timeline = []

    @contextmanager
    def atomic():
        ports.timeline.append('begin')
        try:
            yield
        except Exception:
            ports.timeline.append('rollback')
            raise
        else:
            ports.timeline.append('commit')

    ports.atomic.side_effect = atomic

    # Record every declared port, not only the ones configured below. Recording
    # just the configured names let a timeline assertion omit a step silently, so
    # it passed or failed for a reason unrelated to the sequence under test.
    # Unconfigured ports return an inert sentinel instead of a fabricated value.
    for name in sorted(_declared_ports() - {'atomic'}):
        result = results.get(name, _UNSET)

        def operation(*args, _name=name, _result=result, **kwargs):
            ports.timeline.append(_name)
            if isinstance(_result, deque):
                return _result.popleft()
            return _result

        getattr(ports, name).side_effect = operation

    ports.session_was_removed.return_value = False
    return ports


def _new_member_data():
    # The client posts its session id, so the use case looks the participant up
    # before falling through to creation; a visitor with no session id is a
    # different branch and is covered by its own identity-requirement test.
    return {
        'game_id': 'starlight-garden',
        'session_id': uuid4(),
        'display_name': 'Guest One',
        'game_marker': 'silver-leaf',
    }


def _participant(presence='offline'):
    return ParticipantMembership(
        id=24,
        session_id=uuid4(),
        public_id=uuid4(),
        display_name='Guest One',
        game_marker='silver-leaf',
        presence=presence,
        was_left=False,
    )
