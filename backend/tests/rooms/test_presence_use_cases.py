from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

from django.test import SimpleTestCase

from modules.rooms.features.presence.application.use_cases import (
    mark_inactive,
    mark_online,
    mark_reconnecting,
)
from modules.rooms.features.presence.domain.entities import PresenceParticipant


class PresenceUseCaseTests(SimpleTestCase):
    def test_reconnect_marks_online_and_preserves_target_vote_cancellation(self):
        participant = _participant('reconnecting', _now() - timedelta(seconds=5))
        ports = _ports(
            lock_active_room=True,
            active_participant_for_update=participant,
            save_presence_changes=None,
            cancel_vote_for_target={'status': 'cancelled'},
            room_snapshot={'room': 'online'},
        )

        result = mark_online(ports, 12, str(participant.session_id))

        self.assertEqual(result[0], {'room': 'online'})
        self.assertEqual(
            [(event.name, event.vote) for event in result[1]],
            [
                ('participant_online', None),
                ('expulsion_vote_cancelled', {'status': 'cancelled'}),
            ],
        )
        ports.save_presence_changes.assert_called_once_with(
            participant.id, {'presence': 'online', 'disconnected_at': None}
        )
        ports.cancel_vote_for_target.assert_called_once_with(
            12, participant.id, 'target_reconnected'
        )
        self.assertEqual(ports.timeline[-1], 'commit')

    def test_disconnect_persists_timestamp_and_cancels_target_or_electorate_vote(self):
        participant = _participant('online', None)
        disconnected_at = _now()
        ports = _ports(
            lock_active_room=True,
            active_participant_for_update=participant,
            now=disconnected_at,
            save_presence_changes=None,
            cancel_vote_for_participant={'status': 'cancelled'},
            room_snapshot={'room': 'reconnecting'},
        )

        result = mark_reconnecting(ports, 12, str(participant.session_id))

        self.assertEqual(result[0], {'room': 'reconnecting'})
        self.assertEqual(result[1], disconnected_at)
        self.assertEqual(
            [event.name for event in result[2]],
            ['participant_reconnecting', 'expulsion_vote_cancelled'],
        )
        ports.save_presence_changes.assert_called_once_with(
            participant.id,
            {'presence': 'reconnecting', 'disconnected_at': disconnected_at},
        )
        ports.cancel_vote_for_participant.assert_called_once_with(
            12,
            participant.id,
            target_reason='target_disconnected',
            voter_reason='eligible_voter_disconnected',
        )

    def test_grace_expiry_marks_only_matching_reconnect_and_returns_snapshot(self):
        disconnected_at = _now() - timedelta(seconds=61)
        participant = _participant('reconnecting', disconnected_at)
        ports = _ports(
            lock_active_room=True,
            reconnecting_participant_for_update=participant,
            now=_now(),
            save_presence_changes=None,
            room_snapshot={'room': 'inactive'},
        )

        result = mark_inactive(
            ports, 12, str(participant.session_id), disconnected_at, 60
        )

        self.assertEqual((result.name, result.snapshot), ('participant_inactive', {'room': 'inactive'}))
        ports.save_presence_changes.assert_called_once_with(
            participant.id, {'presence': 'inactive'}
        )

    def test_grace_expiry_does_not_change_state_before_deadline(self):
        disconnected_at = _now()
        participant = _participant('reconnecting', disconnected_at)
        ports = _ports(
            lock_active_room=True,
            reconnecting_participant_for_update=participant,
            now=disconnected_at + timedelta(seconds=59),
        )

        result = mark_inactive(
            ports, 12, str(participant.session_id), disconnected_at, 60
        )

        self.assertIsNone(result)
        ports.save_presence_changes.assert_not_called()


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
    for name, result in results.items():
        def operation(*args, _name=name, _result=result, **kwargs):
            ports.timeline.append(_name)
            if isinstance(_result, deque):
                return _result.popleft()
            return _result

        getattr(ports, name).side_effect = operation
    return ports


def _participant(presence, disconnected_at):
    return PresenceParticipant(
        id=17,
        session_id=uuid4(),
        presence=presence,
        disconnected_at=disconnected_at,
    )


def _now():
    return datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
