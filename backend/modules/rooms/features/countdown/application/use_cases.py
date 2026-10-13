"""The two async lobby-countdown use cases.

They orchestrate the ports only: decide whether a lobby should be counting
down and publish the resulting event, or expire an armed countdown into a
match start. No Django, Channels or asyncio import is allowed here; the timer
is handed in through the ``on_expire`` callback.
"""

import logging

from ..domain.rules import (
    CANCELLED_LOBBY_CHANGED,
    CANCELLED_START_FAILED,
    COUNTDOWN_CANCELLED_EVENT,
    COUNTDOWN_EVENT,
    cancelled_payload,
    countdown_payload,
    lobby_is_ready,
)
from .ports import LobbyCountdownPorts

logger = logging.getLogger(__name__)


async def sync_lobby_countdown(
    ports: LobbyCountdownPorts, room_id, snapshot, *, seconds, on_expire
) -> None:
    """Reconcile the room's countdown with a freshly observed snapshot.

    A ready lobby arms one countdown and announces it; a lobby that is no
    longer ready cancels any countdown and announces the cancellation. The
    check-then-arm sequence relies on ``arm_countdown`` returning ``None``
    when another caller already armed one, so two racers can never arm twice.
    """
    limits = ports.game_limits(snapshot.get('game_id'))
    if limits is None:
        return

    if not lobby_is_ready(snapshot, limits.min_seats, limits.max_seats):
        cancelled = ports.cancel_countdown(room_id)
        if cancelled is not None:
            await ports.broadcast(
                room_id,
                COUNTDOWN_CANCELLED_EVENT,
                snapshot,
                cancelled_payload(CANCELLED_LOBBY_CHANGED),
            )
        return

    if ports.current_countdown(room_id) is not None:
        return

    state = await ports.prepare_lobby(room_id)
    if state is None or not state.seatable:
        return

    armed = ports.arm_countdown(room_id, seconds, on_expire)
    if armed is None:
        return

    await ports.broadcast(
        room_id,
        COUNTDOWN_EVENT,
        state.snapshot,
        countdown_payload(seconds, seconds),
    )


async def expire_lobby_countdown(ports: LobbyCountdownPorts, room_id) -> None:
    """Turn an expired countdown into a match start, or a cancellation.

    The timer task calls this, so it must never raise for ordinary failures.
    A concurrent starter that already opened the match is not an error: the
    gateway swallows it and returns normally. Any other failure is logged and
    swallowed, and a failing ``start_match`` is additionally broadcast as a
    ``start_failed`` cancellation. ``asyncio.CancelledError`` derives from
    ``BaseException`` (not ``Exception``), so a genuinely cancelled task still
    surfaces as cancelled instead of being mistaken for a plain failure.
    """
    try:
        state = await ports.prepare_lobby(room_id)
        if state is None:
            return

        if not state.seatable:
            await ports.broadcast(
                room_id,
                COUNTDOWN_CANCELLED_EVENT,
                state.snapshot,
                cancelled_payload(CANCELLED_LOBBY_CHANGED),
            )
            return

        try:
            await ports.start_match(room_id)
        except Exception:
            logger.exception('Lobby countdown could not start the match.')
            await ports.broadcast(
                room_id,
                COUNTDOWN_CANCELLED_EVENT,
                state.snapshot,
                cancelled_payload(CANCELLED_START_FAILED),
            )
    except Exception:
        logger.exception('Lobby countdown expiry failed.')
