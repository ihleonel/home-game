from ....application.ports import VoteCancellation
from .ports import ReapingPorts
from .use_cases import reap_ghost_memberships


class ReapingService:
    """Composed entry point for ghost reaping.

    Binds the reaping ports, the vote cancellation and the grace window once so
    every adapter resolves the grace constant in the same place.
    """

    def __init__(
        self,
        ports: ReapingPorts,
        vote_cancellation: VoteCancellation,
        *,
        grace_seconds: int,
    ):
        self.ports = ports
        self.vote_cancellation = vote_cancellation
        self.grace_seconds = grace_seconds

    def reap(self, *, room_id: int | None = None, grace_seconds: int | None = None):
        """Reap ghost memberships and rooms.

        ``grace_seconds`` overrides the composed grace window for a single run
        and ``None`` keeps the bound value, so every adapter resolves the
        window in one place and ``--startup`` can pass ``0`` without a second
        code path.
        """
        bound_grace = self.grace_seconds if grace_seconds is None else grace_seconds
        return reap_ghost_memberships(
            self.ports,
            self.vote_cancellation,
            grace_seconds=bound_grace,
            room_id=room_id,
        )
