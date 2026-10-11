"""Compatibility exports for the process-local room connection registry."""

from .infrastructure.connections import (
    has_room_connection,
    register_connection,
    unregister_connection,
)

__all__ = ('has_room_connection', 'register_connection', 'unregister_connection')
