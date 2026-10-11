from ..domain.errors import (
    VotingConflict,
    VotingNotFound,
    VotingPermissionDenied,
)
from ..domain.rules import (
    ballot_is_unanswered,
    grace_has_expired,
    is_connected_voter,
    is_inactive_target,
    is_self_target,
    resolve_ballot,
    resolve_electorate,
)
from .cancellations import ExpulsionVoteCancellation
from .ports import ExpulsionVotingPorts


def start_vote(ports: ExpulsionVotingPorts, data):
    with ports.atomic():
        room_id = ports.active_room_for_update()
        if room_id is None:
            raise VotingNotFound('There is no active room.')

        caller = ports.participant_for_session_for_update(
            room_id, data['session_id']
        )
        if caller is None:
            raise VotingNotFound('The session is not an active room participant.')
        if not is_connected_voter(
            caller.presence,
            lambda: ports.has_connection(room_id, str(caller.session_id)),
        ):
            raise VotingPermissionDenied('Only connected room participants can vote.')

        target = ports.participant_for_public_ref_for_update(
            room_id, data['target_ref']
        )
        if target is None:
            raise VotingNotFound('The target is not an active room participant.')
        if is_self_target(caller.id, target.id):
            raise VotingPermissionDenied(
                'A participant cannot start a vote against themselves.'
            )

        now = ports.now()
        if not is_inactive_target(target, now):
            raise VotingConflict(
                'The target has not completed the reconnect grace period.'
            )
        if ports.pending_vote_for_update(room_id) is not None:
            raise VotingConflict('A vote is already in progress for this room.')

        if grace_has_expired(target, now):
            ports.mark_target_inactive(target.id)
            ports.schedule_room_event(
                room_id,
                'participant_inactive',
                ports.room_snapshot(room_id),
            )

        online_participants = ports.online_active_participants_for_update(room_id)
        connected_sessions = {
            str(participant.session_id)
            for participant in online_participants
            if ports.has_connection(room_id, str(participant.session_id))
        }
        electorate = resolve_electorate(
            caller.id, target.id, online_participants, connected_sessions
        )
        if not electorate.caller_is_eligible:
            raise VotingPermissionDenied('The caller is not eligible to vote.')
        if not electorate.participant_ids:
            raise VotingConflict('No connected voters are available.')

        vote = ports.create_vote(room_id, target.id, caller.id)
        ports.create_ballots(vote.id, electorate.participant_ids)
        vote_summary = ports.vote_snapshot(vote.id)
        response = {'room': ports.room_snapshot(room_id), 'vote': vote_summary}
        ports.schedule_room_event(
            room_id,
            'expulsion_vote_started',
            ports.room_snapshot(room_id),
            vote=vote_summary,
        )
    return response


def cast_ballot(ports: ExpulsionVotingPorts, vote_ref, data):
    with ports.atomic():
        room_id = ports.active_room_for_update()
        if room_id is None:
            raise VotingNotFound('There is no active room.')

        vote = ports.vote_for_public_ref_for_update(room_id, vote_ref)
        if vote is None:
            raise VotingNotFound('The expulsion vote does not exist.')
        if vote.status != 'pending':
            raise VotingConflict('The expulsion vote is already resolved.')

        caller = ports.participant_for_session_for_update(
            room_id, data['session_id']
        )
        if caller is None:
            raise VotingNotFound('The session is not an active room participant.')
        if not is_connected_voter(
            caller.presence,
            lambda: ports.has_connection(room_id, str(caller.session_id)),
        ):
            raise VotingPermissionDenied('Only connected room participants can vote.')
        if is_self_target(caller.id, vote.target_id):
            raise VotingPermissionDenied('The target cannot vote on their own removal.')

        ballot = ports.ballot_for_voter_for_update(vote.id, caller.id)
        if ballot is None:
            raise VotingPermissionDenied(
                'The caller was not eligible when the vote started.'
            )
        if not ballot_is_unanswered(ballot.choice):
            raise VotingConflict('Each eligible participant may cast one ballot.')

        target = ports.participant_by_id_for_update(vote.target_id)
        inactivity_checked_at = ports.now()
        if not is_inactive_target(target, inactivity_checked_at):
            cancelled_vote = ExpulsionVoteCancellation(ports).for_target(
                room_id, target.id, 'target_reconnected'
            )
            snapshot = ports.room_snapshot(room_id)
            vote_summary = cancelled_vote or ports.vote_snapshot(vote.id)
            response = {'room': snapshot, 'vote': vote_summary}
            ports.schedule_room_event(
                room_id,
                'expulsion_vote_cancelled',
                snapshot,
                vote=vote_summary,
            )
            return response

        if target.presence == 'reconnecting' and grace_has_expired(
            target, ports.now()
        ):
            ports.mark_target_inactive(target.id)
        ports.save_ballot(ballot.id, data['choice'], ports.now())

        if data['choice'] == 'no':
            yes_count, no_count, eligible_count = 0, 0, 0
        else:
            yes_count, no_count, eligible_count = ports.ballot_counts(vote.id)
        resolution = resolve_ballot(
            data['choice'], yes_count, no_count, eligible_count
        )
        departed_session_id = None
        if resolution.remove_target:
            ports.remove_target(target.id, ports.now())
            departed_session_id = target.session_id
        if resolution.status != 'pending':
            ports.save_vote_resolution(
                vote.id, resolution.status, resolution.reason, ports.now()
            )

        vote_summary = ports.vote_snapshot(vote.id)
        snapshot = ports.room_snapshot(room_id)
        response = {'room': snapshot, 'vote': vote_summary}
        ports.schedule_room_event(
            room_id,
            resolution.event_name,
            snapshot,
            departed_session_id=departed_session_id,
            vote=vote_summary,
        )
    return response
