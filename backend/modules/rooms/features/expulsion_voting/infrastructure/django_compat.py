from django.utils import timezone

from ....models import ExpulsionVote, Participant
from ..domain.entities import VoteParticipant
from ..domain.rules import is_inactive_target as target_is_inactive
from .snapshot import expulsion_vote_snapshot


def is_inactive_target(participant, now=None):
    now = now or timezone.now()
    return target_is_inactive(
        _participant_state(participant),
        now,
    )


def mark_grace_expired(participant, now=None):
    now = now or timezone.now()
    if (
        participant.presence == Participant.Presence.RECONNECTING
        and target_is_inactive(_participant_state(participant), now)
    ):
        participant.presence = Participant.Presence.INACTIVE
        participant.save(update_fields=('presence', 'updated_at'))
        return True
    return False


def cancel_pending_vote_for_target(room, participant, reason):
    vote = (
        ExpulsionVote.objects.select_for_update()
        .filter(
            room=room,
            target=participant,
            status=ExpulsionVote.Status.PENDING,
        )
        .select_related('target', 'initiated_by')
        .first()
    )
    if vote is None:
        return None
    return _cancel_vote(vote, reason)


def cancel_pending_vote_for_participant(room, participant, target_reason, voter_reason):
    vote = (
        ExpulsionVote.objects.select_for_update()
        .filter(room=room, status=ExpulsionVote.Status.PENDING)
        .select_related('target', 'initiated_by')
        .first()
    )
    if vote is None:
        return None
    if vote.target_id == participant.pk:
        reason = target_reason
    elif vote.ballots.filter(voter_id=participant.pk).exists():
        reason = voter_reason
    else:
        return None
    return _cancel_vote(vote, reason)


def _cancel_vote(vote, reason):
    vote.status = ExpulsionVote.Status.CANCELLED
    vote.resolution_reason = reason
    vote.resolved_at = timezone.now()
    vote.save(update_fields=('status', 'resolution_reason', 'resolved_at'))
    return expulsion_vote_snapshot(vote)


def _participant_state(participant):
    return VoteParticipant(
        id=participant.pk,
        public_id=participant.public_id,
        session_id=participant.session_id,
        display_name=participant.display_name,
        presence=participant.presence,
        was_left=participant.left_at is not None,
        disconnected_at=participant.disconnected_at,
    )
