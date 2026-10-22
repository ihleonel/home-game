"""The batch vote contract: one vote, a set of targets (S5).

The single ``target`` becomes a relation table, the snapshot publishes the set
of participant refs instead of the single ``target_ref``/``target_display_name``
pair, and ``one_pending_room_vote`` is preserved.
"""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone

from modules.rooms.connections import register_connection, unregister_connection
from modules.rooms.features.expulsion_voting.application.use_cases import cast_ballot
from modules.rooms.features.expulsion_voting.infrastructure.django_gateway import (
    DjangoExpulsionVotingGateway,
)
from modules.rooms.infrastructure.snapshots import expulsion_vote_snapshot
from modules.rooms.models import ExpulsionVote, ExpulsionVoteTarget, Participant, Room


def create_participant(room, name, presence=Participant.Presence.ONLINE):
    return Participant.objects.create(
        room=room,
        display_name=name,
        game_marker='guante-rojo',
        presence=presence,
    )


class BatchVoteRelationTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.first = create_participant(
            self.room, 'First', presence=Participant.Presence.INACTIVE
        )
        self.second = create_participant(
            self.room, 'Second', presence=Participant.Presence.INACTIVE
        )
        self.gateway = DjangoExpulsionVotingGateway()

    def test_gateway_stores_the_whole_target_set(self):
        vote = self.gateway.create_vote(
            self.room.pk, (self.first.pk, self.second.pk), origin='automatic'
        )

        stored = ExpulsionVote.objects.get(pk=vote.id)
        self.assertEqual(
            set(stored.targets.values_list('participant_id', flat=True)),
            {self.first.pk, self.second.pk},
        )

    def test_snapshot_publishes_targets_and_drops_the_single_target_fields(self):
        vote = self.gateway.create_vote(
            self.room.pk, (self.first.pk, self.second.pk), origin='automatic'
        )

        snapshot = expulsion_vote_snapshot(ExpulsionVote.objects.get(pk=vote.id))

        self.assertEqual(
            snapshot['targets'],
            [str(self.first.public_id), str(self.second.public_id)],
        )
        self.assertNotIn('target_ref', snapshot)
        self.assertNotIn('target_display_name', snapshot)
        self.assertEqual(snapshot['origin'], 'automatic')
        self.assertIsNone(snapshot['started_by_ref'])

    def test_one_pending_room_vote_is_still_enforced(self):
        from django.db import IntegrityError

        self.gateway.create_vote(self.room.pk, (self.first.pk,), origin='automatic')

        with self.assertRaises(IntegrityError):
            self.gateway.create_vote(
                self.room.pk, (self.second.pk,), origin='automatic'
            )

    def test_relation_rows_cascade_with_the_vote(self):
        vote = self.gateway.create_vote(
            self.room.pk, (self.first.pk,), origin='automatic'
        )
        vote_pk = vote.id

        ExpulsionVote.objects.filter(pk=vote_pk).delete()

        self.assertFalse(
            ExpulsionVoteTarget.objects.filter(vote_id=vote_pk).exists()
        )


class BatchApprovalEventTests(TestCase):
    def test_approved_batch_emits_one_removal_per_target(self):
        room = Room.objects.create(game_id='duelo')
        caller = create_participant(room, 'Host')
        first = create_participant(
            room, 'First', presence=Participant.Presence.INACTIVE
        )
        second = create_participant(
            room, 'Second', presence=Participant.Presence.INACTIVE
        )
        gateway = DjangoExpulsionVotingGateway()
        vote = gateway.create_vote(
            room.pk, (first.pk, second.pk), origin='automatic'
        )
        gateway.create_ballots(vote.id, (caller.pk,))
        channel_name = f'batch-{caller.public_id}'
        register_connection(room.pk, str(caller.session_id), channel_name)
        try:
            with patch(
                'modules.rooms.features.expulsion_voting.infrastructure.'
                'django_gateway.schedule_room_event'
            ) as schedule:
                cast_ballot(
                    gateway,
                    vote.public_id,
                    {'session_id': caller.session_id, 'choice': 'yes'},
                )
        finally:
            unregister_connection(
                room.pk, str(caller.session_id), channel_name
            )

        self.assertEqual(
            [call.args[1] for call in schedule.call_args_list],
            ['expulsion_vote_approved', 'expulsion_vote_approved'],
        )
        self.assertEqual(
            [
                call.kwargs['departed_session_id']
                for call in schedule.call_args_list
            ],
            [first.session_id, second.session_id],
        )
        for target in (first, second):
            target.refresh_from_db()
            self.assertIsNotNone(target.left_at)
