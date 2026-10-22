"""Fidelity tests for the static ``monopoly`` deed economy (S4).

The 22 street deeds are spelled out literally, index by index, so a change to
``deeds.DEEDS`` alone can never rewrite the expectation. ``SimpleTestCase``
only provides the runner: the data module is pure and needs no database.
"""

from django.test import SimpleTestCase

from modules.games.monopoly import board, deeds

# ``(index, price, base_rent, set_rent, house_rents, hotel_rent, house_cost,
# mortgage)`` for each of the 22 streets, in circuit order. This table is the
# normative deed economy of S4; it is intentionally literal.
_EXPECTED = (
    (1, 60, 2, 4, (10, 30, 90, 160), 250, 50, 30),
    (3, 60, 4, 8, (20, 60, 180, 320), 450, 50, 30),
    (6, 100, 6, 12, (30, 90, 270, 400), 550, 50, 50),
    (8, 100, 6, 12, (30, 90, 270, 400), 550, 50, 50),
    (9, 120, 8, 16, (40, 100, 300, 450), 600, 50, 60),
    (11, 140, 10, 20, (50, 150, 450, 625), 750, 100, 70),
    (13, 140, 10, 20, (50, 150, 450, 625), 750, 100, 70),
    (14, 160, 12, 24, (60, 180, 500, 700), 900, 100, 80),
    (16, 180, 14, 28, (70, 200, 550, 750), 950, 100, 90),
    (18, 180, 14, 28, (70, 200, 550, 750), 950, 100, 90),
    (19, 200, 16, 32, (80, 220, 600, 800), 1000, 100, 100),
    (21, 220, 18, 36, (90, 250, 700, 875), 1050, 150, 110),
    (23, 220, 18, 36, (90, 250, 700, 875), 1050, 150, 110),
    (24, 240, 20, 40, (100, 300, 750, 925), 1100, 150, 120),
    (26, 260, 22, 44, (110, 330, 800, 975), 1150, 150, 130),
    (27, 260, 22, 44, (110, 330, 800, 975), 1150, 150, 130),
    (29, 280, 24, 48, (120, 360, 850, 1025), 1200, 150, 140),
    (31, 300, 26, 52, (130, 390, 900, 1100), 1275, 200, 150),
    (32, 300, 26, 52, (130, 390, 900, 1100), 1275, 200, 150),
    (34, 320, 28, 56, (150, 450, 1000, 1200), 1400, 200, 160),
    (37, 350, 35, 70, (175, 500, 1100, 1300), 1500, 200, 175),
    (39, 400, 50, 100, (200, 600, 1400, 1700), 2000, 200, 200),
)

# ``group -> printed price total`` (S4) is the cheapest checksum that catches a
# wrong price anywhere in the table.
_GROUP_TOTALS = (
    ('brown', 120),
    ('light_blue', 320),
    ('pink', 440),
    ('orange', 560),
    ('red', 680),
    ('yellow', 800),
    ('green', 920),
    ('dark_blue', 750),
)

# ``group -> house cost``; every street of a group shares it.
_GROUP_HOUSE_COSTS = (
    ('brown', 50),
    ('light_blue', 50),
    ('pink', 100),
    ('orange', 100),
    ('red', 150),
    ('yellow', 150),
    ('green', 200),
    ('dark_blue', 200),
)


class MonopolyDeedTests(SimpleTestCase):
    def test_street_deeds_match_the_normative_table(self):
        """Every street deed, field by field, against S4."""
        actual = tuple(
            (
                deed.index,
                deed.price,
                deed.base_rent,
                deed.set_rent,
                deed.house_rents,
                deed.hotel_rent,
                deed.house_cost,
                deed.mortgage,
            )
            for deed in deeds.street_deeds()
        )
        self.assertEqual(actual, _EXPECTED)

    def test_deeds_and_board_streets_are_the_same_set(self):
        """A street without a deed, or a deed without a street, is a data bug."""
        self.assertEqual(
            tuple(deed.index for deed in deeds.street_deeds()),
            board.STREET_INDEXES,
        )
        for index in board.STREET_INDEXES:
            with self.subTest(index=index):
                self.assertEqual(deeds.deed_for(index).index, index)

    def test_set_rent_is_twice_the_base_rent(self):
        """The complete-group rent is defined as double the unimproved rent."""
        for deed in deeds.street_deeds():
            with self.subTest(index=deed.index):
                self.assertEqual(deed.set_rent, 2 * deed.base_rent)

    def test_group_purchase_totals(self):
        """Each group's streets add up to the printed total of S4."""
        for group, total in _GROUP_TOTALS:
            with self.subTest(group=group):
                indexes = board.street_indexes(board.ColorGroup(group))
                self.assertEqual(
                    sum(deeds.deed_for(index).price for index in indexes), total
                )

    def test_house_cost_follows_the_colour_group(self):
        """Every street of a group shares the group's building cost."""
        for group, cost in _GROUP_HOUSE_COSTS:
            with self.subTest(group=group):
                for index in board.street_indexes(board.ColorGroup(group)):
                    self.assertEqual(deeds.deed_for(index).house_cost, cost)

    def test_rent_of_a_street_by_development_level(self):
        """Level 0 pays the base rent, a hotel pays the hotel rent."""
        deed = deeds.deed_for(1)
        self.assertEqual(deed.rent_for_level(0), 2)
        self.assertEqual(deed.rent_for_level(1), 10)
        self.assertEqual(deed.rent_for_level(4), 160)
        self.assertEqual(deed.rent_for_level(5), 250)

    def test_invalid_development_level_rejected(self):
        """A level outside 0..5 has no rent and must not silently pay one."""
        deed = deeds.deed_for(1)
        for level in (-1, 6):
            with self.subTest(level=level):
                with self.assertRaises(ValueError):
                    deed.rent_for_level(level)

    def test_development_cost_is_the_house_cost_times_the_level(self):
        """A level costs one printed house cost per level, the hotel included."""
        for deed in deeds.street_deeds():
            with self.subTest(index=deed.index):
                for level in range(0, deeds.HOTEL_LEVEL + 1):
                    self.assertEqual(
                        deeds.development_cost(deed, level), deed.house_cost * level
                    )

    def test_a_hotel_is_worth_five_houses(self):
        """A hotel costs five house payments: four houses plus the hotel (S5)."""
        for deed in deeds.street_deeds():
            with self.subTest(index=deed.index):
                self.assertEqual(
                    deeds.development_cost(deed, deeds.HOTEL_LEVEL),
                    5 * deed.house_cost,
                )

    def test_development_cost_rejects_a_level_off_the_scale(self):
        """A level outside 0..5 has no cost and must not silently price one."""
        deed = deeds.deed_for(1)
        for level in (-1, deeds.HOTEL_LEVEL + 1):
            with self.subTest(level=level):
                with self.assertRaises(ValueError):
                    deeds.development_cost(deed, level)

    def test_sell_back_is_half_the_house_cost(self):
        """Every printed house cost is even, so its half is a whole dollar."""
        for deed in deeds.street_deeds():
            with self.subTest(index=deed.index):
                self.assertEqual(deeds.sell_back(deed), deed.house_cost // 2)

    def test_selling_level_by_level_equals_half_the_development_cost(self):
        """The S5 invariant: selling each level refunds half the total cost."""
        for deed in deeds.street_deeds():
            for level in range(1, deeds.HOTEL_LEVEL + 1):
                with self.subTest(index=deed.index, level=level):
                    self.assertEqual(
                        sum(deeds.sell_back(deed) for _ in range(level)),
                        deeds.development_cost(deed, level) // 2,
                    )

    def test_railroad_economy(self):
        """A railroad costs $200, mortgages for $100 and scales by count owned."""
        self.assertEqual(deeds.RAILROAD_PRICE, 200)
        self.assertEqual(deeds.RAILROAD_MORTGAGE, 100)
        self.assertEqual(deeds.RAILROAD_RENTS, (25, 50, 100, 200))
        for index in board.RAILROAD_INDEXES:
            with self.subTest(index=index):
                self.assertEqual(deeds.purchase_price(index), 200)
                self.assertEqual(deeds.mortgage_value(index), 100)

    def test_utility_economy(self):
        """A utility costs $150, mortgages for $75 and pays a dice multiple."""
        self.assertEqual(deeds.UTILITY_PRICE, 150)
        self.assertEqual(deeds.UTILITY_MORTGAGE, 75)
        self.assertEqual(deeds.UTILITY_DICE_MULTIPLIERS, (4, 10))
        for index in board.UTILITY_INDEXES:
            with self.subTest(index=index):
                self.assertEqual(deeds.purchase_price(index), 150)
                self.assertEqual(deeds.mortgage_value(index), 75)

    def test_purchase_price_covers_every_purchasable_space(self):
        """Every purchasable space has a printed price, and nothing else does."""
        for index in board.PURCHASABLE_INDEXES:
            with self.subTest(index=index):
                self.assertGreater(deeds.purchase_price(index), 0)
                self.assertGreater(deeds.mortgage_value(index), 0)
        for index, space in enumerate(board.BOARD):
            if space.is_purchasable:
                continue
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    deeds.purchase_price(index)
                with self.assertRaises(ValueError):
                    deeds.mortgage_value(index)
                with self.assertRaises(ValueError):
                    deeds.deed_for(index)

    def test_mortgage_lift_cost_is_the_mortgage_plus_ten_percent_rounded_up(self):
        """The S4 helper: value + ceiling(value / 10), for every purchasable space."""
        cases = (
            (1, 30, 33),
            (5, 100, 110),
            (12, 75, 83),
            (37, 175, 193),
            (39, 200, 220),
        )
        for index, mortgage, expected in cases:
            with self.subTest(index=index):
                self.assertEqual(deeds.mortgage_value(index), mortgage)
                self.assertEqual(deeds.mortgage_lift_cost(index), expected)
        for index in board.PURCHASABLE_INDEXES:
            with self.subTest(index=index):
                interest = (
                    deeds.mortgage_lift_cost(index) - deeds.mortgage_value(index)
                )
                self.assertEqual(
                    interest, -(-deeds.mortgage_value(index) // 10)
                )
