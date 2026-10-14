from django.utils import timezone
from rest_framework import serializers

from modules.games.composition import GAME_REGISTRY

from .constants import RECONNECT_GRACE_SECONDS
from .features.presence.domain.rules import grace_expired, remaining_seconds
from .models import ExpulsionBallot, ExpulsionVote, Participant, Room
from .infrastructure.snapshots import expulsion_vote_snapshot, seat_limits


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
    as_spectator = serializers.BooleanField(required=False, default=False)

    def validate_game_id(self, value):
        if not GAME_REGISTRY.is_known_game(value):
            raise serializers.ValidationError('Elige un juego del catálogo.')
        return value

    def validate(self, attrs):
        marker = attrs.get('game_marker')
        if marker is not None and not GAME_REGISTRY.contains_seat_option(
            attrs['game_id'], marker
        ):
            raise serializers.ValidationError(
                {'game_marker': 'Elige una ficha para el juego seleccionado.'}
            )
        return attrs


class ActiveRoomLookupSerializer(serializers.Serializer):
    game_id = serializers.SlugField(max_length=64, required=False)
    session_id = SessionIDField(required=False)

    def validate_game_id(self, value):
        if not GAME_REGISTRY.is_known_game(value):
            raise serializers.ValidationError('Elige un juego del catálogo.')
        return value


class LeaveRoomSerializer(serializers.Serializer):
    session_id = SessionIDField()


class PlayRoomSerializer(serializers.Serializer):
    session_id = SessionIDField()


class ReadyStateSerializer(serializers.Serializer):
    session_id = SessionIDField()
    is_ready = serializers.BooleanField()


class StartExpulsionVoteSerializer(serializers.Serializer):
    session_id = SessionIDField()
    target_ref = serializers.UUIDField()


class CastExpulsionBallotSerializer(serializers.Serializer):
    session_id = SessionIDField()
    choice = serializers.ChoiceField(choices=ExpulsionBallot.Choice.choices)


class ParticipantRosterSerializer(serializers.ModelSerializer):
    presence = serializers.SerializerMethodField()
    remaining_seconds = serializers.SerializerMethodField()
    participant_ref = serializers.UUIDField(source='public_id', read_only=True)

    class Meta:
        model = Participant
        fields = (
            'display_name',
            'participant_ref',
            'game_marker',
            'is_ready',
            'role',
            'presence',
            'remaining_seconds',
            'disconnected_at',
            'joined_at',
        )

    def to_representation(self, instance):
        """Read one entry's reconnect state at a single instant.

        ``presence`` and ``remaining_seconds`` are two views of the same
        deadline, so the clock is read once per entry: a presence that is still
        ``reconnecting`` can never be paired with a countdown that says the
        window is already over. The WebSocket snapshot does the same with one
        ``now`` for the entry it builds.
        """
        self.read_at = timezone.now()
        return super().to_representation(instance)

    def get_presence(self, participant):
        if participant.presence == Participant.Presence.RECONNECTING and grace_expired(
            participant.disconnected_at,
            self.read_at,
            RECONNECT_GRACE_SECONDS,
        ):
            return Participant.Presence.INACTIVE
        return participant.presence

    def get_remaining_seconds(self, participant):
        """The roster's copy of the countdown the match seats already carry.

        Only a participant still inside its reconnect window counts down; an
        ``online``, ``inactive`` or expired one has no window left and answers
        ``None`` (S8).
        """
        if participant.presence != Participant.Presence.RECONNECTING:
            return None
        return remaining_seconds(
            participant.disconnected_at,
            self.read_at,
            RECONNECT_GRACE_SECONDS,
        )


class RoomSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    expulsion_vote = serializers.SerializerMethodField()
    seat_limits = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = (
            'game_id',
            'status',
            'created_at',
            'updated_at',
            'participants',
            'expulsion_vote',
            'seat_limits',
        )

    def get_participants(self, room):
        participants = room.participants.filter(left_at__isnull=True).order_by(
            'joined_at', 'pk'
        )
        return ParticipantRosterSerializer(participants, many=True).data

    def get_expulsion_vote(self, room):
        vote = (
            ExpulsionVote.objects.filter(
                room=room,
                status=ExpulsionVote.Status.PENDING,
            )
            .select_related('target', 'initiated_by')
            .first()
        )
        return expulsion_vote_snapshot(vote) if vote is not None else None

    def get_seat_limits(self, room):
        return seat_limits(room.game_id)
