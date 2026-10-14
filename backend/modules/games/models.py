"""Persistence models for matches of a game.

``Match.state`` is the authoritative versioned snapshot of a match: the runtime
reads it, advances it and writes it back under ``Match.version``, which acts as
the optimistic-concurrency token. ``MatchAction`` is the append-only audit and
replay record of the actions that produced those snapshots; it is never updated.

Game rules are imported lazily through the ``games`` registry and the room and
participant references are lazy string foreign keys, so this module never
imports ``modules.rooms`` at module level.
"""

import uuid

from django.db import models


class Match(models.Model):
    """One playable instance of a game inside a room."""

    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'In progress'
        FINISHED = 'finished', 'Finished'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    room = models.ForeignKey(
        'rooms.Room',
        on_delete=models.CASCADE,
        related_name='matches',
    )
    game_id = models.SlugField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    version = models.PositiveIntegerField(default=0)
    state = models.JSONField(default=dict)
    winner_seat = models.CharField(max_length=32, blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('room',),
                condition=models.Q(status='in_progress'),
                name='one_active_match_per_room',
            ),
        ]

    def __str__(self):
        return f'{self.game_id} ({self.status})'


class MatchSeat(models.Model):
    """A seat of a match bound to the room participant that occupies it."""

    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='seats',
    )
    index = models.PositiveSmallIntegerField()
    seat_id = models.CharField(max_length=32)
    participant = models.ForeignKey(
        'rooms.Participant',
        on_delete=models.CASCADE,
        related_name='match_seats',
    )
    badge = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('match', 'index'),
                name='unique_seat_index_per_match',
            ),
            models.UniqueConstraint(
                fields=('match', 'seat_id'),
                name='unique_seat_id_per_match',
            ),
            models.UniqueConstraint(
                fields=('match', 'participant'),
                name='unique_participant_per_match',
            ),
        ]

    def __str__(self):
        return f'{self.seat_id} @ {self.index}'


class MatchAction(models.Model):
    """Append-only audit and replay record of a match action.

    ``Match.state`` is the authoritative versioned snapshot; this log is the
    immutable history of the actions that produced it.
    """

    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='actions',
    )
    sequence = models.PositiveIntegerField()
    seat_id = models.CharField(max_length=32)
    action_name = models.CharField(max_length=32)
    action_value = models.CharField(max_length=64, blank=True, default='')
    version = models.PositiveIntegerField()
    facts = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('match', 'sequence'),
                name='unique_match_sequence',
            ),
        ]

    def __str__(self):
        return f'{self.match_id}:{self.sequence} {self.action_name}'
