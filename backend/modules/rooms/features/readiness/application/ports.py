from typing import Protocol


class ReadinessGateway(Protocol):
    def set_ready(self, data): ...
