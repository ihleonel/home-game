import uuid

from django.db import models


class Room(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'

    game_id = models.SlugField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('status',),
                condition=models.Q(status='active'),
                name='one_active_room',
            ),
            models.CheckConstraint(
                condition=models.Q(status='active'),
                name='room_active_only',
            ),
        ]

    def __str__(self):
        return f'{self.game_id} ({self.status})'


class Participant(models.Model):
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    session_id = models.UUIDField(default=uuid.uuid4)
    display_name = models.CharField(max_length=80)
    game_marker = models.CharField(max_length=64)
    is_ready = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('room', 'session_id'),
                name='unique_room_session',
            ),
        ]

    def __str__(self):
        return self.display_name
