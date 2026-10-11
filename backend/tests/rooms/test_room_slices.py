from django.test import SimpleTestCase

from modules.rooms.catalog import GAMES, GAMES_BY_ID
from modules.rooms.features.catalog.application.use_cases import list_games
from modules.rooms.features.catalog.domain.catalog import contains_game, contains_marker
from modules.rooms.features.membership.domain.rules import (
    is_disconnected_presence,
    membership_change,
)
from modules.rooms.features.readiness.domain.rules import readiness_change


class CatalogSliceTests(SimpleTestCase):
    def test_static_catalog_is_owned_by_feature_and_compatibility_exports_are_stable(self):
        self.assertEqual(list(GAMES_BY_ID), [game['id'] for game in GAMES])
        self.assertTrue(contains_game(GAMES[0]['id']))
        self.assertTrue(contains_marker(GAMES[0]['id'], GAMES[0]['markers'][0]['id']))
        self.assertFalse(contains_marker(GAMES[0]['id'], GAMES[1]['markers'][0]['id']))

    def test_list_games_uses_catalog_port(self):
        catalog = _CatalogStub()

        self.assertEqual(list_games(catalog), catalog.games)


class MembershipDomainTests(SimpleTestCase):
    def test_rejoin_emits_join_event_and_resets_leave_and_presence_fields(self):
        change = membership_change(
            was_left=True,
            was_disconnected=True,
            current_display_name='Guest',
            current_game_marker='silver-leaf',
            data={'display_name': 'Guest Updated'},
        )

        self.assertEqual(change.event_name, 'player_joined')
        self.assertEqual(
            dict(change.updates),
            {
                'display_name': 'Guest Updated',
                'left_at': None,
                'presence': 'offline',
                'disconnected_at': None,
            },
        )

    def test_unchanged_active_membership_does_not_emit_an_event(self):
        change = membership_change(
            was_left=False,
            was_disconnected=False,
            current_display_name='Guest',
            current_game_marker='silver-leaf',
            data={'display_name': 'Guest', 'game_marker': 'silver-leaf'},
        )

        self.assertEqual(change.updates, ())
        self.assertIsNone(change.event_name)

    def test_only_reconnecting_and_inactive_presence_counts_as_disconnected(self):
        self.assertTrue(is_disconnected_presence('reconnecting'))
        self.assertTrue(is_disconnected_presence('inactive'))
        self.assertFalse(is_disconnected_presence('offline'))


class ReadinessDomainTests(SimpleTestCase):
    def test_change_distinguishes_requested_value_from_state_transition(self):
        self.assertEqual(readiness_change(False, True).value, True)
        self.assertTrue(readiness_change(False, True).changed)
        self.assertFalse(readiness_change(True, True).changed)


class _CatalogStub:
    games = ('game',)

    def list_games(self):
        return self.games
