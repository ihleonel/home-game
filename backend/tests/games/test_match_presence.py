"""Datastore tests for the per-seat presence projection (S1, S6).

The projection publishes who is still around in a running match: each seat's
presence derived from the participant that occupies it, with the same grace
criterion the room snapshot already applies. The tests run against real
Postgres because the resolver reads the persisted match, its seats and the
participants behind them.
"""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from modules.games.duelo import rules
from modules.games.interfaces.match_presence import (
    publish_match_presence,
    resolve_match_presence,
)
from modules.games.models import Match, MatchSeat
from modules.games.runtime.infrastructure.channel_projector import (
    match_public_group_name,
    match_seat_group_name,
)
from modules.rooms.constants import RECONNECT_GRACE_SECONDS
from modules.rooms.models import Participant, Room


class RecordingChannelLayer:
    """Channel-layer fake that records every ``(group, message)`` pair."""

    def __init__(self):
        self.sends = []

    async def group_send(self, group, message):
        self.sends.append((group, message))

    def messages_for(self, group):
        return [
            message
            for sent_group, message in self.sends
            if sent_group == group
        ]


class MatchPresenceTestCase(TestCase):
    """Shared fixture: one room with two online participants and a match."""

    def setUp(self):
        self.room = Room.objects.create(game_id='duelo')
        self.first = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest One',
            game_marker='guante-rojo',
            presence=Participant.Presence.ONLINE,
        )
        self.second = Participant.objects.create(
            room=self.room,
            session_id=uuid.uuid4(),
            display_name='Guest Two',
            game_marker='guante-azul',
            presence=Participant.Presence.ONLINE,
        )

    def create_match(
        self,
        *,
        status=Match.Status.IN_PROGRESS,
        with_seats=True,
    ):
        match = Match.objects.create(
            room=self.room,
            game_id='duelo',
            status=status,
            state=rules.initial_state(['seat-0', 'seat-1']),
        )
        if with_seats:
            MatchSeat.objects.create(
                match=match, index=0, seat_id='seat-0', participant=self.first
            )
            MatchSeat.objects.create(
                match=match, index=1, seat_id='seat-1', participant=self.second
            )
        return match


class ResolveMatchPresenceTests(MatchPresenceTestCase):
    def test_resolves_the_in_progress_match_with_every_seat_presence(self):
        match = self.create_match()

        presence = resolve_match_presence(self.room.id)

        self.assertIsNotNone(presence)
        self.assertEqual(presence.match_ref, str(match.public_id))
        self.assertEqual(
            presence.payload(),
            [
                {'index': 0, 'presence': 'online'},
                {'index': 1, 'presence': 'online'},
            ],
        )

    def test_an_expired_reconnecting_seat_is_reported_inactive(self):
        self.second.presence = Participant.Presence.RECONNECTING
        self.second.disconnected_at = timezone.now() - timedelta(
            seconds=RECONNECT_GRACE_SECONDS + 1
        )
        self.second.save(
            update_fields=('presence', 'disconnected_at', 'updated_at')
        )
        self.create_match()

        presence = resolve_match_presence(self.room.id)

        self.assertEqual(
            presence.payload(),
            [
                {'index': 0, 'presence': 'online'},
                {'index': 1, 'presence': 'inactive'},
            ],
        )

    def test_a_reconnecting_seat_inside_the_grace_stays_reconnecting(self):
        self.second.presence = Participant.Presence.RECONNECTING
        self.second.disconnected_at = timezone.now()
        self.second.save(
            update_fields=('presence', 'disconnected_at', 'updated_at')
        )
        self.create_match()

        presence = resolve_match_presence(self.room.id)

        self.assertEqual(
            presence.payload(),
            [
                {'index': 0, 'presence': 'online'},
                {'index': 1, 'presence': 'reconnecting'},
            ],
        )

    def test_a_seat_that_never_held_a_socket_is_not_present(self):
        self.first.presence = Participant.Presence.OFFLINE
        self.first.save(update_fields=('presence', 'updated_at'))
        self.create_match()

        presence = resolve_match_presence(self.room.id)

        self.assertEqual(presence.payload()[0]['presence'], 'inactive')

    def test_a_room_without_an_in_progress_match_resolves_to_none(self):
        self.create_match(status=Match.Status.FINISHED)

        self.assertIsNone(resolve_match_presence(self.room.id))


class PartlyFailingChannelLayer(RecordingChannelLayer):
    """Layer whose one unreachable group must not silence the others."""

    def __init__(self, broken_group):
        super().__init__()
        self.broken_group = broken_group

    async def group_send(self, group, message):
        if group == self.broken_group:
            raise RuntimeError('channel layer is down')
        await super().group_send(group, message)


class PublishMatchPresenceTests(MatchPresenceTestCase):
    def test_publishes_the_frame_to_every_seat_and_the_public_group(self):
        match = self.create_match()
        match_ref = str(match.public_id)
        layer = RecordingChannelLayer()

        presence = publish_match_presence(self.room.id, channel_layer=layer)

        self.assertIsNotNone(presence)
        expected = {
            'type': 'game.presence',
            'match_ref': match_ref,
            'seats': [
                {'index': 0, 'presence': 'online'},
                {'index': 1, 'presence': 'online'},
            ],
        }
        expected_groups = {
            match_seat_group_name(match_ref, 0),
            match_seat_group_name(match_ref, 1),
            match_public_group_name(match_ref),
        }
        self.assertEqual({group for group, _ in layer.sends}, expected_groups)
        for group in expected_groups:
            self.assertEqual(layer.messages_for(group), [expected])

    def test_publishing_without_an_in_progress_match_sends_nothing(self):
        self.create_match(status=Match.Status.FINISHED)
        layer = RecordingChannelLayer()

        self.assertIsNone(
            publish_match_presence(self.room.id, channel_layer=layer)
        )
        self.assertEqual(layer.sends, [])

    def test_one_unreachable_group_still_reaches_every_other_target(self):
        match = self.create_match()
        match_ref = str(match.public_id)
        broken = match_seat_group_name(match_ref, 0)
        layer = PartlyFailingChannelLayer(broken)

        presence = publish_match_presence(self.room.id, channel_layer=layer)

        self.assertIsNotNone(presence)
        self.assertEqual(
            [group for group, _ in layer.sends],
            [
                match_seat_group_name(match_ref, 1),
                match_public_group_name(match_ref),
            ],
        )
