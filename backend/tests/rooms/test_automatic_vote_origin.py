"""Automatic vote initiation across the voterless boundary (S6).

A vote can now start without a human: ``initiated_by`` is nullable and the vote
carries an ``origin`` (``automatic`` | ``manual``, default ``automatic``). The
snapshot tolerates both and the manual REST path keeps writing ``manual`` with
its caller.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.test import APITestCase

from modules.rooms.features.expulsion_voting.infrastructure.django_gateway import (
    DjangoExpulsionVotingGateway,
)
from modules.rooms.infrastructure.snapshots import expulsion_vote_snapshot
from modules.rooms.models import ExpulsionVote, Participant, Room


def create_participant(room, name='Guest', presence=Participant.Presence.ONLINE):
    return Participant.objects.create(
        room=room,
        display_name=name,
        game_marker='guante-rojo',
        presence=presence,
    )


class AutomaticVoteGatewayTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.target = create_participant(
            self.room,
            name='Ghost',
            presence=Participant.Presence.INACTIVE,
        )
        self.gateway = DjangoExpulsionVotingGateway()

    def test_gateway_creates_an_automatic_vote_without_a_caller(self):
        vote = self.gateway.create_vote(
            self.room.pk, (self.target.pk,), origin='automatic'
        )

        stored = ExpulsionVote.objects.get(pk=vote.id)
        self.assertIsNone(stored.initiated_by)
        self.assertEqual(stored.origin, ExpulsionVote.Origin.AUTOMATIC)

        snapshot = expulsion_vote_snapshot(stored)
        self.assertIsNone(snapshot['started_by_ref'])
        self.assertEqual(snapshot['origin'], 'automatic')

    def test_manual_origin_keeps_its_caller(self):
        caller = create_participant(self.room, name='Host')

        vote = self.gateway.create_vote(
            self.room.pk,
            (self.target.pk,),
            caller_id=caller.pk,
            origin='manual',
        )

        stored = ExpulsionVote.objects.get(pk=vote.id)
        self.assertEqual(stored.initiated_by_id, caller.pk)
        self.assertEqual(stored.origin, ExpulsionVote.Origin.MANUAL)
        self.assertEqual(
            expulsion_vote_snapshot(stored)['started_by_ref'],
            str(caller.public_id),
        )

    def test_new_votes_default_to_the_automatic_origin(self):
        vote = ExpulsionVote.objects.create(room=self.room)

        self.assertEqual(vote.origin, ExpulsionVote.Origin.AUTOMATIC)
        self.assertIsNone(vote.initiated_by_id)


class ManualVoteOriginApiTests(APITestCase):
    def test_manual_endpoint_persists_manual_origin_with_the_caller(self):
        room = Room.objects.create(game_id='duelo')
        caller = create_participant(room, name='Host')
        other = create_participant(room, name='Other')
        target = create_participant(
            room,
            name='Ghost',
            presence=Participant.Presence.INACTIVE,
        )
        target.disconnected_at = timezone.now() - timedelta(seconds=61)
        target.save(update_fields=('disconnected_at',))
        from modules.rooms.connections import (
            register_connection,
            unregister_connection,
        )

        for participant in (caller, other):
            register_connection(
                room.pk, str(participant.session_id), f'test-{participant.pk}'
            )

        try:
            response = self.client.post(
                '/api/rooms/expulsion-votes/',
                {
                    'session_id': str(caller.session_id),
                    'target_ref': str(target.public_id),
                },
                format='json',
            )
        finally:
            for participant in (caller, other):
                unregister_connection(
                    room.pk, str(participant.session_id), f'test-{participant.pk}'
                )

        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        vote = ExpulsionVote.objects.get()
        self.assertEqual(vote.origin, ExpulsionVote.Origin.MANUAL)
        self.assertEqual(vote.initiated_by_id, caller.pk)
        self.assertEqual(
            response.data['vote']['started_by_ref'], str(caller.public_id)
        )
        self.assertEqual(response.data['vote']['origin'], 'manual')
