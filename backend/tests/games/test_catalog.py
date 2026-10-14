"""Catalog endpoint tests for the games module (FRG-07).

``/api/games/`` must serve exactly the production registry so the deleted
placeholder games can never come back through the API, while preserving the
DTO shape the frontend already consumes:
``{'id', 'label', 'description', 'markers': ({'id', 'label'}, ...)}``.
"""

from rest_framework import status as http_status
from rest_framework.test import APITestCase

from modules.games.composition import GAME_REGISTRY


def _normalized(games):
    """Reduce a catalog to plain tuples so JSON list/tuple rendering cannot lie."""
    return tuple(
        (
            game['id'],
            game['label'],
            game['description'],
            tuple((marker['id'], marker['label']) for marker in game['markers']),
        )
        for game in games
    )


class GameCatalogApiTests(APITestCase):
    def get_catalog(self):
        response = self.client.get('/api/games/')

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        return response.data

    def test_catalog_serves_exactly_the_registered_games_with_their_seat_options(self):
        catalog = self.get_catalog()

        self.assertEqual(_normalized(catalog), _normalized(GAME_REGISTRY.list_games()))
        self.assertEqual([game['id'] for game in catalog], ['duelo'])
        self.assertEqual(
            [
                (marker['id'], marker['label'])
                for marker in catalog[0]['markers']
            ],
            [
                ('guante-rojo', 'Guante rojo'),
                ('guante-azul', 'Guante azul'),
                ('guante-verde', 'Guante verde'),
            ],
        )

    def test_catalog_dto_has_exactly_the_four_expected_keys(self):
        for game in self.get_catalog():
            self.assertEqual(set(game), {'id', 'label', 'description', 'markers'})

    def test_catalog_markers_are_id_label_maps(self):
        for game in self.get_catalog():
            self.assertTrue(game['markers'])
            for marker in game['markers']:
                self.assertEqual(set(marker), {'id', 'label'})

    def test_catalog_served_ids_equal_the_registry_ids(self):
        catalog = self.get_catalog()

        self.assertEqual(
            [game['id'] for game in catalog],
            [game['id'] for game in GAME_REGISTRY.list_games()],
        )
