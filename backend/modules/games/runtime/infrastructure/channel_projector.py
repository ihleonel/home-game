"""Channels-backed ``MatchProjector`` adapter: per-seat event projection.

The projector receives precomputed ``views`` keyed by ``seat_id`` (with a
``None`` public view) and never the match state, so a value one seat must not
see before the reveal cannot even be reached here. It fans the same event out
to one group per seat plus a public group, and emits a single state-free
signal to the room group so a client can learn that a match now exists without
leaking any seat's view into the shared room.

Group names are derived from the seat's ``index`` and never its ``seat_id``:
only the index is guaranteed to be unique and to stay inside the channel
layer's legal character set, so two seats can never collide and a seat group
can never collide with the public group.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from ....rooms.infrastructure.events import room_group_name

logger = logging.getLogger(__name__)


def match_public_group_name(match_ref):
    """Return the shared, state-free group for ``match_ref``."""
    return f'match_{match_ref}_public'


def match_seat_group_name(match_ref, seat_index):
    """Return the private group of one seat, keyed by its ``index``."""
    return f'match_{match_ref}_seat_{seat_index}'


class ChannelMatchProjector:
    """``MatchProjector`` port that fans each event out over a channel layer."""

    def __init__(self, channel_layer=None):
        self._channel_layer = channel_layer

    def _channel_layer_or_default(self):
        """Return the injected layer, else Channels' configured layer.

        The lookup is deferred to ``publish`` so a projector built at import
        time does not capture a layer before the app registry is ready.
        """
        if self._channel_layer is not None:
            return self._channel_layer
        return get_channel_layer()

    def publish(self, *, event, header, views, facts):
        """Send ``views`` to each seat's group, the public group and the room.

        A seat with no entry in ``views`` is skipped rather than sent a ``None``
        view, and the public send is skipped when ``views`` has no ``None`` key.
        ``match_started`` additionally signals the room group with a
        state-free message: the consumer only needs to learn that a match
        exists so it can subscribe to the match's own groups.

        ``publish`` runs only after the state transition has already
        committed, so a channel-layer failure must never escape it. Letting a
        raise propagate would (1) report an action that actually committed to
        the client as a failure, inviting a retry that then hits
        ``StaleVersion``, and (2) abort the fan-out on the first unreachable
        group, silencing every other seat (a nine-seat Poker game would lose
        eight views to one bad group). Each send is therefore isolated: a
        failure is logged and the remaining targets are still attempted, so
        the blast radius of a transport failure is one target, not the table.
        Do not remove the per-send handler.
        """
        channel_layer = self._channel_layer_or_default()
        if channel_layer is None:
            return

        send = async_to_sync(channel_layer.group_send)

        for seat in header.seats:
            if seat.seat_id not in views:
                continue
            group = match_seat_group_name(header.match_ref, seat.index)
            try:
                send(
                    group,
                    self._event_message(
                        event, header, views[seat.seat_id], facts
                    ),
                )
            except Exception:
                logger.exception(
                    'Unable to publish %s to channel group %s.', event, group
                )

        if None in views:
            group = match_public_group_name(header.match_ref)
            try:
                send(
                    group,
                    self._event_message(event, header, views[None], facts),
                )
            except Exception:
                logger.exception(
                    'Unable to publish %s to channel group %s.', event, group
                )

        if event == 'match_started':
            group = room_group_name(header.room_id)
            try:
                send(
                    group,
                    {
                        'type': 'match.started',
                        'match_ref': header.match_ref,
                        'version': header.version,
                    },
                )
            except Exception:
                logger.exception(
                    'Unable to publish %s to channel group %s.', event, group
                )

    @staticmethod
    def _event_message(event, header, view, facts):
        """Build the per-view message body sent to a seat or public group."""
        return {
            'type': 'game.event',
            'event': event,
            'match_ref': header.match_ref,
            'room_id': header.room_id,
            'version': header.version,
            'view': view,
            'facts': facts,
        }
