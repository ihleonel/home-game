"""Fidelity tests for the static ``monopoly`` board data (S3).

The expected board is spelled out literally, index by index, so a change to
``board.BOARD`` alone can never rewrite the expectation. ``SimpleTestCase``
only provides the runner: the data module is pure and needs no database.
"""

from django.test import SimpleTestCase

from modules.games.monopoly import board

# ``(name, kind, group)`` for each of the 40 spaces, in circuit order from GO.
# This table is the normative board of S3, transcribed from the classic U.S.
# board; it is intentionally literal.
_EXPECTED = (
    ('GO', 'go', None),
    ('Avenida Mediterráneo', 'street', 'brown'),
    ('Community Chest', 'community_chest', None),
    ('Avenida Báltica', 'street', 'brown'),
    ('Income Tax', 'income_tax', None),
    ('Ferrocarril Reading', 'railroad', None),
    ('Avenida Oriental', 'street', 'light_blue'),
    ('Chance', 'chance', None),
    ('Avenida Vermont', 'street', 'light_blue'),
    ('Avenida Connecticut', 'street', 'light_blue'),
    ('Cárcel / Solo visitando', 'jail', None),
    ('St. Charles Place', 'street', 'pink'),
    ('Compañía Eléctrica', 'utility', None),
    ('Avenida States', 'street', 'pink'),
    ('Avenida Virginia', 'street', 'pink'),
    ('Ferrocarril Pennsylvania', 'railroad', None),
    ('St. James Place', 'street', 'orange'),
    ('Community Chest', 'community_chest', None),
    ('Avenida Tennessee', 'street', 'orange'),
    ('Avenida New York', 'street', 'orange'),
    ('Free Parking', 'free_parking', None),
    ('Avenida Kentucky', 'street', 'red'),
    ('Chance', 'chance', None),
    ('Avenida Indiana', 'street', 'red'),
    ('Avenida Illinois', 'street', 'red'),
    ('Ferrocarril B. & O.', 'railroad', None),
    ('Avenida Atlantic', 'street', 'yellow'),
    ('Avenida Ventnor', 'street', 'yellow'),
    ('Water Works', 'utility', None),
    ('Marvin Gardens', 'street', 'yellow'),
    ('Go to Jail', 'go_to_jail', None),
    ('Avenida Pacific', 'street', 'green'),
    ('Avenida North Carolina', 'street', 'green'),
    ('Community Chest', 'community_chest', None),
    ('Avenida Pennsylvania', 'street', 'green'),
    ('Ferrocarril Short Line', 'railroad', None),
    ('Chance', 'chance', None),
    ('Park Place', 'street', 'dark_blue'),
    ('Luxury Tax', 'luxury_tax', None),
    ('Boardwalk', 'street', 'dark_blue'),
)

# ``group -> streets`` in circuit order, for the eight colour groups of S4.
_EXPECTED_GROUPS = (
    ('brown', (1, 3)),
    ('light_blue', (6, 8, 9)),
    ('pink', (11, 13, 14)),
    ('orange', (16, 18, 19)),
    ('red', (21, 23, 24)),
    ('yellow', (26, 27, 29)),
    ('green', (31, 32, 34)),
    ('dark_blue', (37, 39)),
)

_KIND_COUNTS = (
    ('street', 22),
    ('railroad', 4),
    ('utility', 2),
    ('chance', 3),
    ('community_chest', 3),
    ('income_tax', 1),
    ('luxury_tax', 1),
    ('go', 1),
    ('jail', 1),
    ('free_parking', 1),
    ('go_to_jail', 1),
)


class MonopolyBoardTests(SimpleTestCase):
    def test_board_matches_the_normative_table(self):
        """The 40 spaces, in order, with their name, kind and colour group."""
        self.assertEqual(len(board.BOARD), 40)
        self.assertEqual(board.BOARD_SIZE, 40)
        actual = tuple(
            (space.index, space.name, space.kind.value, _group_value(space.group))
            for space in board.BOARD
        )
        expected = tuple(
            (index, name, kind, group)
            for index, (name, kind, group) in enumerate(_EXPECTED)
        )
        self.assertEqual(actual, expected)

    def test_indexes_are_contiguous_and_start_at_go(self):
        """The circuit is a contiguous 0..39 run that starts at GO."""
        self.assertEqual(
            tuple(space.index for space in board.BOARD), tuple(range(40))
        )
        self.assertEqual(board.BOARD[board.GO_INDEX].kind, board.SpaceKind.GO)
        self.assertEqual(board.GO_INDEX, 0)

    def test_landmark_indexes(self):
        """The board constants used by the rules point at the right spaces."""
        self.assertEqual(
            board.BOARD[board.JAIL_INDEX].kind, board.SpaceKind.JAIL
        )
        self.assertEqual(
            board.BOARD[board.INCOME_TAX_INDEX].kind, board.SpaceKind.INCOME_TAX
        )
        self.assertEqual(
            board.BOARD[board.LUXURY_TAX_INDEX].kind, board.SpaceKind.LUXURY_TAX
        )
        self.assertEqual(
            board.BOARD[board.GO_TO_JAIL_INDEX].kind, board.SpaceKind.GO_TO_JAIL
        )
        self.assertEqual((board.JAIL_INDEX, board.INCOME_TAX_INDEX), (10, 4))
        self.assertEqual((board.LUXURY_TAX_INDEX, board.GO_TO_JAIL_INDEX), (38, 30))

    def test_composition_is_the_classic_one(self):
        """Every kind appears exactly as many times as the classic board does."""
        for kind, count in _KIND_COUNTS:
            with self.subTest(kind=kind):
                self.assertEqual(
                    len(board.spaces_of_kind(board.SpaceKind(kind))), count
                )

    def test_purchasable_spaces_are_the_28_properties(self):
        """The purchasable set is 22 streets plus 4 railroads plus 2 utilities."""
        purchasable = tuple(
            space.index for space in board.BOARD if space.is_purchasable
        )
        expected = tuple(
            index
            for index, (_, kind, _) in enumerate(_EXPECTED)
            if kind in ('street', 'railroad', 'utility')
        )
        self.assertEqual(board.PURCHASABLE_INDEXES, expected)
        self.assertEqual(purchasable, expected)
        self.assertEqual(len(purchasable), 28)
        self.assertEqual(board.RAILROAD_INDEXES, (5, 15, 25, 35))
        self.assertEqual(board.UTILITY_INDEXES, (12, 28))

    def test_colour_groups_hold_their_streets(self):
        """Each group maps to its streets, in circuit order."""
        for group, indexes in _EXPECTED_GROUPS:
            with self.subTest(group=group):
                self.assertEqual(
                    board.street_indexes(board.ColorGroup(group)), indexes
                )

    def test_every_street_belongs_to_a_group(self):
        """A street without a group would make the set rule unusable."""
        for space in board.spaces_of_kind(board.SpaceKind.STREET):
            with self.subTest(space=space.index):
                self.assertIsInstance(space.group, board.ColorGroup)

    def test_non_street_spaces_have_no_group(self):
        """Groups are a street concept only, so nothing else carries one."""
        for space in board.BOARD:
            if space.kind is board.SpaceKind.STREET:
                continue
            with self.subTest(space=space.index):
                self.assertIsNone(space.group)


def _group_value(group):
    """Read a colour group as its string value, or ``None``."""
    return None if group is None else group.value
