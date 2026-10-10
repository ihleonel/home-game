from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.response import Response

from .catalog import GAMES
from .models import Participant, Room
from .serializers import (
    LeaveRoomSerializer,
    ReadyStateSerializer,
    RoomRequestSerializer,
    RoomSerializer,
)


class ActiveRoomGameConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The active room belongs to a different game.'
    default_code = 'active_room_game_conflict'


def _request_data(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _membership_for(room, data):
    session_id = data.get('session_id')
    participant = None
    if session_id is not None:
        participant = Participant.objects.select_for_update().filter(
            room=room,
            session_id=session_id,
        ).first()

    if participant is not None:
        update_fields = []
        for field in ('display_name', 'game_marker'):
            if field in data and getattr(participant, field) != data[field]:
                setattr(participant, field, data[field])
                update_fields.append(field)
        if participant.left_at is not None:
            participant.left_at = None
            update_fields.append('left_at')
        if update_fields:
            update_fields.append('updated_at')
            participant.save(update_fields=tuple(update_fields))
        return participant

    missing_fields = {
        field: 'This field is required for a new room participant.'
        for field in ('display_name', 'game_marker')
        if field not in data
    }
    if missing_fields:
        raise ValidationError(missing_fields)

    return Participant.objects.create(
        room=room,
        display_name=data['display_name'],
        game_marker=data['game_marker'],
    )


def _create_or_discover_room(data):
    room = Room.objects.select_for_update().filter(
        status=Room.Status.ACTIVE
    ).first()
    created = False
    if room is None:
        room, created = Room.objects.get_or_create(
            status=Room.Status.ACTIVE,
            defaults={'game_id': data['game_id']},
        )
        room = Room.objects.select_for_update().get(pk=room.pk)

    if room.game_id != data['game_id']:
        raise ActiveRoomGameConflict()

    participant = _membership_for(room, data)
    return room, participant, created


def _room_membership_response(room, participant):
    return {
        'room': RoomSerializer(room).data,
        'session_id': str(participant.session_id),
    }


@api_view(['GET'])
def game_catalog(request):
    return Response(list(GAMES))


@api_view(['GET'])
def active_room(request):
    room = Room.objects.filter(status=Room.Status.ACTIVE).first()
    if room is None:
        raise NotFound('There is no active room.')
    return Response({'room': RoomSerializer(room).data})


@api_view(['POST'])
def create_room(request):
    data = _request_data(RoomRequestSerializer, request)
    with transaction.atomic():
        room, participant, created = _create_or_discover_room(data)
        response_data = _room_membership_response(room, participant)
    response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(response_data, status=response_status)


@api_view(['POST'])
def join_room(request):
    data = _request_data(RoomRequestSerializer, request)
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        if room is None:
            raise NotFound('There is no active room to join.')
        if room.game_id != data['game_id']:
            raise ActiveRoomGameConflict()
        participant = _membership_for(room, data)
        response_data = _room_membership_response(room, participant)
    return Response(response_data)


@api_view(['POST'])
def leave_room(request):
    data = _request_data(LeaveRoomSerializer, request)
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        if room is None:
            raise NotFound('There is no active room.')
        participant = Participant.objects.select_for_update().filter(
            room=room,
            session_id=data['session_id'],
            left_at__isnull=True,
        ).first()
        if participant is None:
            raise NotFound('The session is not an active room participant.')

        participant.left_at = timezone.now()
        participant.save(update_fields=('left_at', 'updated_at'))
        if not room.participants.filter(left_at__isnull=True).exists():
            room.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['PATCH'])
def update_ready_state(request):
    data = _request_data(ReadyStateSerializer, request)
    with transaction.atomic():
        room = Room.objects.select_for_update().filter(
            status=Room.Status.ACTIVE
        ).first()
        if room is None:
            raise NotFound('There is no active room.')
        participant = Participant.objects.select_for_update().filter(
            room=room,
            session_id=data['session_id'],
            left_at__isnull=True,
        ).first()
        if participant is None:
            raise NotFound('The session is not an active room participant.')

        participant.is_ready = data['is_ready']
        participant.save(update_fields=('is_ready', 'updated_at'))
        response_data = {'room': RoomSerializer(room).data}
    return Response(response_data)
