"""Compatibility exports retained for existing room integrations."""

from .features.expulsion_voting.infrastructure.django_compat import (
    is_inactive_target,
    mark_grace_expired,
)
from .features.expulsion_voting.application.cancellations import (
    ExpulsionVoteCancellation,
)
from .features.expulsion_voting.infrastructure.django_gateway import (
    DjangoExpulsionVotingGateway,
)
from .features.expulsion_voting.infrastructure.snapshot import expulsion_vote_snapshot
from .constants import RECONNECT_GRACE_SECONDS


def cancel_pending_vote_for_target(room, participant, reason):
    cancellation = ExpulsionVoteCancellation(DjangoExpulsionVotingGateway())
    return cancellation.for_target(room.pk, participant.pk, reason)


def cancel_pending_vote_for_participant(room, participant, target_reason, voter_reason):
    cancellation = ExpulsionVoteCancellation(DjangoExpulsionVotingGateway())
    return cancellation.for_participant(
        room.pk,
        participant.pk,
        target_reason,
        voter_reason,
    )


__all__ = (
    'cancel_pending_vote_for_participant',
    'cancel_pending_vote_for_target',
    'expulsion_vote_snapshot',
    'is_inactive_target',
    'mark_grace_expired',
    'RECONNECT_GRACE_SECONDS',
)
