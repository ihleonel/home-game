from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response

from ..features.expulsion_voting.application.use_cases import cast_ballot, start_vote
from ..features.expulsion_voting.domain.errors import (
    VotingConflict,
    VotingNotFound,
    VotingPermissionDenied,
)
from ..features.membership.application.use_cases import (
    create_or_discover_room,
    get_active_room,
    join_room as join_room_use_case,
    leave_room as leave_room_use_case,
)
from ..features.membership.domain.errors import (
    ActiveParticipantNotFound as MembershipParticipantNotFound,
    ActiveRoomGameConflict as ActiveRoomGameConflictError,
    ActiveRoomNotFound as MembershipRoomNotFound,
    ActiveRoomSelectionRequired,
    MissingParticipantIdentity,
    ReadyParticipantCannotLeave,
    RemovedSession,
)
from ..features.readiness.application.use_cases import set_ready_state
from ..features.readiness.domain.errors import (
    ActiveParticipantNotFound,
    ActiveRoomNotFound,
)
from ..serializers import (
    ActiveRoomLookupSerializer,
    CastExpulsionBallotSerializer,
    LeaveRoomSerializer,
    ReadyStateSerializer,
    RoomRequestSerializer,
    StartExpulsionVoteSerializer,
)
from .composition import compose_room_dependencies


class ActiveRoomGameConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'La sala activa pertenece a otro juego.'
    default_code = 'active_room_game_conflict'


class ExpulsionVoteConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'La votación de expulsión ya no se puede modificar.'
    default_code = 'expulsion_vote_conflict'


class ReadyLeaveForbidden(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        'No puedes salir de la sala mientras estés listo. '
        'Deja de estar listo para poder salir.'
    )
    default_code = 'ready_participant_cannot_leave'


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
def active_room(request):
    serializer = ActiveRoomLookupSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    dependencies = compose_room_dependencies()
    try:
        # Reap first so an emptied ghost room is gone before the lookup runs,
        # and the lookup then answers "no active room" instead of a dead one.
        dependencies.reaping.reap()
        room = get_active_room(
            dependencies.membership,
            game_id=data.get('game_id'),
            session_id=data.get('session_id'),
        )
    except ActiveRoomSelectionRequired:
        raise NotFound('Indica el juego o la sesión para seleccionar una sala.')
    except MembershipRoomNotFound:
        raise NotFound('No hay ninguna sala activa.')
    return Response({'room': room})


@api_view(['POST'])
def create_room(request):
    data = _request_data(RoomRequestSerializer, request)
    dependencies = compose_room_dependencies()
    try:
        response_data, created = create_or_discover_room(
            dependencies.membership,
            data,
            dependencies.vote_cancellation,
            dependencies.reaping,
        )
    except ActiveRoomGameConflictError:
        raise ActiveRoomGameConflict()
    except RemovedSession:
        raise ValidationError({'session_id': 'Esta sesión ya no forma parte de la sala.'})
    except MissingParticipantIdentity as error:
        raise ValidationError(error.fields)
    response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(response_data, status=response_status)


@api_view(['POST'])
def join_room(request):
    data = _request_data(RoomRequestSerializer, request)
    dependencies = compose_room_dependencies()
    try:
        result = join_room_use_case(
            dependencies.membership,
            data,
            dependencies.vote_cancellation,
            dependencies.reaping,
        )
    except ActiveRoomGameConflictError:
        raise ActiveRoomGameConflict()
    except RemovedSession:
        raise ValidationError({'session_id': 'Esta sesión ya no forma parte de la sala.'})
    except MissingParticipantIdentity as error:
        raise ValidationError(error.fields)
    if result is None:
        raise NotFound('No hay ninguna sala activa a la que unirse.')
    return Response(result)


@api_view(['POST'])
def leave_room(request):
    data = _request_data(LeaveRoomSerializer, request)
    dependencies = compose_room_dependencies()
    try:
        leave_room_use_case(
            dependencies.membership,
            data,
            dependencies.vote_cancellation,
        )
    except MembershipRoomNotFound:
        raise NotFound('No hay ninguna sala activa.')
    except MembershipParticipantNotFound:
        raise NotFound('La sesión no pertenece a ningún participante activo de la sala.')
    except ReadyParticipantCannotLeave:
        raise ReadyLeaveForbidden()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['PATCH'])
def update_ready_state(request):
    data = _request_data(ReadyStateSerializer, request)
    dependencies = compose_room_dependencies()
    try:
        response_data = set_ready_state(dependencies.readiness, data)
    except ActiveRoomNotFound:
        raise NotFound('No hay ninguna sala activa.')
    except ActiveParticipantNotFound:
        raise NotFound('La sesión no pertenece a ningún participante activo de la sala.')
    return Response(response_data)


@api_view(['POST'])
def start_expulsion_vote(request):
    data = _request_data(StartExpulsionVoteSerializer, request)
    dependencies = compose_room_dependencies()
    try:
        response_data = start_vote(dependencies.expulsion_voting, data)
    except (VotingNotFound, VotingPermissionDenied, VotingConflict) as error:
        _translate_voting_error(error)
    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def cast_expulsion_ballot(request, vote_ref):
    data = _request_data(CastExpulsionBallotSerializer, request)
    dependencies = compose_room_dependencies()
    try:
        response_data = cast_ballot(
            dependencies.expulsion_voting, vote_ref, data
        )
    except (VotingNotFound, VotingPermissionDenied, VotingConflict) as error:
        _translate_voting_error(error)
    return Response(response_data, status=status.HTTP_200_OK)
