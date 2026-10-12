from dataclasses import dataclass

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


@dataclass(frozen=True)
class RoomDependencies:
    membership: DjangoRoomMembershipGateway
    readiness: DjangoReadinessGateway
    presence: DjangoPresenceGateway
    expulsion_voting: DjangoExpulsionVotingGateway
    vote_cancellation: ExpulsionVoteCancellation


def compose_room_dependencies():
    expulsion_voting = DjangoExpulsionVotingGateway()
    return RoomDependencies(
        membership=DjangoRoomMembershipGateway(),
        readiness=DjangoReadinessGateway(),
        presence=DjangoPresenceGateway(),
        expulsion_voting=expulsion_voting,
        vote_cancellation=ExpulsionVoteCancellation(expulsion_voting),
    )
