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


class MissingParticipantIdentity(Exception):
    def __init__(self, fields):
        self.fields = fields
