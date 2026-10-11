from dataclasses import dataclass
from datetime import timedelta

from .entities import VoteResolution

RECONNECT_GRACE_SECONDS = 60


@dataclass(frozen=True)
class Electorate:
    participant_ids: tuple[int, ...]
    caller_is_eligible: bool


def is_inactive_target(participant, now, grace_seconds=RECONNECT_GRACE_SECONDS):
    if participant.was_left:
        return False
    if participant.presence == 'inactive':
        return True
    return (
        participant.presence == 'reconnecting'
        and participant.disconnected_at is not None
        and now >= participant.disconnected_at + timedelta(seconds=grace_seconds)
    )


def grace_has_expired(participant, now, grace_seconds=RECONNECT_GRACE_SECONDS):
    return (
        participant.presence == 'reconnecting'
        and is_inactive_target(participant, now, grace_seconds)
    )


def resolve_electorate(caller_id, target_id, online_participants, connected_session_ids):
    voters = tuple(
        participant.id
        for participant in online_participants
        if participant.id != target_id
        and participant.presence == 'online'
        and str(participant.session_id) in connected_session_ids
    )
    return Electorate(voters, caller_id in voters)


def is_connected_voter(presence, connection_check):
    return presence == 'online' and connection_check()


def is_self_target(caller_id, target_id):
    return caller_id == target_id


def ballot_is_unanswered(choice):
    return choice is None


def membership_cancellation_reason(
    vote_target_id,
    participant_id,
    participant_is_voter,
    target_reason,
    voter_reason,
):
    if vote_target_id == participant_id:
        return target_reason
    if participant_is_voter:
        return voter_reason
    return None


def resolve_ballot(choice, yes_count, no_count, eligible_count):
    if choice == 'no' or no_count > 0:
        return VoteResolution('rejected', 'voter_rejected', 'expulsion_vote_rejected')
    if eligible_count > 0 and yes_count == eligible_count:
        return VoteResolution(
            'approved', 'unanimous', 'expulsion_vote_approved', remove_target=True
        )
    return VoteResolution('pending', '', 'expulsion_vote_updated')
