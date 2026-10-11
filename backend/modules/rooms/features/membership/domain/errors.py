class ActiveRoomGameConflict(Exception):
    pass


class RemovedSession(Exception):
    pass


class MissingParticipantIdentity(Exception):
    def __init__(self, fields):
        self.fields = fields
