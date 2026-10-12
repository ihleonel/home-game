"""Tests for the per-seat Channels match projector (FRG-05B).

The projector is the piece that turns a single computed payload into one
delivery per seat, so the tests are written around the property the whole
feature exists for: one seat's view must never reach another seat's group,
the public group, or the room group.
"""

import json
import re
from unittest.mock import patch

from django.test import SimpleTestCase

from modules.games.duelo import rules
from modules.games.duelo.game import DueloDefinition
from modules.games.runtime.application.ports import MatchHeader, SeatRecord
from modules.games.runtime.infrastructure import channel_projector
from modules.games.runtime.infrastructure.channel_projector import (
    ChannelMatchProjector,
    match_public_group_name,
    match_seat_group_name,
)
from modules.rooms.infrastructure.events import room_group_name

# Channels constrains group names to this character set, and a name outside it
# is rejected at runtime rather than at construction time.
GROUP_NAME_RE = re.compile(r'^[a-zA-Z\d\-_.]+$')


class RecordingChannelLayer:
    """Channel-layer fake that records every ``(group, message)`` pair.

    ``group_send`` is ``async`` because the projector drives the layer through
    ``async_to_sync``; the recorder appends synchronously inside it so a test
    can read the exact pairs that were sent.
    """

    def __init__(self):
        self.sends = []

    async def group_send(self, group, message):
        self.sends.append((group, message))

    def messages_for(self, group):
        return [
            message for sent_group, message in self.sends if sent_group == group
        ]


class FailingChannelLayer(RecordingChannelLayer):
    """Recording layer that also raises, so a transport failure can be posed.

    A group in ``failing_groups`` (or every group when ``fail_all`` is set) is
    recorded and then rejected, which is what lets a test observe that the
    projector attempted a target even when the layer could not reach it.
    """

    def __init__(self, failing_groups=(), fail_all=False):
        super().__init__()
        self.failing_groups = set(failing_groups)
        self.fail_all = fail_all

    async def group_send(self, group, message):
        self.sends.append((group, message))
        if self.fail_all or group in self.failing_groups:
            raise RuntimeError(f'channel layer cannot reach {group}')

    def attempted_groups(self):
        return [group for group, _ in self.sends]


class MatchGroupNameTests(SimpleTestCase):
    def test_seat_and_public_groups_are_distinct_and_legal(self):
        match_ref = 'abc-123'

        public = match_public_group_name(match_ref)
        seat_0 = match_seat_group_name(match_ref, 0)
        seat_1 = match_seat_group_name(match_ref, 1)

        self.assertEqual(public, 'match_abc-123_public')
        self.assertEqual(seat_0, 'match_abc-123_seat_0')
        self.assertEqual(seat_1, 'match_abc-123_seat_1')
        self.assertEqual(len({public, seat_0, seat_1}), 3)
        for name in (public, seat_0, seat_1):
            self.assertRegex(name, GROUP_NAME_RE)

    def test_seat_group_uses_index_not_seat_id(self):
        # A seat id is a display-facing label; only the index is guaranteed to
        # be unique and to match the state's seat keys. Using the id here would
        # let two seats collide and would put illegal characters in a group.
        seat_group = match_seat_group_name('abc-123', 3)

        self.assertEqual(seat_group, 'match_abc-123_seat_3')


class ChannelMatchProjectorTests(SimpleTestCase):
    def setUp(self):
        self.layer = RecordingChannelLayer()
        self.projector = ChannelMatchProjector(channel_layer=self.layer)
        self.definition = DueloDefinition()
        self.match_ref = '11111111-1111-1111-1111-111111111111'
        self.seats = (
            SeatRecord(
                index=0, seat_id='seat-0', participant_ref='p0', badge='red'
            ),
            SeatRecord(
                index=1, seat_id='seat-1', participant_ref='p1', badge='blue'
            ),
        )

    def _header(self, **overrides):
        values = {
            'match_ref': self.match_ref,
            'room_id': 7,
            'game_id': 'duelo',
            'version': 1,
            'status': 'in_progress',
            'winner_seat': None,
            'seats': self.seats,
        }
        values.update(overrides)
        return MatchHeader(**values)

    def _views(self, state):
        views = {
            seat.seat_id: self.definition.view(state, seat.seat_id)
            for seat in self.seats
        }
        views[None] = self.definition.view(state, None)
        return views

    def _rock_state(self):
        state = rules.initial_state(['seat-0', 'seat-1'])
        return rules.apply_pick(state, 'seat-0', 'rock')

    def test_seat_message_has_the_exact_shape(self):
        views = {'seat-0': {'you': 'seat-0'}, None: {'public': True}}
        facts = ({'name': 'pick_recorded', 'seat': 'seat-0', 'detail': {}},)

        self.projector.publish(
            event='match_updated',
            header=self._header(),
            views=views,
            facts=facts,
        )

        seat_message = self.layer.messages_for(
            match_seat_group_name(self.match_ref, 0)
        )[0]
        self.assertEqual(
            set(seat_message),
            {
                'type',
                'event',
                'match_ref',
                'room_id',
                'version',
                'view',
                'facts',
            },
        )
        self.assertEqual(seat_message['type'], 'game.event')
        self.assertEqual(seat_message['event'], 'match_updated')
        self.assertEqual(seat_message['match_ref'], self.match_ref)
        self.assertEqual(seat_message['room_id'], 7)
        self.assertEqual(seat_message['version'], 1)
        self.assertEqual(seat_message['view'], views['seat-0'])
        self.assertEqual(seat_message['facts'], facts)

    def test_each_seat_receives_exactly_its_own_view(self):
        state = self._rock_state()
        views = self._views(state)

        self.projector.publish(
            event='match_updated',
            header=self._header(),
            views=views,
            facts=(),
        )

        seat_0_messages = self.layer.messages_for(
            match_seat_group_name(self.match_ref, 0)
        )
        seat_1_messages = self.layer.messages_for(
            match_seat_group_name(self.match_ref, 1)
        )
        public_messages = self.layer.messages_for(
            match_public_group_name(self.match_ref)
        )

        self.assertEqual(len(seat_0_messages), 1)
        self.assertEqual(len(seat_1_messages), 1)
        self.assertEqual(len(public_messages), 1)
        self.assertEqual(seat_0_messages[0]['view'], views['seat-0'])
        self.assertEqual(seat_1_messages[0]['view'], views['seat-1'])
        self.assertIsNone(seat_1_messages[0]['view']['your_pick'])
        self.assertTrue(seat_1_messages[0]['view']['opponent_has_picked'])

        # Seat 0 has committed to 'rock'. The whole payload delivered to seat 1
        # and to the public group must not contain that value anywhere; seat 0's
        # own payload must carry it.
        self.assertIn('rock', json.dumps(seat_0_messages[0]))
        self.assertNotIn('rock', json.dumps(seat_1_messages[0]))
        self.assertNotIn('rock', json.dumps(public_messages[0]))

    def test_public_group_receives_public_view_and_no_seat_view_leaks(self):
        state = self._rock_state()
        views = self._views(state)

        self.projector.publish(
            event='match_updated',
            header=self._header(),
            views=views,
            facts=(),
        )

        public_messages = self.layer.messages_for(
            match_public_group_name(self.match_ref)
        )
        self.assertEqual(len(public_messages), 1)
        self.assertEqual(public_messages[0]['view'], views[None])

        seat_0_group = match_seat_group_name(self.match_ref, 0)
        seat_1_group = match_seat_group_name(self.match_ref, 1)
        for group, message in self.layer.sends:
            if group != seat_0_group:
                self.assertNotEqual(message.get('view'), views['seat-0'])
            if group != seat_1_group:
                self.assertNotEqual(message.get('view'), views['seat-1'])

    def test_room_group_receives_nothing_for_non_start_events(self):
        state = self._rock_state()
        views = self._views(state)
        group = room_group_name(7)

        for event in ('match_updated', 'match_finished'):
            self.layer.sends.clear()
            self.projector.publish(
                event=event,
                header=self._header(),
                views=views,
                facts=(),
            )
            self.assertEqual(self.layer.messages_for(group), [])

    def test_match_started_sends_one_state_free_signal_to_the_room_group(self):
        state = rules.initial_state(['seat-0', 'seat-1'])
        views = self._views(state)

        self.projector.publish(
            event='match_started',
            header=self._header(version=0),
            views=views,
            facts=(),
        )

        room_messages = self.layer.messages_for(room_group_name(7))
        self.assertEqual(len(room_messages), 1)
        self.assertEqual(
            set(room_messages[0]), {'type', 'match_ref', 'version'}
        )
        self.assertEqual(room_messages[0]['type'], 'match.started')
        self.assertEqual(room_messages[0]['match_ref'], self.match_ref)
        self.assertEqual(room_messages[0]['version'], 0)

    def test_seat_missing_from_views_is_skipped(self):
        views = {'seat-0': {'you': 'seat-0'}, None: {'public': True}}

        self.projector.publish(
            event='match_updated',
            header=self._header(),
            views=views,
            facts=(),
        )

        seat_0_messages = self.layer.messages_for(
            match_seat_group_name(self.match_ref, 0)
        )
        self.assertEqual(len(seat_0_messages), 1)
        self.assertEqual(seat_0_messages[0]['view'], views['seat-0'])
        self.assertEqual(
            self.layer.messages_for(match_seat_group_name(self.match_ref, 1)),
            [],
        )
        self.assertEqual(
            len(
                self.layer.messages_for(
                    match_public_group_name(self.match_ref)
                )
            ),
            1,
        )

    def test_missing_public_view_is_skipped(self):
        views = {'seat-0': {'you': 'seat-0'}, 'seat-1': {'you': 'seat-1'}}

        self.projector.publish(
            event='match_updated',
            header=self._header(),
            views=views,
            facts=(),
        )

        self.assertEqual(
            self.layer.messages_for(match_public_group_name(self.match_ref)),
            [],
        )
        self.assertEqual(
            len(
                self.layer.messages_for(
                    match_seat_group_name(self.match_ref, 0)
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                self.layer.messages_for(
                    match_seat_group_name(self.match_ref, 1)
                )
            ),
            1,
        )

    def test_publish_without_a_channel_layer_is_a_silent_noop(self):
        state = rules.initial_state(['seat-0', 'seat-1'])
        views = self._views(state)
        projector = ChannelMatchProjector()

        with patch.object(
            channel_projector, 'get_channel_layer', return_value=None
        ), patch.object(channel_projector, 'async_to_sync') as async_to_sync:
            projector.publish(
                event='match_started',
                header=self._header(version=0),
                views=views,
                facts=(),
            )

        async_to_sync.assert_not_called()

    def test_injected_layer_is_used_without_the_global_one(self):
        views = {'seat-0': {'you': 'seat-0'}, None: {'public': True}}

        with patch.object(channel_projector, 'get_channel_layer') as get_layer:
            self.projector.publish(
                event='match_updated',
                header=self._header(),
                views=views,
                facts=(),
            )

        get_layer.assert_not_called()
        self.assertTrue(self.layer.sends)

    def test_a_failing_seat_group_does_not_stop_the_remaining_targets(self):
        # publish runs after the transition committed, so one unreachable group
        # must not abort the fan-out: the other seat and the public group still
        # get their message, and publish returns instead of raising.
        views = {
            'seat-0': {'you': 'seat-0'},
            'seat-1': {'you': 'seat-1'},
            None: {'public': True},
        }
        failing_group = match_seat_group_name(self.match_ref, 1)
        layer = FailingChannelLayer(failing_groups=[failing_group])
        projector = ChannelMatchProjector(channel_layer=layer)

        with self.assertLogs(
            'modules.games.runtime.infrastructure.channel_projector',
            level='ERROR',
        ):
            projector.publish(
                event='match_updated',
                header=self._header(),
                views=views,
                facts=(),
            )

        self.assertEqual(layer.attempted_groups().count(failing_group), 1)
        self.assertEqual(
            len(layer.messages_for(match_seat_group_name(self.match_ref, 0))),
            1,
        )
        self.assertEqual(
            len(layer.messages_for(match_public_group_name(self.match_ref))),
            1,
        )

    def test_a_failing_send_is_logged_with_the_target_group_and_event(self):
        views = {
            'seat-0': {'you': 'seat-0'},
            'seat-1': {'you': 'seat-1'},
            None: {'public': True},
        }
        failing_group = match_seat_group_name(self.match_ref, 1)
        layer = FailingChannelLayer(failing_groups=[failing_group])
        projector = ChannelMatchProjector(channel_layer=layer)

        with self.assertLogs(
            'modules.games.runtime.infrastructure.channel_projector',
            level='ERROR',
        ) as captured:
            projector.publish(
                event='match_updated',
                header=self._header(),
                views=views,
                facts=(),
            )

        output = '\n'.join(captured.output)
        self.assertIn(failing_group, output)
        self.assertIn('match_updated', output)

    def test_a_layer_failing_every_target_still_attempts_them_all(self):
        state = rules.initial_state(['seat-0', 'seat-1'])
        views = self._views(state)
        layer = FailingChannelLayer(fail_all=True)
        projector = ChannelMatchProjector(channel_layer=layer)

        with self.assertLogs(
            'modules.games.runtime.infrastructure.channel_projector',
            level='ERROR',
        ) as captured:
            projector.publish(
                event='match_started',
                header=self._header(version=0),
                views=views,
                facts=(),
            )

        self.assertEqual(
            sorted(layer.attempted_groups()),
            sorted(
                [
                    match_seat_group_name(self.match_ref, 0),
                    match_seat_group_name(self.match_ref, 1),
                    match_public_group_name(self.match_ref),
                    room_group_name(7),
                ]
            ),
        )
        self.assertEqual(len(captured.output), 4)
