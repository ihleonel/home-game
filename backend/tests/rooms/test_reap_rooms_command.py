"""Coverage for the ``reap_rooms`` maintenance command.

The command is exercised through ``call_command`` over real rows, so the
assertions cover the same composed ``RoomDependencies.reaping`` entry point the
adapters and the container startup chain use.
"""

import io
import uuid
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from modules.games.models import Match
from modules.rooms.constants import RECONNECT_GRACE_SECONDS
from modules.rooms.models import Participant, Room


def create_room(game_id='duelo'):
    return Room.objects.create(game_id=game_id)


def create_participant(
    room,
    *,
    presence=Participant.Presence.OFFLINE,
    disconnected_at=None,
    is_ready=False,
    left_at=None,
    display_name='Guest',
    session_id=None,
):
    return Participant.objects.create(
        room=room,
        session_id=session_id or uuid.uuid4(),
        display_name=display_name,
        game_marker='guante-rojo',
        presence=presence,
        disconnected_at=disconnected_at,
        is_ready=is_ready,
        left_at=left_at,
    )


def stale_moment():
    return timezone.now() - timedelta(seconds=RECONNECT_GRACE_SECONDS + 30)


def inside_grace_moment():
    return timezone.now() - timedelta(seconds=RECONNECT_GRACE_SECONDS - 5)


def age_participant(participant, *, updated_at):
    Participant.objects.filter(pk=participant.pk).update(updated_at=updated_at)
    participant.refresh_from_db()
    return participant


def run_command(*args):
    stdout = io.StringIO()
    call_command('reap_rooms', *args, stdout=stdout)
    return stdout.getvalue()


class ReapRoomsCommandTests(TestCase):
    def test_default_run_reaps_past_grace_and_spares_inside_grace(self):
        room = create_room()
        stale = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=stale_moment(),
            is_ready=True,
        )
        inside = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=inside_grace_moment(),
            is_ready=True,
            display_name='Inside',
        )

        output = run_command()

        stale.refresh_from_db()
        self.assertIsNotNone(stale.left_at)
        self.assertEqual(stale.presence, Participant.Presence.OFFLINE)
        self.assertIsNone(stale.disconnected_at)
        self.assertFalse(stale.is_ready)

        inside.refresh_from_db()
        self.assertIsNone(inside.left_at)
        self.assertEqual(inside.presence, Participant.Presence.RECONNECTING)
        self.assertTrue(inside.is_ready)

        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        self.assertIn('Reaped participants: 1', output)
        self.assertIn('rooms touched: 1', output)
        self.assertIn('rooms deleted: 0', output)

    def test_startup_run_reaps_every_non_left_membership_in_a_non_busy_room(self):
        room = create_room()
        inside = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=inside_grace_moment(),
            is_ready=True,
        )
        companion = create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            display_name='Companion',
        )

        output = run_command('--startup')

        # The startup sweep is presence-agnostic, so even the online companion
        # is a ghost; the emptied room and its members are gone.
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertFalse(
            Participant.objects.filter(pk__in=(inside.pk, companion.pk)).exists()
        )
        self.assertIn('Reaped participants: 2', output)
        self.assertIn('rooms touched: 1', output)
        self.assertIn('rooms deleted: 1', output)

    def test_default_run_reaps_a_never_socketed_offline_membership(self):
        # A membership posted over REST whose socket never opened is offline
        # with disconnected_at=NULL; it must still age out on the grace window.
        room = create_room()
        offline = age_participant(
            create_participant(room, presence=Participant.Presence.OFFLINE),
            updated_at=stale_moment(),
        )

        output = run_command()

        self.assertIn('Reaped participants: 1', output)
        self.assertIn('rooms touched: 1', output)
        self.assertIn('rooms deleted: 1', output)
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertFalse(Participant.objects.filter(pk=offline.pk).exists())

    def test_startup_run_reaps_a_presence_agnostic_membership_and_default_does_not(
        self,
    ):
        room = create_room()
        online = create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            display_name='Online',
        )

        default_output = run_command()
        online.refresh_from_db()
        self.assertIsNone(online.left_at)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        self.assertIn('Reaped participants: 0', default_output)

        startup_output = run_command('--startup')
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())
        self.assertFalse(Participant.objects.filter(pk=online.pk).exists())
        self.assertIn('Reaped participants: 1', startup_output)
        self.assertIn('rooms touched: 1', startup_output)
        self.assertIn('rooms deleted: 1', startup_output)

    def test_startup_run_is_idempotent_for_presence_agnostic_memberships(self):
        room = create_room()
        create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            display_name='Online',
        )

        first = run_command('--startup')
        second = run_command('--startup')

        self.assertIn('Reaped participants: 1', first)
        self.assertIn('Reaped participants: 0', second)
        self.assertIn('rooms deleted: 0', second)
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())

    def test_room_with_in_progress_match_keeps_its_participant_in_both_modes(self):
        room = create_room()
        ghost = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=stale_moment(),
            is_ready=True,
        )
        match = Match.objects.create(
            room=room,
            game_id='duelo',
            status=Match.Status.IN_PROGRESS,
        )

        default_output = run_command()
        startup_output = run_command('--startup')

        ghost.refresh_from_db()
        self.assertIsNone(ghost.left_at)
        self.assertEqual(ghost.presence, Participant.Presence.RECONNECTING)
        self.assertTrue(ghost.is_ready)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        self.assertTrue(Match.objects.filter(pk=match.pk).exists())
        for output in (default_output, startup_output):
            self.assertIn('Reaped participants: 0', output)
            self.assertIn('rooms touched: 0', output)
            self.assertIn('rooms deleted: 0', output)

    def test_emptied_room_is_deleted_in_both_modes(self):
        default_room = create_room('juego-default')
        create_participant(
            default_room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
        )
        startup_room = create_room('juego-startup')
        create_participant(
            startup_room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=inside_grace_moment(),
        )

        run_command()
        self.assertFalse(Room.objects.filter(pk=default_room.pk).exists())
        self.assertTrue(Room.objects.filter(pk=startup_room.pk).exists())

        run_command('--startup')
        self.assertFalse(Room.objects.filter(pk=startup_room.pk).exists())

    def test_default_run_twice_reports_no_further_work(self):
        room = create_room()
        ghost = create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=stale_moment(),
        )
        companion = create_participant(
            room,
            presence=Participant.Presence.ONLINE,
            display_name='Companion',
        )

        first = run_command()
        self.assertIn('Reaped participants: 1', first)
        second = run_command()

        self.assertIn('Reaped participants: 0', second)
        self.assertIn('rooms touched: 0', second)
        self.assertIn('rooms deleted: 0', second)
        ghost.refresh_from_db()
        self.assertIsNotNone(ghost.left_at)
        companion.refresh_from_db()
        self.assertIsNone(companion.left_at)

    def test_startup_run_twice_reports_no_further_work(self):
        room = create_room()
        create_participant(
            room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=inside_grace_moment(),
        )

        first = run_command('--startup')
        self.assertIn('Reaped participants: 1', first)
        second = run_command('--startup')

        self.assertIn('Reaped participants: 0', second)
        self.assertIn('rooms touched: 0', second)
        self.assertIn('rooms deleted: 0', second)
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())

    def test_summary_reports_the_counts_of_the_run(self):
        first_room = create_room('juego-uno')
        create_participant(
            first_room,
            presence=Participant.Presence.RECONNECTING,
            disconnected_at=stale_moment(),
        )
        second_room = create_room('juego-dos')
        create_participant(
            second_room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
        )
        create_participant(
            second_room,
            presence=Participant.Presence.INACTIVE,
            disconnected_at=stale_moment(),
            display_name='Second',
        )

        output = run_command()

        self.assertIn('Reaped participants: 3', output)
        self.assertIn('rooms touched: 2', output)
        self.assertIn('rooms deleted: 2', output)
        self.assertFalse(Room.objects.filter(pk=first_room.pk).exists())
        self.assertFalse(Room.objects.filter(pk=second_room.pk).exists())
