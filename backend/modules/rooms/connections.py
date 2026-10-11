from threading import RLock

_CONNECTIONS = {}
_CONNECTIONS_LOCK = RLock()


def register_connection(room_id, session_id, channel_name):
    key = (room_id, session_id)
    with _CONNECTIONS_LOCK:
        _CONNECTIONS.setdefault(key, set()).add(channel_name)


def unregister_connection(room_id, session_id, channel_name):
    key = (room_id, session_id)
    with _CONNECTIONS_LOCK:
        channels = _CONNECTIONS.get(key)
        if channels is None:
            return True
        channels.discard(channel_name)
        if channels:
            return False
        _CONNECTIONS.pop(key, None)
        return True


def has_room_connection(room_id, session_id):
    with _CONNECTIONS_LOCK:
        return bool(_CONNECTIONS.get((room_id, session_id)))
