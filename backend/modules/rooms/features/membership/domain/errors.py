class ActiveRoomGameConflict(Exception):
    pass


class ActiveRoomNotFound(Exception):
    pass


class ActiveRoomSelectionRequired(Exception):
    pass


class ActiveParticipantNotFound(Exception):
    pass


class RemovedSession(Exception):
    pass


class ReadyParticipantCannotLeave(Exception):
    pass


class MatchAlreadyStarted(Exception):
    """Seats are fixed once a match is in progress, so promotion is closed."""


class NoFreeSeat(Exception):
    """The room already holds the game's maximum number of players."""


class MissingParticipantIdentity(Exception):
    def __init__(self, fields):
        self.fields = fields
