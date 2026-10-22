"""Static deed economy of the classic Monopoly board (S4).

Pure data and lookups: this module imports nothing from Django, DRF or
Channels and never mutates anything. It answers the questions the rules ask
constantly -- what a space prints as its purchase price, what it prints as its
mortgage value, what the streets rent for, and what a development level costs
and returns -- and it answers them from one table, so a price cannot live in
two places and drift.

Only the classic 1999-2007 edition values are here (S2): Luxury Tax is $75 at
the board level and Income Tax offers $200 or 10 % of total worth.
"""

from dataclasses import dataclass

from . import board

# A street reaches its hotel at level 5 and holds at most four houses.
MAX_HOUSE_LEVEL = 4
HOTEL_LEVEL = 5

RAILROAD_PRICE = 200
RAILROAD_MORTGAGE = 100
# Rent by the number of railroads the owner holds, so index 0 is one railroad.
RAILROAD_RENTS = (25, 50, 100, 200)

UTILITY_PRICE = 150
UTILITY_MORTGAGE = 75
# Rent multiplier by the number of utilities the owner holds: 4x with one,
# 10x with both, applied to the dice roll that moved the payer.
UTILITY_DICE_MULTIPLIERS = (4, 10)


@dataclass(frozen=True)
class Deed:
    """The title deed of one street.

    ``set_rent`` is the unimproved rent an owner may charge once the whole
    colour group is held; it is stored rather than derived at read time so the
    printed rule is visible in the data. ``house_rents`` holds the rents for
    one to four houses, in order.
    """

    index: int
    price: int
    base_rent: int
    set_rent: int
    house_rents: tuple[int, int, int, int]
    hotel_rent: int
    house_cost: int
    mortgage: int

    def rent_for_level(self, level: int) -> int:
        """Return the rent printed for a development level.

        ``0`` is unimproved, ``1..4`` are houses and ``5`` is the hotel. The
        complete-group rent is **not** selected here: it belongs to the set
        rule, not to the level, and the caller applies it to an unimproved
        street whose owner holds the whole group. Raises ``ValueError`` for a
        level off the scale rather than paying a neighbouring level's rent.
        """
        if not 0 <= level <= HOTEL_LEVEL:
            raise ValueError(f'development level out of range: {level!r}')
        if level == 0:
            return self.base_rent
        if level == HOTEL_LEVEL:
            return self.hotel_rent
        return self.house_rents[level - 1]


# Keyed by the space index, so a deed is found by the space it belongs to.
_DEEDS = {
    deed.index: deed
    for deed in (
        Deed(1, 60, 2, 4, (10, 30, 90, 160), 250, 50, 30),
        Deed(3, 60, 4, 8, (20, 60, 180, 320), 450, 50, 30),
        Deed(6, 100, 6, 12, (30, 90, 270, 400), 550, 50, 50),
        Deed(8, 100, 6, 12, (30, 90, 270, 400), 550, 50, 50),
        Deed(9, 120, 8, 16, (40, 100, 300, 450), 600, 50, 60),
        Deed(11, 140, 10, 20, (50, 150, 450, 625), 750, 100, 70),
        Deed(13, 140, 10, 20, (50, 150, 450, 625), 750, 100, 70),
        Deed(14, 160, 12, 24, (60, 180, 500, 700), 900, 100, 80),
        Deed(16, 180, 14, 28, (70, 200, 550, 750), 950, 100, 90),
        Deed(18, 180, 14, 28, (70, 200, 550, 750), 950, 100, 90),
        Deed(19, 200, 16, 32, (80, 220, 600, 800), 1000, 100, 100),
        Deed(21, 220, 18, 36, (90, 250, 700, 875), 1050, 150, 110),
        Deed(23, 220, 18, 36, (90, 250, 700, 875), 1050, 150, 110),
        Deed(24, 240, 20, 40, (100, 300, 750, 925), 1100, 150, 120),
        Deed(26, 260, 22, 44, (110, 330, 800, 975), 1150, 150, 130),
        Deed(27, 260, 22, 44, (110, 330, 800, 975), 1150, 150, 130),
        Deed(29, 280, 24, 48, (120, 360, 850, 1025), 1200, 150, 140),
        Deed(31, 300, 26, 52, (130, 390, 900, 1100), 1275, 200, 150),
        Deed(32, 300, 26, 52, (130, 390, 900, 1100), 1275, 200, 150),
        Deed(34, 320, 28, 56, (150, 450, 1000, 1200), 1400, 200, 160),
        Deed(37, 350, 35, 70, (175, 500, 1100, 1300), 1500, 200, 175),
        Deed(39, 400, 50, 100, (200, 600, 1400, 1700), 2000, 200, 200),
    )
}

# Circuit order, which is the order every other module reads.
_STREET_DEEDS = tuple(_DEEDS[index] for index in board.STREET_INDEXES)


def street_deeds() -> tuple[Deed, ...]:
    """Return every street deed, in circuit order."""
    return _STREET_DEEDS


def deed_for(index: int) -> Deed:
    """Return the deed of the street at ``index``.

    Raises ``ValueError`` for a space that is not a street: a railroad and a
    utility are purchasable, but they have no title deed, and handing one back
    would let a caller build houses on Boardwalk's neighbours.
    """
    try:
        return _DEEDS[index]
    except KeyError:
        raise ValueError(f'space {index!r} has no street deed') from None


def is_street(index: int) -> bool:
    """Whether the space at ``index`` is a street with a deed."""
    return index in _DEEDS


def development_cost(deed: Deed, level: int) -> int:
    """Return what a development level is worth in printed house costs.

    Level 0 is bare land and costs nothing, levels 1 to 4 are that many houses
    and level 5 (the hotel) is worth **five** houses: the owner paid four
    houses plus the hotel price, and those four houses went back to the bank.
    This is the single place that decides the equivalence, so rent, tax and
    bankruptcy cannot disagree about it. Raises ``ValueError`` for a level off
    the scale.
    """
    if not 0 <= level <= HOTEL_LEVEL:
        raise ValueError(f'development level out of range: {level!r}')
    return deed.house_cost * level


def sell_back(deed: Deed) -> int:
    """Return what one level returns when sold back to the bank.

    The printed rule pays "one-half the price paid" for a house or a hotel,
    and every house cost on the board is even, so the half is a whole dollar.
    """
    return deed.house_cost // 2


def purchase_price(index: int) -> int:
    """Return the printed purchase price of a purchasable space.

    Raises ``ValueError`` when the space cannot be bought, so a caller cannot
    treat a tax space as free property.
    """
    space = board.space_at(index)
    if space.kind is board.SpaceKind.STREET:
        return deed_for(index).price
    if space.kind is board.SpaceKind.RAILROAD:
        return RAILROAD_PRICE
    if space.kind is board.SpaceKind.UTILITY:
        return UTILITY_PRICE
    raise ValueError(f'space {index!r} ({space.name}) is not purchasable')


def mortgage_value(index: int) -> int:
    """Return the printed mortgage value of a purchasable space.

    Raises ``ValueError`` when the space cannot be mortgaged.
    """
    space = board.space_at(index)
    if space.kind is board.SpaceKind.STREET:
        return deed_for(index).mortgage
    if space.kind is board.SpaceKind.RAILROAD:
        return RAILROAD_MORTGAGE
    if space.kind is board.SpaceKind.UTILITY:
        return UTILITY_MORTGAGE
    raise ValueError(f'space {index!r} ({space.name}) is not purchasable')


def mortgage_lift_cost(index: int) -> int:
    """Return what lifting a mortgage costs: the value plus 10 % interest (S4).

    The interest is ten percent of the printed mortgage value, rounded up to
    the whole dollar like the Income Tax of S10 of ``monopoly.md``. A caller
    that needs the interest alone subtracts :func:`mortgage_value`, which is
    the single place the two numbers are made to agree.
    """
    mortgage = mortgage_value(index)
    return mortgage + -(-mortgage // 10)
