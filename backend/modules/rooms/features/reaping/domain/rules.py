from datetime import timedelta


def staleness_cutoff(now, grace_seconds):
    return now - timedelta(seconds=grace_seconds)


def is_stale(presence, disconnected_at, cutoff):
    return (
        presence in ('reconnecting', 'inactive')
        and disconnected_at is not None
        and disconnected_at <= cutoff
    )


def reap_changes(left_at):
    # Clearing is_ready is required: participant_for_session_for_update does not
    # filter left_at, so a rejoining session would otherwise come back ready.
    return (
        ('left_at', left_at),
        ('presence', 'offline'),
        ('disconnected_at', None),
        ('is_ready', False),
    )
