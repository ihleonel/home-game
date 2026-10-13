"""Asyncio timer that owns the armed lobby countdowns.

Mirrors ``features/presence/infrastructure/grace_timer.py``: one module-level
timer holds an in-memory registry, each armed countdown owns its task, and the
task removes its own entry when it finishes so a later arm can start one.
"""

import asyncio
import time
from dataclasses import dataclass
from math import ceil

from ..domain.rules import countdown_payload


@dataclass(frozen=True)
class ArmedCountdown:
    room_id: int
    seconds: int
    deadline: float
    task: object

    def remaining_seconds(self) -> int:
        return max(0, ceil(self.deadline - time.monotonic()))

    def payload(self) -> dict:
        return countdown_payload(self.seconds, self.remaining_seconds())


class AsyncioCountdownTimer:
    def __init__(self):
        self._armed: dict[int, ArmedCountdown] = {}

    def current(self, room_id):
        return self._armed.get(room_id)

    def arm(self, room_id, seconds, on_expire):
        """Arm a countdown unless one is already armed.

        Returns the new :class:`ArmedCountdown`, or ``None`` when a countdown
        was already armed. The return value is the single arbiter of the race
        between concurrent sync callers.
        """
        if room_id in self._armed:
            return None
        deadline = time.monotonic() + seconds
        task = asyncio.create_task(self._run(room_id, seconds, on_expire))
        armed = ArmedCountdown(
            room_id=room_id, seconds=seconds, deadline=deadline, task=task
        )
        self._armed[room_id] = armed
        return armed

    def cancel(self, room_id):
        armed = self._armed.pop(room_id, None)
        if armed is not None and not armed.task.done():
            armed.task.cancel()
        return armed

    async def _run(self, room_id, seconds, on_expire):
        """Sleep, retire the entry, then run the expiry callback.

        The entry is retired the moment the countdown fires and before
        ``on_expire`` is awaited, so a later ``cancel`` finds nothing to cancel
        and cannot inject ``CancelledError`` into an expiry that is already
        running. A genuinely cancelled task still raises out of the ``except``
        clause below; the ``finally`` cleanup remains the backstop for the
        cancelled and failed paths that never reach the retirement step.
        """
        try:
            await asyncio.sleep(seconds)
            self._retire(room_id)
            await on_expire()
        except asyncio.CancelledError:
            raise
        finally:
            self._retire(room_id)

    def _retire(self, room_id):
        """Drop the room's entry only while this task still owns it."""
        armed = self._armed.get(room_id)
        if armed is not None and armed.task is asyncio.current_task():
            self._armed.pop(room_id, None)


LOBBY_TIMER = AsyncioCountdownTimer()
