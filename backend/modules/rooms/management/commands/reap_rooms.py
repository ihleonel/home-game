"""Management command that reaps ghost memberships and rooms.

Safe to run from a separate process while a server is live: staleness is
derived from the persisted ``presence`` and ``disconnected_at`` columns, never
from the in-process connection registry, so this sweep does not depend on
sharing memory with the sockets.

``--startup`` ignores the reconnect grace window because nobody can hold a
socket to a process that has just started; it is meant to run once before the
server accepts connections.
"""

from django.core.management.base import BaseCommand

from modules.rooms.interfaces.composition import compose_room_dependencies


class Command(BaseCommand):
    help = (
        'Reap ghost memberships and rooms left behind by disconnected '
        'participants.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--startup',
            action='store_true',
            help=(
                'Ignore the reconnect grace window. Safe at boot because '
                'nobody can hold a socket to a process that has just started.'
            ),
        )

    def handle(self, *args, **options):
        # Going through the composed service keeps the wiring in one place;
        # --startup only overrides the grace window, it does not bypass the
        # use case.
        grace_seconds = 0 if options['startup'] else None
        outcome = compose_room_dependencies().reaping.reap(
            grace_seconds=grace_seconds
        )
        self.stdout.write(
            self.style.SUCCESS(
                f'Reaped participants: {outcome.participants_removed}, '
                f'rooms touched: {outcome.rooms_reaped}, '
                f'rooms deleted: {outcome.rooms_deleted}.'
            )
        )
