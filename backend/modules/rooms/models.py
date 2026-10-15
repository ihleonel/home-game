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
                fields=('game_id', 'status'),
                condition=models.Q(status='active'),
                name='one_active_room_per_game',
            ),
            models.CheckConstraint(
                condition=models.Q(status='active'),
                name='room_active_only',
            ),
        ]

    def __str__(self):
        return f'{self.game_id} ({self.status})'


class Participant(models.Model):
    class Presence(models.TextChoices):
        OFFLINE = 'offline', 'Offline'
        ONLINE = 'online', 'Online'
        RECONNECTING = 'reconnecting', 'Reconnecting'
        INACTIVE = 'inactive', 'Inactive'

    class Role(models.TextChoices):
        PLAYER = 'player', 'Player'
        SPECTATOR = 'spectator', 'Spectator'

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    session_id = models.UUIDField(default=uuid.uuid4)
    display_name = models.CharField(max_length=80)
    game_marker = models.CharField(max_length=64)
    is_ready = models.BooleanField(default=False)
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.PLAYER,
    )
    presence = models.CharField(
        max_length=16,
        choices=Presence.choices,
        default=Presence.OFFLINE,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    left_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('room', 'session_id'),
                name='unique_room_session',
            ),
        ]

    def __str__(self):
        return self.display_name


class ExpulsionVote(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='expulsion_votes',
    )
    target = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='expulsion_votes_as_target',
    )
    initiated_by = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='expulsion_votes_started',
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    resolution_reason = models.CharField(max_length=32, blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('room',),
                condition=models.Q(status='pending'),
                name='one_pending_room_vote',
            ),
        ]


class ExpulsionBallot(models.Model):
    class Choice(models.TextChoices):
        YES = 'yes', 'Yes'
        NO = 'no', 'No'

    vote = models.ForeignKey(
        ExpulsionVote,
        on_delete=models.CASCADE,
        related_name='ballots',
    )
    voter = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='expulsion_ballots',
    )
    choice = models.CharField(
        max_length=3,
        choices=Choice.choices,
        null=True,
        blank=True,
    )
    cast_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('vote', 'voter'),
                name='one_ballot_per_voter',
            ),
        ]
