"""Request serializers for the match REST endpoints (FRG-06).

Every serializer here is strict: the request may carry only the fields the
endpoint documents. A client-supplied ``participant_ref`` or ``game_id`` would
otherwise be silently ignored, and the task requires that an unvalidated
reference can never reach the store -- ``DjangoMatchStore.create`` resolves a
``participant_ref`` to a ``Participant`` row and raises a bare ``KeyError`` for
an unknown one.
"""

from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    """Serializer that rejects any field it does not declare.

    DRF's default behaviour is to drop unknown keys, which would let a client
    smuggle a ``participant_ref`` into the request without effect. Turning the
    drop into a validation error makes that attempt observable instead.
    """

    def to_internal_value(self, data):
        if hasattr(data, 'keys'):
            unknown = sorted(set(data.keys()) - set(self.fields))
            if unknown:
                raise serializers.ValidationError(
                    {
                        field: 'Este campo no está permitido.'
                        for field in unknown
                    }
                )
        return super().to_internal_value(data)


class SubmitActionSerializer(StrictSerializer):
    """``POST /api/matches/<match_ref>/actions/`` body."""

    session_id = serializers.UUIDField()
    action_name = serializers.CharField(max_length=32)
    action_value = serializers.CharField(
        max_length=64, required=False, allow_null=True
    )
    expected_version = serializers.IntegerField(min_value=0)


class MatchResyncSerializer(StrictSerializer):
    """``GET /api/matches/<match_ref>/`` query parameters."""

    session_id = serializers.UUIDField()
