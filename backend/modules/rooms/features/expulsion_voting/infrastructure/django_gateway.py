from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from ....infrastructure.connections import has_room_connection
from ....infrastructure.events import room_snapshot, schedule_room_event
from ....models import ExpulsionBallot, ExpulsionVote, Participant, Room
from .snapshot import expulsion_vote_snapshot
from ..domain.entities import BallotRecord, VoteParticipant, VoteRecord


class DjangoExpulsionVotingGateway:
    @contextmanager
    def atomic(self):
        with transaction.atomic():
            yield self

    def active_room_for_session_for_update(self, session_id):
        participants = list(
            Participant.objects.select_for_update()
            .select_related('room')
            .filter(
                session_id=session_id,
                left_at__isnull=True,
                room__status=Room.Status.ACTIVE,
            )[:2]
        )
        if len(participants) != 1:
            return None
        return participants[0].room_id

    def room_for_vote_for_update(self, vote_ref):
        vote = ExpulsionVote.objects.select_for_update().filter(
            public_id=vote_ref,
            room__status=Room.Status.ACTIVE,
        ).first()
        return vote.room_id if vote is not None else None

    def participant_for_session_for_update(self, room_id, session_id):
        participant = Participant.objects.select_for_update().filter(
            room_id=room_id,
            session_id=session_id,
            left_at__isnull=True,
        ).first()
        return self._participant_state(participant) if participant else None

    def participant_for_public_ref_for_update(self, room_id, participant_ref):
        participant = Participant.objects.select_for_update().filter(
            room_id=room_id,
            public_id=participant_ref,
            left_at__isnull=True,
        ).first()
        return self._participant_state(participant) if participant else None

    def participant_by_id_for_update(self, participant_id):
        participant = Participant.objects.select_for_update().get(pk=participant_id)
        return self._participant_state(participant)

    def has_connection(self, room_id, session_id):
        return has_room_connection(room_id, session_id)

    def online_active_participants_for_update(self, room_id):
        participants = Participant.objects.select_for_update().filter(
            room_id=room_id,
            left_at__isnull=True,
            presence=Participant.Presence.ONLINE,
        ).order_by('pk')
        return [self._participant_state(participant) for participant in participants]

    def pending_vote_for_update(self, room_id):
        vote = ExpulsionVote.objects.select_for_update().filter(
            room_id=room_id,
            status=ExpulsionVote.Status.PENDING,
        ).first()
        return self._vote_state(vote) if vote else None

    def pending_vote_for_target_for_update(self, room_id, target_id):
        vote = ExpulsionVote.objects.select_for_update().filter(
            room_id=room_id,
            target_id=target_id,
            status=ExpulsionVote.Status.PENDING,
        ).select_related('target', 'initiated_by').first()
        return self._vote_state(vote) if vote else None

    def pending_vote_for_room_for_update(self, room_id):
        vote = ExpulsionVote.objects.select_for_update().filter(
            room_id=room_id,
            status=ExpulsionVote.Status.PENDING,
        ).select_related('target', 'initiated_by').first()
        return self._vote_state(vote) if vote else None

    def participant_has_ballot(self, vote_id, participant_id):
        return ExpulsionBallot.objects.filter(
            vote_id=vote_id,
            voter_id=participant_id,
        ).exists()

    def session_was_removed(self, room_id, participant_id):
        return ExpulsionVote.objects.filter(
            room_id=room_id,
            target_id=participant_id,
            status=ExpulsionVote.Status.APPROVED,
        ).exists()

    def create_vote(self, room_id, target_id, caller_id):
        vote = ExpulsionVote.objects.create(
            room_id=room_id,
            target_id=target_id,
            initiated_by_id=caller_id,
        )
        return self._vote_state(vote)

    def create_ballots(self, vote_id, voter_ids):
        ExpulsionBallot.objects.bulk_create(
            [ExpulsionBallot(vote_id=vote_id, voter_id=voter_id) for voter_id in voter_ids]
        )

    def vote_for_public_ref_for_update(self, room_id, vote_ref):
        vote = ExpulsionVote.objects.select_for_update().filter(
            room_id=room_id,
            public_id=vote_ref,
        ).select_related('target', 'initiated_by').first()
        return self._vote_state(vote) if vote else None

    def ballot_for_voter_for_update(self, vote_id, voter_id):
        ballot = ExpulsionBallot.objects.select_for_update().filter(
            vote_id=vote_id,
            voter_id=voter_id,
        ).first()
        return BallotRecord(ballot.pk, ballot.choice) if ballot else None

    def mark_target_inactive(self, participant_id):
        participant = Participant.objects.select_for_update().get(pk=participant_id)
        participant.presence = Participant.Presence.INACTIVE
        participant.save(update_fields=('presence', 'updated_at'))

    def save_ballot(self, ballot_id, choice, cast_at):
        ballot = ExpulsionBallot.objects.select_for_update().get(pk=ballot_id)
        ballot.choice = choice
        ballot.cast_at = cast_at
        ballot.save(update_fields=('choice', 'cast_at'))

    def ballot_counts(self, vote_id):
        ballots = ExpulsionBallot.objects.filter(vote_id=vote_id)
        return (
            ballots.filter(choice=ExpulsionBallot.Choice.YES).count(),
            ballots.filter(choice=ExpulsionBallot.Choice.NO).count(),
            ballots.count(),
        )

    def remove_target(self, participant_id, left_at):
        target = Participant.objects.select_for_update().get(pk=participant_id)
        target.left_at = left_at
        target.presence = Participant.Presence.OFFLINE
        target.disconnected_at = None
        target.save(
            update_fields=('left_at', 'presence', 'disconnected_at', 'updated_at')
        )

    def save_vote_resolution(self, vote_id, status, reason, resolved_at):
        vote = ExpulsionVote.objects.select_for_update().get(pk=vote_id)
        vote.status = status
        vote.resolution_reason = reason
        vote.resolved_at = resolved_at
        vote.save(update_fields=('status', 'resolution_reason', 'resolved_at'))

    def vote_snapshot(self, vote_id):
        vote = ExpulsionVote.objects.select_related('target', 'initiated_by').get(
            pk=vote_id
        )
        return expulsion_vote_snapshot(vote)

    def room_snapshot(self, room_id):
        return room_snapshot(Room.objects.get(pk=room_id))

    def schedule_room_event(
        self,
        room_id,
        event_name,
        snapshot,
        *,
        departed_session_id=None,
        vote=None,
    ):
        schedule_room_event(
            room_id,
            event_name,
            snapshot,
            departed_session_id=departed_session_id,
            vote=vote,
        )

    def now(self):
        return timezone.now()

    @staticmethod
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

    @staticmethod
    def _vote_state(vote):
        return VoteRecord(
            id=vote.pk,
            public_id=vote.public_id,
            status=vote.status,
            target_id=vote.target_id,
            initiated_by_id=vote.initiated_by_id,
        )
