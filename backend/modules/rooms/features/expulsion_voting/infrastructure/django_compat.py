from django.utils import timezone

from ....models import Participant
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
