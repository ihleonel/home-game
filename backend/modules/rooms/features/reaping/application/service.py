from ....application.ports import VoteCancellation
from ...expulsion_voting.application.ports import ExpulsionVotingPorts
from ..domain.rules import GRACE
from .ports import ReapingPorts
from .use_cases import sweep_rooms


class ReapingService:
    """Composed entry point for the reap-or-vote sweep.

    Binds the reaping ports, the expulsion-voting ports, the vote cancellation
    and the grace window once so every adapter resolves the grace constant in
    the same place. ``reap`` is the sweep (S3): it reaps a stale membership or,
    when the room holds the vote quorum, includes it in one automatic batch.
    """

    def __init__(
        self,
        ports: ReapingPorts,
        voting: ExpulsionVotingPorts,
        vote_cancellation: VoteCancellation,
        *,
        grace_seconds: int,
    ):
        self.ports = ports
        self.voting = voting
        self.vote_cancellation = vote_cancellation
        self.grace_seconds = grace_seconds

    def reap(self, *, room_id: int | None = None, policy: str = GRACE):
        """Sweep ghost memberships, rooms, and automatic votes.

        The grace window stays bound here; adapters only choose the staleness
        policy. ``GRACE`` (the default) is the hot-path and on-demand rule that
        can vote; ``STARTUP`` is the presence-agnostic boot sweep, which never
        votes because nobody can be connected to a process that just started.
        """
        return sweep_rooms(
            self.ports,
            self.voting,
            self.vote_cancellation,
            grace_seconds=self.grace_seconds,
            room_id=room_id,
            policy=policy,
        )
