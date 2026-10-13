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
        try:
            await asyncio.sleep(seconds)
            await on_expire()
        except asyncio.CancelledError:
            raise
        finally:
            armed = self._armed.get(room_id)
            if armed is not None and armed.task is asyncio.current_task():
                self._armed.pop(room_id, None)


LOBBY_TIMER = AsyncioCountdownTimer()
