"""Compatibility exports for the process-local presence connection registry."""

from .features.presence.infrastructure.connections import (
    has_room_connection,
    register_connection,
    unregister_connection,
)

__all__ = ('has_room_connection', 'register_connection', 'unregister_connection')
