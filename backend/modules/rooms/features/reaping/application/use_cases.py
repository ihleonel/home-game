"""Reap memberships and rooms that nobody is coming back to, or vote them out.

Staleness is decided from the persisted ``presence``, ``disconnected_at`` and
``updated_at`` columns rather than from the in-process connection registry, so
this sweep is correct from any process and survives a restart. Two rules carry
the weight:

- a room holding an in-progress match is skipped entirely, because its seats
  belong to players who may still reconnect into the running match;
- the reaped membership clears ``is_ready`` as well as setting ``left_at``,
  because ``participant_for_session_for_update`` resolves left rows too and
  the rejoin path would otherwise revive a ready ghost.

Under the grace policy the same pass is a reap-or-vote sweep (S3): a room with
the connected vote quorum includes its expired absences in one automatic batch
and the decision rules come from the expulsion-voting domain. The presence-
agnostic ``STARTUP`` policy always reaps, because at boot nobody is connected.

Deleting an emptied room takes that room's matches with it (``Match.room`` is
CASCADE), which is the accepted cost of having no soft-close state: ``Room``
only allows ``status='active'``.
"""

from ....application.ports import VoteCancellation
from ...expulsion_voting.application.ports import ExpulsionVotingPorts
from ...expulsion_voting.domain.rules import (
    LEAVE,
    REAP,
    VOTE,
    expired_absence,
    has_vote_quorum,
    resolve_sweep_action,
)
from ..domain.entities import ReapOutcome
from ..domain.rules import GRACE, STARTUP, is_stale, reap_changes, staleness_cutoff
from .ports import ReapingPorts


def _join_order_key(participant):
    joined_at = participant.joined_at
    return (
        joined_at.timestamp() if joined_at is not None else 0.0,
        participant.id,
    )


def _reapable_by_room(participants):
    grouped = {}
    for participant in sorted(participants, key=_join_order_key):
        grouped.setdefault(participant.room_id, []).append(participant)
    return grouped


def _classify_absences(participants, voting, room_id, now, grace_seconds):
    """Split a room's reapable members into reap / leave / vote (S3).

    The quorum is a room-level property of the connected electorate, which
    never includes the targets; it is resolved once and then applied to every
    absence by the pure decision rule.
    """
    pending = set(voting.pending_vote_target_ids_for_update(room_id) or ())
    expired_flags = {
        participant.id: expired_absence(
            participant.presence,
            participant.disconnected_at,
            now,
            grace_seconds,
        )
        for participant in participants
    }
    targets = {
        participant.id
        for participant in participants
        if expired_flags[participant.id] and participant.id not in pending
    }
    electorate = tuple(
        voter_id
        for voter_id in (voting.connected_voter_ids_for_update(room_id) or ())
        if voter_id not in targets
    )
    quorum = has_vote_quorum(len(electorate))
    # ``one_pending_room_vote`` is preserved (S5), so a room that already holds
    # a pending vote cannot open a second one. An absence the running vote does
    # not cover waits for the next sweep instead of racing the constraint.
    can_open_vote = not pending

    reap_list = []
    vote_targets = []
    for participant in participants:
        is_expired = expired_flags[participant.id]
        spent = bool(
            is_expired
            and voting.absence_is_spent_for_update(
                room_id, participant.id, participant.disconnected_at
            )
        )
        action = resolve_sweep_action(
            expired=is_expired,
            spent=spent,
            already_voting=participant.id in pending,
            has_quorum=quorum,
        )
        if action == VOTE and not can_open_vote:
            action = LEAVE
        if action == REAP:
            reap_list.append(participant)
        elif action == VOTE:
            vote_targets.append(participant)
    return tuple(reap_list), tuple(vote_targets), electorate


def _start_automatic_vote(ports, voting, room_id, vote_targets, electorate):
    vote = voting.create_vote(
        room_id, tuple(participant.id for participant in vote_targets), origin='automatic'
    )
    voting.create_ballots(vote.id, electorate)
    vote_summary = voting.vote_snapshot(vote.id)
    ports.schedule_room_event(
        room_id,
        'expulsion_vote_started',
        ports.room_snapshot(room_id),
        vote=vote_summary,
    )


def reap_ghost_memberships(
    ports: ReapingPorts,
    vote_cancellation: VoteCancellation,
    *,
    grace_seconds: int,
    room_id: int | None = None,
    policy: str = GRACE,
) -> ReapOutcome:
    """Reap every stale membership, never starting a vote.

    The pure reaper kept for the call sites and tests that want the reap-only
    rule; the composed service uses :func:`sweep_rooms` instead.
    """
    return sweep_rooms(
        ports,
        None,
        vote_cancellation,
        grace_seconds=grace_seconds,
        room_id=room_id,
        policy=policy,
    )


def sweep_rooms(
    ports: ReapingPorts,
    voting: ExpulsionVotingPorts | None,
    vote_cancellation: VoteCancellation,
    *,
    grace_seconds: int,
    room_id: int | None = None,
    policy: str = GRACE,
) -> ReapOutcome:
    """One idempotent reap-or-vote evaluation per room (S3).

    Inside a single transaction per call: lock the room, skip it whole when it
    holds an in-progress match, walk the stale memberships in join order
    deciding reap / leave / include in the automatic batch, and delete the room
    when nothing active remains. ``voting`` is ``None`` for the reap-only rule
    and for the presence-agnostic ``STARTUP`` policy, which never votes (S10).
    """
    with ports.atomic():
        room_ids = ports.active_room_ids(room_id=room_id)
        if not room_ids:
            return ReapOutcome(0, 0, 0)
        busy = ports.room_ids_with_in_progress_match(room_ids)
        candidate_rooms = tuple(
            room for room in sorted(room_ids) if room not in busy
        )
        if not candidate_rooms:
            return ReapOutcome(0, 0, 0)

        now = ports.now()
        cutoff = staleness_cutoff(now, grace_seconds)
        reapable = tuple(
            participant
            for participant in ports.reapable_participants_for_update(
                candidate_rooms, policy=policy, cutoff=cutoff
            )
            if is_stale(
                policy,
                participant.presence,
                participant.disconnected_at,
                participant.updated_at,
                cutoff,
            )
        )
        can_vote = voting is not None and policy != STARTUP

        rooms_reaped = 0
        participants_removed = 0
        rooms_deleted = 0
        grouped = _reapable_by_room(reapable)
        for target_room in sorted(grouped):
            participants = grouped[target_room]
            vote_targets = ()
            electorate = ()
            if can_vote:
                reap_list, vote_targets, electorate = _classify_absences(
                    participants, voting, target_room, now, grace_seconds
                )
            else:
                reap_list = participants
            for participant in reap_list:
                ports.save_reaped_changes(
                    participant.id, dict(reap_changes(now))
                )
                cancelled_vote = vote_cancellation.participant_left(
                    target_room, participant.id
                )
                snapshot = ports.room_snapshot(target_room)
                ports.schedule_room_event(
                    target_room,
                    'player_left',
                    snapshot,
                    departed_session_id=participant.session_id,
                )
                if cancelled_vote is not None:
                    ports.schedule_room_event(
                        target_room,
                        'expulsion_vote_cancelled',
                        snapshot,
                        vote=cancelled_vote,
                    )
                participants_removed += 1
            if reap_list:
                rooms_reaped += 1
                if not ports.has_active_participants(target_room):
                    ports.delete_room(target_room)
                    rooms_deleted += 1
            if vote_targets:
                _start_automatic_vote(
                    ports, voting, target_room, vote_targets, electorate
                )
    return ReapOutcome(rooms_reaped, participants_removed, rooms_deleted)
