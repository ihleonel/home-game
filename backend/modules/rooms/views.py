from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response

from .connections import has_room_connection
from .events import room_snapshot, schedule_room_event
from .features.catalog.application.use_cases import list_games
from .features.catalog.infrastructure.static_catalog import StaticCatalog
from .features.membership.application.use_cases import (
    create_or_discover_room,
    get_active_room,
    join_room as join_room_use_case,
    leave_room as leave_room_use_case,
)
from .features.membership.domain.errors import (
    ActiveParticipantNotFound as MembershipParticipantNotFound,
    ActiveRoomGameConflict as ActiveRoomGameConflictError,
    ActiveRoomNotFound as MembershipRoomNotFound,
    MissingParticipantIdentity,
    RemovedSession,
)
from .features.membership.infrastructure.django_gateway import (
    DjangoRoomMembershipGateway,
)
from .features.readiness.application.use_cases import set_ready_state
from .features.readiness.domain.errors import (
    ActiveParticipantNotFound,
    ActiveRoomNotFound,
)
from .features.readiness.infrastructure.django_gateway import DjangoReadinessGateway
from .models import ExpulsionBallot, ExpulsionVote, Participant, Room
from .serializers import (
    CastExpulsionBallotSerializer,
    LeaveRoomSerializer,
    ReadyStateSerializer,
    RoomRequestSerializer,
    RoomSerializer,
    StartExpulsionVoteSerializer,
)
from .voting import (
    cancel_pending_vote_for_participant,
    cancel_pending_vote_for_target,
    expulsion_vote_snapshot,
    is_inactive_target,
    mark_grace_expired,
)


class ActiveRoomGameConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The active room belongs to a different game.'
    default_code = 'active_room_game_conflict'


class ExpulsionVoteConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The expulsion vote can no longer be changed.'
    default_code = 'expulsion_vote_conflict'


def _request_data(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


@api_view(['GET'])
def game_catalog(request):
    return Response(list(list_games(StaticCatalog())))


@api_view(['GET'])
def active_room(request):
    try:
        room = get_active_room(DjangoRoomMembershipGateway())
    except MembershipRoomNotFound:
        raise NotFound('There is no active room.')
    return Response({'room': room})


@api_view(['POST'])
def create_room(request):
    data = _request_data(RoomRequestSerializer, request)
    try:
        response_data, created = create_or_discover_room(
            DjangoRoomMembershipGateway(), data
        )
    except ActiveRoomGameConflictError:
        raise ActiveRoomGameConflict()
    except RemovedSession:
        raise ValidationError({'session_id': 'This session was removed from the room.'})
    except MissingParticipantIdentity as error:
        raise ValidationError(error.fields)
    response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(response_data, status=response_status)


@api_view(['POST'])
def join_room(request):
    data = _request_data(RoomRequestSerializer, request)
    try:
        result = join_room_use_case(DjangoRoomMembershipGateway(), data)
    except ActiveRoomGameConflictError:
        raise ActiveRoomGameConflict()
    except RemovedSession:
        raise ValidationError({'session_id': 'This session was removed from the room.'})
    except MissingParticipantIdentity as error:
        raise ValidationError(error.fields)
    if result is None:
        raise NotFound('There is no active room to join.')
    return Response(result)


@api_view(['POST'])
def leave_room(request):
    data = _request_data(LeaveRoomSerializer, request)
    try:
        leave_room_use_case(DjangoRoomMembershipGateway(), data)
    except MembershipRoomNotFound:
        raise NotFound('There is no active room.')
    except MembershipParticipantNotFound:
        raise NotFound('The session is not an active room participant.')
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['PATCH'])
def update_ready_state(request):
    data = _request_data(ReadyStateSerializer, request)
    try:
        response_data = set_ready_state(DjangoReadinessGateway(), data)
    except ActiveRoomNotFound:
        raise NotFound('There is no active room.')
    except ActiveParticipantNotFound:
        raise NotFound('The session is not an active room participant.')
    return Response(response_data)


@api_view(['POST'])
def start_expulsion_vote(request):
    data = _request_data(StartExpulsionVoteSerializer, request)
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        if room is None:
            raise NotFound('There is no active room.')

        caller = Participant.objects.select_for_update().filter(
            room=room,
            session_id=data['session_id'],
            left_at__isnull=True,
        ).first()
        if caller is None:
            raise NotFound('The session is not an active room participant.')
        if (
            caller.presence != Participant.Presence.ONLINE
            or not has_room_connection(room.pk, str(caller.session_id))
        ):
            raise PermissionDenied('Only connected room participants can vote.')

        target = Participant.objects.select_for_update().filter(
            room=room,
            public_id=data['target_ref'],
            left_at__isnull=True,
        ).first()
        if target is None:
            raise NotFound('The target is not an active room participant.')
        if target.pk == caller.pk:
            raise PermissionDenied('A participant cannot start a vote against themselves.')
        if not is_inactive_target(target):
            raise ExpulsionVoteConflict('The target has not completed the reconnect grace period.')

        pending_vote = ExpulsionVote.objects.select_for_update().filter(
            room=room,
            status=ExpulsionVote.Status.PENDING,
        ).first()
        if pending_vote is not None:
            raise ExpulsionVoteConflict('A vote is already in progress for this room.')

        target_became_inactive = mark_grace_expired(target)
        if target_became_inactive:
            schedule_room_event(
                room.pk,
                'participant_inactive',
                room_snapshot(room),
            )

        online_participants = list(
            Participant.objects.select_for_update()
            .filter(
                room=room,
                left_at__isnull=True,
                presence=Participant.Presence.ONLINE,
            )
            .exclude(pk=target.pk)
            .order_by('pk')
        )
        eligible_voters = [
            voter
            for voter in online_participants
            if has_room_connection(room.pk, str(voter.session_id))
        ]
        if not any(voter.pk == caller.pk for voter in eligible_voters):
            raise PermissionDenied('The caller is not eligible to vote.')
        if not eligible_voters:
            raise ExpulsionVoteConflict('No connected voters are available.')

        vote = ExpulsionVote.objects.create(
            room=room,
            target=target,
            initiated_by=caller,
        )
        ExpulsionBallot.objects.bulk_create(
            [ExpulsionBallot(vote=vote, voter=voter) for voter in eligible_voters]
        )
        vote_summary = expulsion_vote_snapshot(vote)
        response_data = {
            'room': RoomSerializer(room).data,
            'vote': vote_summary,
        }
        schedule_room_event(
            room.pk,
            'expulsion_vote_started',
            room_snapshot(room),
            vote=vote_summary,
        )
    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def cast_expulsion_ballot(request, vote_ref):
    data = _request_data(CastExpulsionBallotSerializer, request)
    response_status = status.HTTP_200_OK
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        if room is None:
            raise NotFound('There is no active room.')

        vote = ExpulsionVote.objects.select_for_update().filter(
            room=room,
            public_id=vote_ref,
        ).select_related('target', 'initiated_by').first()
        if vote is None:
            raise NotFound('The expulsion vote does not exist.')
        if vote.status != ExpulsionVote.Status.PENDING:
            raise ExpulsionVoteConflict('The expulsion vote is already resolved.')

        caller = Participant.objects.select_for_update().filter(
            room=room,
            session_id=data['session_id'],
            left_at__isnull=True,
        ).first()
        if caller is None:
            raise NotFound('The session is not an active room participant.')
        if (
            caller.presence != Participant.Presence.ONLINE
            or not has_room_connection(room.pk, str(caller.session_id))
        ):
            raise PermissionDenied('Only connected room participants can vote.')
        if caller.pk == vote.target_id:
            raise PermissionDenied('The target cannot vote on their own removal.')

        ballot = ExpulsionBallot.objects.select_for_update().filter(
            vote=vote,
            voter=caller,
        ).first()
        if ballot is None:
            raise PermissionDenied('The caller was not eligible when the vote started.')
        if ballot.choice is not None:
            raise ExpulsionVoteConflict('Each eligible participant may cast one ballot.')

        target = Participant.objects.select_for_update().get(pk=vote.target_id)
        if not is_inactive_target(target):
            cancelled_vote = cancel_pending_vote_for_target(
                room,
                target,
                'target_reconnected',
            )
            snapshot = room_snapshot(room)
            vote_summary = cancelled_vote or expulsion_vote_snapshot(vote)
            response_data = {'room': snapshot, 'vote': vote_summary}
            schedule_room_event(
                room.pk,
                'expulsion_vote_cancelled',
                snapshot,
                vote=vote_summary,
            )
        else:
            mark_grace_expired(target)
            ballot.choice = data['choice']
            ballot.cast_at = timezone.now()
            ballot.save(update_fields=('choice', 'cast_at'))

            departed_session_id = None
            if ballot.choice == ExpulsionBallot.Choice.NO:
                vote.status = ExpulsionVote.Status.REJECTED
                vote.resolution_reason = 'voter_rejected'
                vote.resolved_at = timezone.now()
                event_name = 'expulsion_vote_rejected'
            else:
                yes_count = vote.ballots.filter(
                    choice=ExpulsionBallot.Choice.YES
                ).count()
                no_count = vote.ballots.filter(
                    choice=ExpulsionBallot.Choice.NO
                ).count()
                eligible_count = vote.ballots.count()
                if no_count > 0:
                    vote.status = ExpulsionVote.Status.REJECTED
                    vote.resolution_reason = 'voter_rejected'
                    vote.resolved_at = timezone.now()
                    event_name = 'expulsion_vote_rejected'
                elif yes_count == eligible_count:
                    target.left_at = timezone.now()
                    target.presence = Participant.Presence.OFFLINE
                    target.disconnected_at = None
                    target.save(
                        update_fields=(
                            'left_at',
                            'presence',
                            'disconnected_at',
                            'updated_at',
                        )
                    )
                    vote.status = ExpulsionVote.Status.APPROVED
                    vote.resolution_reason = 'unanimous'
                    vote.resolved_at = timezone.now()
                    departed_session_id = target.session_id
                    event_name = 'expulsion_vote_approved'
                else:
                    event_name = 'expulsion_vote_updated'

            if vote.status != ExpulsionVote.Status.PENDING:
                vote.save(
                    update_fields=('status', 'resolution_reason', 'resolved_at')
                )
            vote_summary = expulsion_vote_snapshot(vote)
            snapshot = room_snapshot(room)
            response_data = {'room': snapshot, 'vote': vote_summary}
            schedule_room_event(
                room.pk,
                event_name,
                snapshot,
                departed_session_id=departed_session_id,
                vote=vote_summary,
            )
    return Response(response_data, status=response_status)
