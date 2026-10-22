from dataclasses import dataclass

from ..constants import RECONNECT_GRACE_SECONDS
from ..features.countdown.infrastructure.django_gateway import (
    DjangoLobbyCountdownGateway,
)
from ..features.expulsion_voting.application.cancellations import (
    ExpulsionVoteCancellation,
)
from ..features.expulsion_voting.infrastructure.django_gateway import (
    DjangoExpulsionVotingGateway,
)
from ..features.membership.infrastructure.django_gateway import (
    DjangoRoomMembershipGateway,
)
from ..features.presence.infrastructure.django_gateway import DjangoPresenceGateway
from ..features.readiness.infrastructure.django_gateway import DjangoReadinessGateway
from ..features.reaping.application.service import ReapingService
from ..features.reaping.infrastructure.django_gateway import (
    DjangoRoomReapingGateway,
)


@dataclass(frozen=True)
class RoomDependencies:
    membership: DjangoRoomMembershipGateway
    readiness: DjangoReadinessGateway
    presence: DjangoPresenceGateway
    expulsion_voting: DjangoExpulsionVotingGateway
    vote_cancellation: ExpulsionVoteCancellation
    reaping: ReapingService
    countdown: DjangoLobbyCountdownGateway


def compose_room_dependencies():
    expulsion_voting = DjangoExpulsionVotingGateway()
    vote_cancellation = ExpulsionVoteCancellation(expulsion_voting)
    reaping = ReapingService(
        DjangoRoomReapingGateway(),
        expulsion_voting,
        vote_cancellation,
        grace_seconds=RECONNECT_GRACE_SECONDS,
    )
    return RoomDependencies(
        membership=DjangoRoomMembershipGateway(),
        readiness=DjangoReadinessGateway(),
        presence=DjangoPresenceGateway(),
        expulsion_voting=expulsion_voting,
        vote_cancellation=vote_cancellation,
        reaping=reaping,
        countdown=DjangoLobbyCountdownGateway(reaping=reaping),
    )
