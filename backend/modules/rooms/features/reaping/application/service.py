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

    def reap(self, *, room_id: int | None = None):
        return reap_ghost_memberships(
            self.ports,
            self.vote_cancellation,
            grace_seconds=self.grace_seconds,
            room_id=room_id,
        )
