class ActiveRoomNotFound(Exception):
    pass


class ActiveParticipantNotFound(Exception):
    pass


class SpectatorCannotBeReady(Exception):
    """A spectator has no seat to mark ready, so the action never applies."""
