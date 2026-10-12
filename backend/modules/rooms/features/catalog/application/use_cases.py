from .ports import CatalogReader


def list_games(catalog: CatalogReader):
    return catalog.list_games()
