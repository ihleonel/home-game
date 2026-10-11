from django.utils import timezone

from ....constants import RECONNECT_GRACE_SECONDS
from ....models import ExpulsionVote, Participant
from ...expulsion_voting.infrastructure.snapshot import expulsion_vote_snapshot
from ..domain.rules import grace_expired


def room_snapshot(room):
    participants = room.participants.filter(left_at__isnull=True).order_by(
        'joined_at', 'pk'
    )
    pending_vote = (
        ExpulsionVote.objects.filter(
            room=room,
            status=ExpulsionVote.Status.PENDING,
        )
        .select_related('target', 'initiated_by')
        .first()
    )
    return {
        'game_id': room.game_id,
        'status': room.status,
        'created_at': _datetime(room.created_at),
        'updated_at': _datetime(room.updated_at),
        'participants': [_participant_snapshot(participant) for participant in participants],
        'expulsion_vote': (
            expulsion_vote_snapshot(pending_vote) if pending_vote is not None else None
        ),
    }


def _participant_snapshot(participant):
    presence = participant.presence
    if (
        presence == Participant.Presence.RECONNECTING
        and grace_expired(
            participant.disconnected_at,
            timezone.now(),
            RECONNECT_GRACE_SECONDS,
        )
    ):
        presence = Participant.Presence.INACTIVE
    return {
        'display_name': participant.display_name,
        'participant_ref': str(participant.public_id),
        'game_marker': participant.game_marker,
        'is_ready': participant.is_ready,
        'presence': presence,
        'disconnected_at': _datetime(participant.disconnected_at),
        'joined_at': _datetime(participant.joined_at),
    }


def _datetime(value):
    if value is None:
        return None
    value = timezone.localtime(value)
    return value.isoformat().replace('+00:00', 'Z')
