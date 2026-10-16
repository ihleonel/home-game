from ..domain.rules import membership_cancellation_reason
from .ports import ExpulsionVotingPorts


class ExpulsionVoteCancellation:
    def __init__(self, ports: ExpulsionVotingPorts):
        self.ports = ports

    def session_was_removed(self, room_id, participant_id):
        return self.ports.session_was_removed(room_id, participant_id)

    def target_reconnected(self, room_id, participant_id):
        return self.for_target(room_id, participant_id, 'target_reconnected')

    def participant_disconnected(self, room_id, participant_id):
        return self.for_participant(
            room_id,
            participant_id,
            'target_disconnected',
            'eligible_voter_disconnected',
        )

    def participant_left(self, room_id, participant_id):
        return self.for_participant(
            room_id,
            participant_id,
            'target_left',
            'eligible_voter_left',
        )

    def for_target(self, room_id, participant_id, reason):
        vote = self.ports.pending_vote_for_target_for_update(room_id, participant_id)
        if vote is None:
            return None
        return self._cancel(vote.id, reason)

    def for_participant(
        self, room_id, participant_id, target_reason, voter_reason
    ):
        vote = self.ports.pending_vote_for_room_for_update(room_id)
        if vote is None:
            return None
        participant_is_target = participant_id in vote.target_ids
        reason = membership_cancellation_reason(
            participant_is_target,
            (
                False
                if participant_is_target
                else self.ports.participant_has_ballot(vote.id, participant_id)
            ),
            target_reason,
            voter_reason,
        )
        if reason is None:
            return None
        return self._cancel(vote.id, reason)

    def _cancel(self, vote_id, reason):
        self.ports.save_vote_resolution(
            vote_id,
            'cancelled',
            reason,
            self.ports.now(),
        )
        return self.ports.vote_snapshot(vote_id)
