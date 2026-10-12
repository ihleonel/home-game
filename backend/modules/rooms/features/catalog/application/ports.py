from typing import Protocol


class CatalogReader(Protocol):
    def list_games(self): ...
