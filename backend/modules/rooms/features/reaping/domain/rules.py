from datetime import timedelta

GRACE = 'grace'
STARTUP = 'startup'


def staleness_cutoff(now, grace_seconds):
    return now - timedelta(seconds=grace_seconds)


def is_stale(policy, presence, disconnected_at, updated_at, cutoff):
    if policy == STARTUP:
        # The startup sweep runs before the server accepts connections, so at
        # that moment every row is a ghost: nobody can hold a socket to a
        # process that has just started. The caller's left_at filter is the
        # only other condition.
        return True
    if presence in ('reconnecting', 'inactive'):
        return disconnected_at is not None and disconnected_at <= cutoff
    if presence == 'offline':
        # A membership created over REST whose socket never opens stays at
        # presence='offline' with disconnected_at=NULL. Age it out on the same
        # window, counted from its last update, so a fresh or revived arrival
        # keeps its window while a never-connected row is eventually removed.
        return updated_at is not None and updated_at <= cutoff
    # Anything else, including 'online', belongs to a live socket under the
    # grace policy.
    return False


def reap_changes(left_at):
    # Clearing is_ready is required: participant_for_session_for_update does not
    # filter left_at, so a rejoining session would otherwise come back ready.
    return (
        ('left_at', left_at),
        ('presence', 'offline'),
        ('disconnected_at', None),
        ('is_ready', False),
    )
