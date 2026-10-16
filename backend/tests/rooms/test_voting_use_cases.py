from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import call
from uuid import uuid4

from django.test import SimpleTestCase

from modules.rooms.features.expulsion_voting.application.use_cases import (
    cast_ballot,
    start_vote,
)
from modules.rooms.features.expulsion_voting.application.cancellations import (
    ExpulsionVoteCancellation,
)
from modules.rooms.features.expulsion_voting.application.ports import (
    ExpulsionVotingPorts,
)
from modules.rooms.features.expulsion_voting.domain.entities import (
    BallotRecord,
    VoteParticipant,
    VoteRecord,
)
from modules.rooms.features.expulsion_voting.domain.rules import (
    resolve_ballot,
    resolve_electorate,
)

from .support import ports_fake


class ExpulsionVotingDomainTests(SimpleTestCase):
    def test_resolution_requires_unanimous_yes_and_rejection_is_terminal(self):
        self.assertEqual(
            resolve_ballot('yes', 1, 0, 2).event_name,
            'expulsion_vote_updated',
        )
        rejected = resolve_ballot('no', 0, 0, 2)
        self.assertEqual((rejected.status, rejected.reason), ('rejected', 'voter_rejected'))
        approved = resolve_ballot('yes', 2, 0, 2)
        self.assertTrue(approved.remove_target)
        self.assertEqual(approved.event_name, 'expulsion_vote_approved')

    def test_electorate_excludes_target_and_late_unconnected_players(self):
        caller, target, voter, late = (
            _participant(1),
            _participant(2),
            _participant(3),
            _participant(4),
        )

        electorate = resolve_electorate(
            caller.id,
            target.id,
            [caller, target, voter, late],
            {str(caller.session_id), str(target.session_id), str(voter.session_id)},
        )

        self.assertEqual(electorate.participant_ids, (caller.id, voter.id))
        self.assertTrue(electorate.caller_is_eligible)


class ExpulsionVotingUseCaseTests(SimpleTestCase):
    def test_target_departure_cancels_without_checking_voter_electorate(self):
        vote = VoteRecord(41, uuid4(), 'pending', (24,), 12)
        ports = _ports(
            pending_vote_for_room_for_update=vote,
            save_vote_resolution=None,
            now=_now(),
            vote_snapshot={'resolution_reason': 'target_left'},
        )

        result = ExpulsionVoteCancellation(ports).for_participant(
            7, 24, 'target_left', 'eligible_voter_left'
        )

        self.assertEqual(result, {'resolution_reason': 'target_left'})
        ports.participant_has_ballot.assert_not_called()
        ports.save_vote_resolution.assert_called_once_with(
            vote.id, 'cancelled', 'target_left', _now()
        )

    def test_eligible_voter_departure_uses_fixed_ballot_to_select_cancel_reason(self):
        vote = VoteRecord(41, uuid4(), 'pending', (99,), 12)
        ports = _ports(
            pending_vote_for_room_for_update=vote,
            participant_has_ballot=True,
            save_vote_resolution=None,
            now=_now(),
            vote_snapshot={'resolution_reason': 'eligible_voter_disconnected'},
        )

        result = ExpulsionVoteCancellation(ports).for_participant(
            7,
            24,
            'target_disconnected',
            'eligible_voter_disconnected',
        )

        self.assertEqual(
            result, {'resolution_reason': 'eligible_voter_disconnected'}
        )
        ports.save_vote_resolution.assert_called_once_with(
            vote.id,
            'cancelled',
            'eligible_voter_disconnected',
            _now(),
        )

    def test_start_vote_fixes_connected_electorate_and_publishes_after_persistence(self):
        caller, other = _participant(1), _participant(2)
        target = _participant(
            3,
            presence='reconnecting',
            disconnected_at=_now() - timedelta(seconds=61),
        )
        vote = VoteRecord(41, uuid4(), 'pending', (target.id,), caller.id)
        ports = _ports(
            active_room_for_session_for_update=12,
            participant_for_session_for_update=caller,
            participant_for_public_ref_for_update=target,
            has_connection=deque((True, True, True)),
            pending_vote_for_update=None,
            now=_now(),
            mark_target_inactive=None,
            room_snapshot=deque(({'revision': 'inactive'}, {'revision': 'response'}, {'revision': 'event'})),
            online_active_participants_for_update=[caller, other],
            create_vote=vote,
            create_ballots=None,
            vote_snapshot={'eligible_count': 2},
            schedule_room_event=None,
        )

        response = start_vote(
            ports,
            {'session_id': caller.session_id, 'target_ref': target.public_id},
        )

        self.assertEqual(response, {'room': {'revision': 'response'}, 'vote': {'eligible_count': 2}})
        ports.create_ballots.assert_called_once_with(vote.id, (caller.id, other.id))
        self.assertEqual(
            [call.args[1] for call in ports.schedule_room_event.call_args_list],
            ['participant_inactive', 'expulsion_vote_started'],
        )
        self.assertEqual(ports.timeline[-1], 'commit')

    def test_batch_approval_emits_one_removal_per_target_in_order(self):
        caller = _participant(2)
        first = _participant(3, presence='inactive')
        second = _participant(4, presence='inactive')
        vote = VoteRecord(41, uuid4(), 'pending', (first.id, second.id), 1)
        now = _now()
        ports = _ports(
            room_for_vote_for_update=12,
            vote_for_public_ref_for_update=vote,
            participant_for_session_for_update=caller,
            has_connection=True,
            ballot_for_voter_for_update=BallotRecord(51, None),
            participant_by_id_for_update=deque((first, second)),
            now=now,
            save_ballot=None,
            ballot_counts=(1, 0, 1),
            remove_target=None,
            save_vote_resolution=None,
            vote_snapshot={'status': 'approved'},
            room_snapshot={'room': 'without-targets'},
            schedule_room_event=None,
        )

        response = cast_ballot(
            ports,
            vote.public_id,
            {'session_id': caller.session_id, 'choice': 'yes'},
        )

        self.assertEqual(response['vote']['status'], 'approved')
        self.assertEqual(
            ports.remove_target.call_args_list,
            [call(first.id, now), call(second.id, now)],
        )
        self.assertEqual(
            ports.schedule_room_event.call_args_list,
            [
                call(
                    12,
                    'expulsion_vote_approved',
                    {'room': 'without-targets'},
                    departed_session_id=first.session_id,
                    vote={'status': 'approved'},
                ),
                call(
                    12,
                    'expulsion_vote_approved',
                    {'room': 'without-targets'},
                    departed_session_id=second.session_id,
                    vote={'status': 'approved'},
                ),
            ],
        )

    def test_unanimous_yes_removes_target_and_publishes_departure(self):
        caller, target = _participant(2), _participant(3, presence='inactive')
        vote = VoteRecord(41, uuid4(), 'pending', (target.id,), 1)
        ballot = BallotRecord(51, None)
        now = _now()
        ports = _ports(
            room_for_vote_for_update=12,
            vote_for_public_ref_for_update=vote,
            participant_for_session_for_update=caller,
            has_connection=True,
            ballot_for_voter_for_update=ballot,
            participant_by_id_for_update=target,
            now=deque((now, now, now, now)),
            save_ballot=None,
            ballot_counts=(2, 0, 2),
            remove_target=None,
            save_vote_resolution=None,
            vote_snapshot={'status': 'approved'},
            room_snapshot={'room': 'without-target'},
            schedule_room_event=None,
        )

        response = cast_ballot(
            ports,
            vote.public_id,
            {'session_id': caller.session_id, 'choice': 'yes'},
        )

        self.assertEqual(response['vote']['status'], 'approved')
        ports.remove_target.assert_called_once_with(target.id, now)
        ports.schedule_room_event.assert_called_once_with(
            12,
            'expulsion_vote_approved',
            {'room': 'without-target'},
            departed_session_id=target.session_id,
            vote={'status': 'approved'},
        )

    def test_reconnected_target_cancels_pending_vote_without_casting_ballot(self):
        caller, target = _participant(2), _participant(3, presence='online')
        vote = VoteRecord(41, uuid4(), 'pending', (target.id,), 1)
        ports = _ports(
            room_for_vote_for_update=12,
            vote_for_public_ref_for_update=vote,
            participant_for_session_for_update=caller,
            has_connection=True,
            ballot_for_voter_for_update=BallotRecord(51, None),
            participant_by_id_for_update=target,
            pending_vote_for_target_for_update=vote,
            now=deque((_now(), _now())),
            save_vote_resolution=None,
            vote_snapshot={'resolution_reason': 'target_reconnected'},
            room_snapshot={'room': 'reconnected'},
            schedule_room_event=None,
        )

        response = cast_ballot(
            ports,
            vote.public_id,
            {'session_id': caller.session_id, 'choice': 'yes'},
        )

        self.assertEqual(response['vote']['resolution_reason'], 'target_reconnected')
        ports.save_ballot.assert_not_called()
        ports.save_vote_resolution.assert_called_once_with(
            vote.id, 'cancelled', 'target_reconnected', _now()
        )
        ports.schedule_room_event.assert_called_once_with(
            12,
            'expulsion_vote_cancelled',
            {'room': 'reconnected'},
            vote={'resolution_reason': 'target_reconnected'},
        )


def _ports(**results):
    return ports_fake(ExpulsionVotingPorts, **results)


def _participant(participant_id, presence='online', disconnected_at=None):
    return VoteParticipant(
        id=participant_id,
        public_id=uuid4(),
        session_id=uuid4(),
        display_name=f'Guest {participant_id}',
        presence=presence,
        was_left=False,
        disconnected_at=disconnected_at,
    )


def _now():
    return datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
