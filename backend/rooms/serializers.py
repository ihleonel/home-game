from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .catalog import GAMES_BY_ID
from .constants import RECONNECT_GRACE_SECONDS
from .models import Participant, Room


class SessionIDField(serializers.UUIDField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail('invalid', value=data)
        return super().to_internal_value(data)


class RoomRequestSerializer(serializers.Serializer):
    game_id = serializers.SlugField(max_length=64)
    session_id = SessionIDField(required=False)
    display_name = serializers.CharField(max_length=80, required=False)
    game_marker = serializers.SlugField(max_length=64, required=False)

    def validate_game_id(self, value):
        if value not in GAMES_BY_ID:
            raise serializers.ValidationError('Choose a game from the catalog.')
        return value

    def validate(self, attrs):
        marker = attrs.get('game_marker')
        game = GAMES_BY_ID[attrs['game_id']]
        marker_ids = {option['id'] for option in game['markers']}
        if marker is not None and marker not in marker_ids:
            raise serializers.ValidationError(
                {'game_marker': 'Choose a marker for the selected game.'}
            )
        return attrs


class LeaveRoomSerializer(serializers.Serializer):
    session_id = SessionIDField()


class ReadyStateSerializer(serializers.Serializer):
    session_id = SessionIDField()
    is_ready = serializers.BooleanField()


class ParticipantRosterSerializer(serializers.ModelSerializer):
    presence = serializers.SerializerMethodField()

    class Meta:
        model = Participant
        fields = (
            'display_name',
            'game_marker',
            'is_ready',
            'presence',
            'disconnected_at',
            'joined_at',
        )

    def get_presence(self, participant):
        if (
            participant.presence == Participant.Presence.RECONNECTING
            and participant.disconnected_at is not None
            and timezone.now()
            >= participant.disconnected_at + timedelta(seconds=RECONNECT_GRACE_SECONDS)
        ):
            return Participant.Presence.INACTIVE
        return participant.presence


class RoomSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ('game_id', 'status', 'created_at', 'updated_at', 'participants')

    def get_participants(self, room):
        participants = room.participants.filter(left_at__isnull=True).order_by(
            'joined_at', 'pk'
        )
        return ParticipantRosterSerializer(participants, many=True).data
