"""REST interface of the match runtime (FRG-06).

The three endpoints are thin transport adapters: they validate the request,
resolve the caller's room through the existing rooms machinery, and hand the
work to the framework-free use cases through the composition root in
``interfaces/composition.py``. The use cases own every rule; this module only
translates their rejections into HTTP responses.

Reads that are not a read-validate-write sequence -- the resync endpoint -- use
plain ``Match.objects``/``MatchSeat.objects`` queries, exactly like
``interfaces/match_lookup.py``, and never the locking ``DjangoMatchStore.load``,
which demands an open transaction.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from ..rooms.features.presence.application.use_cases import find_active_membership
from ..rooms.models import Participant, Room
from .contracts import seat_id
from .interfaces.composition import compose_match_dependencies
from .models import Match, MatchSeat
from .runtime.application.start_match import start_match
from .runtime.application.submit_action import submit_action
from .runtime.domain import errors as match_errors
from .serializers import (
    MatchResyncSerializer,
    StartMatchSerializer,
    SubmitActionSerializer,
)


class MatchAPIError(APIException):
    """``APIException`` whose body always carries a snake_case ``code``.

    DRF's default handler returns only ``{'detail': ...}`` for the string
    ``default_detail`` used elsewhere in this repo, which forces a client to
    parse Spanish prose to tell a resync-worthy conflict from an illegal
    action. Handing the handler a dict keeps ``detail`` and adds ``code`` from
    ``default_code``; structured extras such as the current version are merged
    afterwards so they stay raw JSON values instead of being coerced to text.
    """

    def __init__(self, detail=None, **extra):
        if detail is None:
            detail = self.default_detail
        super().__init__({'detail': detail, 'code': self.default_code})
        self.detail.update(extra)


class ActiveRoomNotFoundProblem(MatchAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = 'active_room_not_found'
    default_detail = 'No hay ninguna sala activa para esta sesión.'


class MatchNotFoundProblem(MatchAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = 'match_not_found'
    default_detail = 'No existe la partida solicitada.'


class MatchInProgressProblem(MatchAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'match_already_in_progress'
    default_detail = 'La sala ya tiene una partida en curso.'


class UnknownGameProblem(MatchAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'unknown_game'
    default_detail = 'El juego de la sala no está disponible.'


class MatchNotPlayableProblem(MatchAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'match_not_playable'
    default_detail = 'La partida ya terminó y no admite más jugadas.'


class NotASeatProblem(MatchAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'not_a_seat'
    default_detail = 'No ocupás un asiento en esta partida.'


class StaleVersionProblem(MatchAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'stale_version'
    default_detail = 'La partida cambió. Volvé a sincronizar.'


class NotYourTurnProblem(MatchAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'not_your_turn'
    default_detail = 'No es el turno de tu asiento.'


class IllegalActionProblem(MatchAPIError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'illegal_action'
    default_detail = 'La jugada no es válida.'


class WrongSeatCountProblem(MatchAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'wrong_seat_count'
    default_detail = 'La cantidad de participantes listos no es válida.'


def translate_match_error(error):
    """Raise the HTTP problem matching a runtime rejection.

    Every ``MatchError`` gets its own status code and ``default_code`` so the
    frontend can distinguish a resync (``stale_version``) from an illegal
    action (``illegal_action``) without parsing prose. ``StaleVersion`` carries
    the current version in the body so the client can resync.
    """
    if isinstance(error, match_errors.MatchNotFound):
        raise MatchNotFoundProblem()
    if isinstance(error, match_errors.UnknownGame):
        raise UnknownGameProblem()
    if isinstance(error, match_errors.MatchNotPlayable):
        raise MatchNotPlayableProblem()
    if isinstance(error, match_errors.NotASeat):
        raise NotASeatProblem()
    if isinstance(error, match_errors.StaleVersion):
        raise StaleVersionProblem(version=error.actual_version)
    if isinstance(error, match_errors.NotYourTurn):
        raise NotYourTurnProblem()
    if isinstance(error, match_errors.IllegalAction):
        raise IllegalActionProblem()
    if isinstance(error, match_errors.WrongSeatCount):
        raise WrongSeatCountProblem(
            f'Se necesitan entre {error.min_seats} y {error.max_seats} '
            f'participantes listos y hay {error.count}.'
        )
    raise error


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _active_room(presence, session_id):
    """Return the session's active room, or ``None``.

    Delegates the session-to-room resolution to the existing rooms use case so
    the games API never runs a second, divergent query.
    """
    membership = find_active_membership(presence, session_id)
    if membership is None:
        return None
    room_id, _ = membership
    return Room.objects.filter(pk=room_id).first()


def _request_participant(room_id, session_id):
    return Participant.objects.filter(
        room_id=room_id,
        session_id=session_id,
        left_at__isnull=True,
    ).first()


def _find_match(match_ref):
    """Return the match for ``match_ref``, or ``None`` for a malformed ref."""
    try:
        return Match.objects.filter(public_id=match_ref).first()
    except (ValidationError, ValueError, TypeError):
        return None


def _view_for(definition, state, seat_index):
    return definition.view(
        state, None if seat_index is None else seat_id(seat_index)
    )


def _participant_payload(record, definition, seat_index):
    return {
        'match_ref': record.match_ref,
        'version': record.version,
        'status': record.status,
        'seat_index': seat_index,
        'view': _view_for(definition, record.state, seat_index),
    }


@api_view(['POST'])
def start_match_view(request):
    """Start a match in the caller's room from its ready participants.

    The room is reaped before the seats are resolved, inside the same atomic
    block as the seat read, so a ready participant who disconnected past the
    grace window cannot occupy a seat. The runtime's own transaction starts
    only after this block closes, so it is never nested here.
    """
    data = _validated(StartMatchSerializer, request.data)
    dependencies = compose_match_dependencies()
    with transaction.atomic():
        room = _active_room(dependencies.presence, data['session_id'])
        if room is None:
            raise ActiveRoomNotFoundProblem()

        # Reap first: the seat query below must read post-reap state, so a
        # ghost-ready membership is gone before seats are enumerated.
        dependencies.reaping.reap(room_id=room.id)

        if Match.objects.filter(
            room_id=room.id, status=Match.Status.IN_PROGRESS
        ).exists():
            raise MatchInProgressProblem()

        # The seats are the room's own active participants that are ready,
        # ordered by join time. Nothing is taken from the request body, so an
        # unvalidated participant reference can never reach
        # ``DjangoMatchStore.create``.
        participants = list(
            Participant.objects.filter(
                room_id=room.id, left_at__isnull=True, is_ready=True
            ).order_by('joined_at', 'pk')
        )
        requester = _request_participant(room.id, data['session_id'])
        seats = [
            (index, str(participant.public_id), participant.game_marker)
            for index, participant in enumerate(participants)
        ]

    try:
        record = start_match(
            room_id=room.id,
            game_id=room.game_id,
            seats=seats,
            store=dependencies.store,
            registry=dependencies.registry,
            projector=dependencies.projector,
        )
    except (match_errors.UnknownGame, match_errors.WrongSeatCount) as error:
        translate_match_error(error)
    except IntegrityError:
        # ``one_active_match_per_room`` is the only integrity error the check
        # above cannot fully rule out: two concurrent starts can both pass it
        # before either commits. Map the constraint to the same clean 409.
        raise MatchInProgressProblem()

    definition = dependencies.registry.get(record.game_id)
    if definition is None:
        raise UnknownGameProblem()

    requester_ref = str(requester.public_id) if requester is not None else None
    seat_index = next(
        (
            seat.index
            for seat in record.seats
            if seat.participant_ref == requester_ref
        ),
        None,
    )
    display_names = {
        str(participant.public_id): participant.display_name
        for participant in participants
    }
    return Response(
        {
            'match_ref': record.match_ref,
            'version': record.version,
            'status': record.status,
            'seat_index': seat_index,
            'view': _view_for(definition, record.state, seat_index),
            'seats': [
                {
                    'seat_index': seat.index,
                    'participant_ref': seat.participant_ref,
                    'display_name': display_names.get(seat.participant_ref, ''),
                }
                for seat in record.seats
            ],
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
def submit_action_view(request, match_ref):
    """Apply one action of a match for the caller's participant."""
    data = _validated(SubmitActionSerializer, request.data)
    dependencies = compose_match_dependencies()
    room = _active_room(dependencies.presence, data['session_id'])
    if room is None:
        raise MatchNotFoundProblem()

    match = _find_match(match_ref)
    if match is None or match.room_id != room.id:
        raise MatchNotFoundProblem()

    participant = _request_participant(room.id, data['session_id'])
    if participant is None:
        raise MatchNotFoundProblem()

    try:
        record = submit_action(
            match_ref=str(match.public_id),
            participant_ref=str(participant.public_id),
            action_name=data['action_name'],
            action_value=data.get('action_value'),
            expected_version=data['expected_version'],
            store=dependencies.store,
            registry=dependencies.registry,
            projector=dependencies.projector,
            lifecycle=dependencies.lifecycle,
        )
    except match_errors.MatchError as error:
        translate_match_error(error)

    definition = dependencies.registry.get(record.game_id)
    seat = record.seat_for(str(participant.public_id))
    return Response(
        _participant_payload(
            record, definition, seat.index if seat is not None else None
        ),
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
def match_detail_view(request, match_ref):
    """Resync one participant's view of a match that already exists."""
    serializer = MatchResyncSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    session_id = serializer.validated_data['session_id']

    dependencies = compose_match_dependencies()
    room = _active_room(dependencies.presence, session_id)
    if room is None:
        raise MatchNotFoundProblem()

    match = _find_match(match_ref)
    if match is None or match.room_id != room.id:
        raise MatchNotFoundProblem()

    definition = dependencies.registry.get(match.game_id)
    if definition is None:
        raise UnknownGameProblem()

    participant = _request_participant(room.id, session_id)
    seat = None
    if participant is not None:
        seat = MatchSeat.objects.filter(
            match=match, participant=participant
        ).first()
    seat_index = seat.index if seat is not None else None
    return Response(
        {
            'match_ref': str(match.public_id),
            'version': match.version,
            'status': match.status,
            'seat_index': seat_index,
            'view': _view_for(definition, match.state, seat_index),
        },
        status=status.HTTP_200_OK,
    )
