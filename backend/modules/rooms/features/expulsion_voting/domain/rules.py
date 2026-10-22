from dataclasses import dataclass
from datetime import timedelta

from .entities import VoteResolution

RECONNECT_GRACE_SECONDS = 60

# The mixed policy (D1, D5): one connected participant alone never expels
# anyone, so an automatic vote needs at least this many eligible voters.
MIN_VOTE_QUORUM = 2

# The actions the sweep can decide for one expired absence (S3).
REAP = 'reap'
LEAVE = 'leave'
VOTE = 'vote'


@dataclass(frozen=True)
class Electorate:
    participant_ids: tuple[int, ...]
    caller_is_eligible: bool


def expired_absence(presence, disconnected_at, now, grace_seconds=RECONNECT_GRACE_SECONDS):
    """Whether a membership holds an absence past its reconnect grace (S2).

    An ``inactive`` row is already expired. A ``reconnecting`` row is expired
    once ``disconnected_at`` is at least the grace window in the past. A
    never-socketed ``offline`` row (``disconnected_at`` is ``None``) is never an
    expired absence: it never had a socket to lose, so it is only reapable.
    """
    if presence == 'inactive':
        return True
    return (
        presence == 'reconnecting'
        and disconnected_at is not None
        and now >= disconnected_at + timedelta(seconds=grace_seconds)
    )


def absence_is_spent(status, started_at, disconnected_at):
    """Whether a resolved vote already spent the current absence (S2).

    The absence identity is the ``disconnected_at`` value, so only a resolved
    vote that started at or after that instant covers it. A cancelled vote does
    not spend the absence: the next sweep may vote again.
    """
    return (
        status in ('approved', 'rejected')
        and disconnected_at is not None
        and started_at >= disconnected_at
    )


def has_vote_quorum(eligible_voter_count, quorum=MIN_VOTE_QUORUM):
    """Whether the connected electorate reaches the automatic-vote quorum."""
    return eligible_voter_count >= quorum


def resolve_sweep_action(*, expired, spent, already_voting, has_quorum):
    """The sweep's per-absence decision (S3).

    A pending vote already covering the absence is never touched; a spent
    absence is reaped; an expired absence without the vote quorum falls back to
    reaping; only an expired, unspent absence inside a quorum room joins the
    automatic batch.
    """
    if not expired:
        return REAP
    if spent:
        return REAP
    if already_voting:
        return LEAVE
    return VOTE if has_quorum else REAP


def is_inactive_target(participant, now, grace_seconds=RECONNECT_GRACE_SECONDS):
    if participant.was_left:
        return False
    return expired_absence(
        participant.presence,
        participant.disconnected_at,
        now,
        grace_seconds,
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
    participant_is_target,
    participant_is_voter,
    target_reason,
    voter_reason,
):
    if participant_is_target:
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
