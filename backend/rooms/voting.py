from datetime import timedelta

from django.utils import timezone

from .constants import RECONNECT_GRACE_SECONDS
from .models import ExpulsionBallot, ExpulsionVote, Participant


def is_inactive_target(participant, now=None):
    if participant.left_at is not None:
        return False
    if participant.presence == Participant.Presence.INACTIVE:
        return True
    now = now or timezone.now()
    return (
        participant.presence == Participant.Presence.RECONNECTING
        and participant.disconnected_at is not None
        and now >= participant.disconnected_at + timedelta(seconds=RECONNECT_GRACE_SECONDS)
    )


def mark_grace_expired(participant, now=None):
    if (
        participant.presence == Participant.Presence.RECONNECTING
        and is_inactive_target(participant, now)
    ):
        participant.presence = Participant.Presence.INACTIVE
        participant.save(update_fields=('presence', 'updated_at'))
        return True
    return False


def expulsion_vote_snapshot(vote):
    ballots = list(
        vote.ballots.select_related('voter').order_by('voter__public_id')
    )
    return {
        'vote_ref': str(vote.public_id),
        'target_ref': str(vote.target.public_id),
        'target_display_name': vote.target.display_name,
        'started_by_ref': str(vote.initiated_by.public_id),
        'status': vote.status,
        'resolution_reason': vote.resolution_reason,
        'started_at': vote.started_at.isoformat(),
        'resolved_at': vote.resolved_at.isoformat() if vote.resolved_at else None,
        'eligible_count': len(ballots),
        'yes_count': sum(ballot.choice == ExpulsionBallot.Choice.YES for ballot in ballots),
        'no_count': sum(ballot.choice == ExpulsionBallot.Choice.NO for ballot in ballots),
        'ballots': [
            {
                'participant_ref': str(ballot.voter.public_id),
                'display_name': ballot.voter.display_name,
                'choice': ballot.choice,
            }
            for ballot in ballots
        ],
    }


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
