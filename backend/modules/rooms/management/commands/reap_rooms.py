"""Management command that reaps ghost memberships and rooms.

Safe to run from a separate process while a server is live: staleness is
derived from the persisted ``presence`` and ``disconnected_at`` columns, never
from the in-process connection registry, so this sweep does not depend on
sharing memory with the sockets.

It also resolves seats already abandoned in a running match before reaping, so
a process restart in the middle of the reconnect grace window -- which loses
the in-process timer -- does not leave the match ``in_progress`` and the room
unreapable.

``--startup`` selects the presence-agnostic ``STARTUP`` policy instead of the
reconnect grace window because nobody can hold a socket to a process that has
just started; it is meant to run once before the server accepts connections.
"""

from django.core.management.base import BaseCommand

from modules.games.interfaces.match_abandon import abandon_expired_seats
from modules.rooms.features.reaping.domain.rules import GRACE, STARTUP
from modules.rooms.interfaces.composition import compose_room_dependencies


class Command(BaseCommand):
    help = (
        'Reap ghost memberships and rooms left behind by disconnected '
        'participants, resolving the seats they abandoned in a running match.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--startup',
            action='store_true',
            help=(
                'Reap every non-left membership, whatever its presence. Safe at '
                'boot because nobody can hold a socket to a process that has '
                'just started.'
            ),
        )

    def handle(self, *args, **options):
        # Resolve abandoned seats before reaping: finishing the match is what
        # unblocks the room so the reap below can clean its ghost membership.
        sweep = abandon_expired_seats()
        # Going through the composed service keeps the wiring in one place;
        # --startup only selects the policy, it does not bypass the use case.
        policy = STARTUP if options['startup'] else GRACE
        outcome = compose_room_dependencies().reaping.reap(policy=policy)
        self.stdout.write(
            self.style.SUCCESS(
                f'Reaped participants: {outcome.participants_removed}, '
                f'rooms touched: {outcome.rooms_reaped}, '
                f'rooms deleted: {outcome.rooms_deleted}, '
                f'abandoned seats: {sweep.seats_resolved}.'
            )
        )
