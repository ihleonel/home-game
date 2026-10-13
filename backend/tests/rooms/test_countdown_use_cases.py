"""Use-case and timer tests for the lobby countdown slice (CDS-02).

The use cases are framework-free, so every collaborator is a recording fake:
``ports.broadcasts`` captures the published event tuples and ``ports.timeline``
records the port calls in order. Async ports are faked with async side effects
so the use cases can ``await`` them exactly as they will the production
gateway.
"""

import asyncio
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from modules.rooms.features.countdown.application.ports import (
    LobbyLimits,
    LobbyState,
)
from modules.rooms.features.countdown.application.use_cases import (
    expire_lobby_countdown,
    sync_lobby_countdown,
)
from modules.rooms.features.countdown.domain.rules import (
    CANCELLED_LOBBY_CHANGED,
    CANCELLED_START_FAILED,
    COUNTDOWN_CANCELLED_EVENT,
    COUNTDOWN_EVENT,
    LOBBY_COUNTDOWN_SECONDS,
    cancelled_payload,
    countdown_payload,
    lobby_is_ready,
)
from modules.rooms.features.countdown.infrastructure import timer as timer_module
from modules.rooms.features.countdown.infrastructure.timer import (
    ArmedCountdown,
    AsyncioCountdownTimer,
)

_UNSET = object()
_ARMED = object()

USE_CASE_LOGGER = 'modules.rooms.features.countdown.application.use_cases'


def _snapshot(*readiness, game_id='duelo'):
    return {
        'game_id': game_id,
        'participants': [{'is_ready': ready} for ready in readiness],
    }


def _ports(
    *,
    limits=None,
    current=None,
    arm_result=_UNSET,
    cancel_result=None,
    prepare=_UNSET,
    prepare_error=None,
    start_error=None,
    broadcast_error=None,
):
    """Recording fake for :class:`LobbyCountdownPorts`.

    Sync ports resolve immediately; async ports are async side effects so an
    ``await`` on the fake behaves like the production adapter. ``prepare``
    defaults to ``None`` so the missing-room branch is the default and a test
    only opts in to a state when it needs one.
    """
    ports = Mock()
    ports.timeline = []
    ports.broadcasts = []

    def sync(name, value):
        def operation(*args, **kwargs):
            ports.timeline.append(name)
            return value

        return operation

    def async_op(name, value):
        async def operation(*args, **kwargs):
            ports.timeline.append(name)
            return value

        return operation

    ports.game_limits.side_effect = sync('game_limits', limits)
    ports.current_countdown.side_effect = sync('current_countdown', current)
    ports.arm_countdown.side_effect = sync(
        'arm_countdown', _ARMED if arm_result is _UNSET else arm_result
    )
    ports.cancel_countdown.side_effect = sync('cancel_countdown', cancel_result)
    if prepare_error is None:
        ports.prepare_lobby.side_effect = async_op(
            'prepare_lobby', None if prepare is _UNSET else prepare
        )
    else:

        async def prepare_lobby(*args, **kwargs):
            ports.timeline.append('prepare_lobby')
            raise prepare_error

        ports.prepare_lobby.side_effect = prepare_lobby

    if start_error is None:
        ports.start_match.side_effect = async_op('start_match', None)
    else:

        async def start_match(*args, **kwargs):
            ports.timeline.append('start_match')
            raise start_error

        ports.start_match.side_effect = start_match

    async def broadcast(room_id, event_name, snapshot, countdown):
        ports.timeline.append('broadcast')
        ports.broadcasts.append((room_id, event_name, snapshot, countdown))
        if broadcast_error is not None:
            raise broadcast_error

    ports.broadcast.side_effect = broadcast
    return ports


class LobbyReadyRuleTests(SimpleTestCase):
    def test_lone_ready_player_under_the_minimum_is_not_ready(self):
        self.assertFalse(lobby_is_ready(_snapshot(True), 2, 2))

    def test_exactly_the_minimum_ready_is_ready(self):
        self.assertTrue(lobby_is_ready(_snapshot(True, True), 2, 2))

    def test_more_than_the_maximum_is_not_ready(self):
        self.assertFalse(lobby_is_ready(_snapshot(True, True, True), 2, 2))

    def test_a_single_not_ready_participant_blocks_readiness(self):
        self.assertFalse(lobby_is_ready(_snapshot(True, False), 2, 2))

    def test_empty_roster_is_not_ready(self):
        self.assertFalse(lobby_is_ready(_snapshot(), 2, 2))

    def test_payload_helpers_use_the_agreed_shapes(self):
        self.assertEqual(
            countdown_payload(10, 4),
            {'seconds': 10, 'remaining_seconds': 4},
        )
        self.assertEqual(
            cancelled_payload(CANCELLED_LOBBY_CHANGED),
            {'reason': 'lobby_changed'},
        )

    def test_event_constants_are_stable(self):
        self.assertEqual(LOBBY_COUNTDOWN_SECONDS, 10)
        self.assertEqual(COUNTDOWN_EVENT, 'match_countdown')
        self.assertEqual(COUNTDOWN_CANCELLED_EVENT, 'match_countdown_cancelled')


class SyncLobbyCountdownTests(SimpleTestCase):
    def test_ready_lobby_arms_once_and_broadcasts_the_countdown(self):
        snapshot = _snapshot(True, True)
        state = LobbyState(snapshot=snapshot, seatable=True)
        ports = _ports(limits=LobbyLimits(2, 2), prepare=state)
        on_expire = Mock()

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, snapshot, seconds=LOBBY_COUNTDOWN_SECONDS, on_expire=on_expire
            )
        )

        ports.arm_countdown.assert_called_once_with(5, 10, on_expire)
        self.assertEqual(
            ports.broadcasts,
            [
                (
                    5,
                    COUNTDOWN_EVENT,
                    snapshot,
                    {'seconds': 10, 'remaining_seconds': 10},
                )
            ],
        )

    def test_second_sync_while_armed_changes_nothing(self):
        snapshot = _snapshot(True, True)
        ports = _ports(limits=LobbyLimits(2, 2), current=_ARMED)

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, snapshot, seconds=10, on_expire=Mock()
            )
        )

        ports.arm_countdown.assert_not_called()
        ports.prepare_lobby.assert_not_called()
        self.assertEqual(ports.broadcasts, [])

    def test_not_ready_lobby_cancels_and_broadcasts_lobby_changed(self):
        snapshot = _snapshot(True, False)
        ports = _ports(limits=LobbyLimits(2, 2), cancel_result=_ARMED)

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, snapshot, seconds=10, on_expire=Mock()
            )
        )

        ports.cancel_countdown.assert_called_once_with(5)
        ports.arm_countdown.assert_not_called()
        self.assertEqual(
            ports.broadcasts,
            [
                (
                    5,
                    COUNTDOWN_CANCELLED_EVENT,
                    snapshot,
                    {'reason': CANCELLED_LOBBY_CHANGED},
                )
            ],
        )

    def test_not_ready_lobby_with_nothing_armed_broadcasts_nothing(self):
        snapshot = _snapshot(True, False)
        ports = _ports(limits=LobbyLimits(2, 2), cancel_result=None)

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, snapshot, seconds=10, on_expire=Mock()
            )
        )

        ports.cancel_countdown.assert_called_once_with(5)
        self.assertEqual(ports.broadcasts, [])

    def test_ready_lobby_that_is_not_seatable_arms_nothing(self):
        snapshot = _snapshot(True, True)
        state = LobbyState(snapshot=snapshot, seatable=False)
        ports = _ports(limits=LobbyLimits(2, 2), prepare=state)

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, snapshot, seconds=10, on_expire=Mock()
            )
        )

        ports.arm_countdown.assert_not_called()
        self.assertEqual(ports.broadcasts, [])

    def test_missing_room_arms_nothing(self):
        snapshot = _snapshot(True, True)
        ports = _ports(limits=LobbyLimits(2, 2), prepare=None)

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, snapshot, seconds=10, on_expire=Mock()
            )
        )

        ports.arm_countdown.assert_not_called()
        self.assertEqual(ports.broadcasts, [])

    def test_lost_race_arms_the_winner_and_broadcasts_nothing(self):
        snapshot = _snapshot(True, True)
        state = LobbyState(snapshot=snapshot, seatable=True)
        ports = _ports(limits=LobbyLimits(2, 2), prepare=state, arm_result=None)
        on_expire = Mock()

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, snapshot, seconds=10, on_expire=on_expire
            )
        )

        ports.arm_countdown.assert_called_once_with(5, 10, on_expire)
        self.assertEqual(ports.broadcasts, [])

    def test_unknown_game_returns_before_any_other_port(self):
        ports = _ports(limits=None)

        asyncio.run(
            sync_lobby_countdown(
                ports, 5, _snapshot(True, True), seconds=10, on_expire=Mock()
            )
        )

        self.assertEqual(ports.timeline, ['game_limits'])


class ExpireLobbyCountdownTests(SimpleTestCase):
    def test_seatable_lobby_starts_the_match(self):
        snapshot = _snapshot(True, True)
        state = LobbyState(snapshot=snapshot, seatable=True)
        ports = _ports(prepare=state)

        asyncio.run(expire_lobby_countdown(ports, 5))

        ports.start_match.assert_called_once_with(5)
        self.assertEqual(ports.broadcasts, [])

    def test_not_seatable_lobby_broadcasts_lobby_changed_without_starting(self):
        snapshot = _snapshot(True, False)
        state = LobbyState(snapshot=snapshot, seatable=False)
        ports = _ports(prepare=state)

        asyncio.run(expire_lobby_countdown(ports, 5))

        ports.start_match.assert_not_called()
        self.assertEqual(
            ports.broadcasts,
            [
                (
                    5,
                    COUNTDOWN_CANCELLED_EVENT,
                    snapshot,
                    {'reason': CANCELLED_LOBBY_CHANGED},
                )
            ],
        )

    def test_missing_room_returns_quietly(self):
        ports = _ports(prepare=None)

        asyncio.run(expire_lobby_countdown(ports, 5))

        ports.start_match.assert_not_called()
        self.assertEqual(ports.broadcasts, [])

    def test_start_failure_is_logged_and_broadcast_without_raising(self):
        snapshot = _snapshot(True, True)
        state = LobbyState(snapshot=snapshot, seatable=True)
        ports = _ports(prepare=state, start_error=RuntimeError('boom'))

        with self.assertLogs(USE_CASE_LOGGER, level='ERROR'):
            asyncio.run(expire_lobby_countdown(ports, 5))

        self.assertEqual(
            ports.broadcasts,
            [
                (
                    5,
                    COUNTDOWN_CANCELLED_EVENT,
                    snapshot,
                    {'reason': CANCELLED_START_FAILED},
                )
            ],
        )

    def test_prepare_lobby_failure_is_logged_and_swallowed(self):
        ports = _ports(prepare_error=RuntimeError('boom'))

        with self.assertLogs(USE_CASE_LOGGER, level='ERROR'):
            result = asyncio.run(expire_lobby_countdown(ports, 5))

        self.assertIsNone(result)
        ports.start_match.assert_not_called()
        self.assertEqual(ports.broadcasts, [])

    def test_not_seatable_broadcast_failure_is_logged_and_swallowed(self):
        snapshot = _snapshot(True, False)
        state = LobbyState(snapshot=snapshot, seatable=False)
        ports = _ports(prepare=state, broadcast_error=RuntimeError('boom'))

        with self.assertLogs(USE_CASE_LOGGER, level='ERROR'):
            result = asyncio.run(expire_lobby_countdown(ports, 5))

        self.assertIsNone(result)
        ports.start_match.assert_not_called()
        self.assertEqual(len(ports.broadcasts), 1)


class AsyncioCountdownTimerTests(SimpleTestCase):
    def test_arm_returns_none_when_already_armed(self):
        async def scenario():
            timer = AsyncioCountdownTimer()
            expired = []

            async def on_expire():
                expired.append(True)

            first = timer.arm(5, 10, on_expire)
            second = timer.arm(5, 10, on_expire)
            try:
                self.assertIsNotNone(first)
                self.assertIsNone(second)
                self.assertIs(timer.current(5), first)
            finally:
                timer.cancel(5)
                with self.assertRaises(asyncio.CancelledError):
                    await first.task
            self.assertEqual(expired, [])

        asyncio.run(scenario())

    def test_cancel_returns_the_armed_countdown_and_clears_it(self):
        async def scenario():
            timer = AsyncioCountdownTimer()

            async def on_expire():
                return None

            armed = timer.arm(5, 10, on_expire)
            cancelled = timer.cancel(5)
            self.assertIs(cancelled, armed)
            self.assertIsNone(timer.current(5))
            self.assertIsNone(timer.cancel(5))
            with self.assertRaises(asyncio.CancelledError):
                await armed.task

        asyncio.run(scenario())

    def test_expiry_runs_the_callback_and_self_cleans(self):
        async def scenario():
            timer = AsyncioCountdownTimer()
            expired = []

            async def on_expire():
                expired.append(True)

            armed = timer.arm(5, 0, on_expire)
            self.assertIs(timer.current(5), armed)
            await armed.task
            self.assertEqual(expired, [True])
            self.assertIsNone(timer.current(5))

        asyncio.run(scenario())

    def test_cancel_after_firing_does_not_cancel_the_running_expiry(self):
        async def scenario():
            timer = AsyncioCountdownTimer()
            started = asyncio.Event()
            release = asyncio.Event()
            completed = []

            async def on_expire():
                started.set()
                await release.wait()
                completed.append(True)

            armed = timer.arm(5, 0, on_expire)
            await started.wait()
            self.assertIsNone(timer.current(5))
            self.assertIsNone(timer.cancel(5))
            release.set()
            await armed.task
            self.assertEqual(completed, [True])

        asyncio.run(scenario())

    def test_remaining_seconds_counts_down_and_floors_at_zero(self):
        with patch.object(timer_module, 'time') as clock:
            clock.monotonic.return_value = 100.0
            countdown = ArmedCountdown(
                room_id=5, seconds=10, deadline=110.0, task=object()
            )
            self.assertEqual(countdown.remaining_seconds(), 10)
            clock.monotonic.return_value = 101.0
            self.assertEqual(countdown.remaining_seconds(), 9)
            clock.monotonic.return_value = 111.0
            self.assertEqual(countdown.remaining_seconds(), 0)

    def test_payload_uses_the_countdown_shape(self):
        with patch.object(timer_module, 'time') as clock:
            clock.monotonic.return_value = 100.0
            countdown = ArmedCountdown(
                room_id=5, seconds=10, deadline=104.0, task=object()
            )
            self.assertEqual(countdown.remaining_seconds(), 4)
            self.assertEqual(
                countdown.payload(),
                {'seconds': 10, 'remaining_seconds': 4},
            )
