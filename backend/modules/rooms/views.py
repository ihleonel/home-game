from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response

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
from .features.expulsion_voting.application.use_cases import (
    cast_ballot,
    start_vote,
)
from .features.expulsion_voting.domain.errors import (
    VotingConflict,
    VotingNotFound,
    VotingPermissionDenied,
)
from .features.expulsion_voting.infrastructure.django_gateway import (
    DjangoExpulsionVotingGateway,
)
from .serializers import (
    CastExpulsionBallotSerializer,
    LeaveRoomSerializer,
    ReadyStateSerializer,
    RoomRequestSerializer,
    StartExpulsionVoteSerializer,
)


class ActiveRoomGameConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The active room belongs to a different game.'
    default_code = 'active_room_game_conflict'


class ExpulsionVoteConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The expulsion vote can no longer be changed.'
    default_code = 'expulsion_vote_conflict'


def _translate_voting_error(error):
    if isinstance(error, VotingNotFound):
        raise NotFound(str(error))
    if isinstance(error, VotingPermissionDenied):
        raise PermissionDenied(str(error))
    if isinstance(error, VotingConflict):
        raise ExpulsionVoteConflict(str(error))
    raise error


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
    try:
        response_data = start_vote(DjangoExpulsionVotingGateway(), data)
    except (VotingNotFound, VotingPermissionDenied, VotingConflict) as error:
        _translate_voting_error(error)
    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def cast_expulsion_ballot(request, vote_ref):
    data = _request_data(CastExpulsionBallotSerializer, request)
    try:
        response_data = cast_ballot(
            DjangoExpulsionVotingGateway(), vote_ref, data
        )
    except (VotingNotFound, VotingPermissionDenied, VotingConflict) as error:
        _translate_voting_error(error)
    return Response(response_data, status=status.HTTP_200_OK)
