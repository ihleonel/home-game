"""Static data of the classic Monopoly board (S3).

Pure data: this module imports nothing from Django, DRF or Channels, holds no
rules and no mutable state. Every space is indexed by its position on the
circuit, starting at GO (index ``0``) and moving clockwise, which is the only
ordering the rules ever need. How those indexes are painted onto the 11x11
grid is a presentation concern of the interface increment, not board data.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Iterator


class SpaceKind(str, Enum):
    """What happens when a token stops on a space."""

    GO = 'go'
    STREET = 'street'
    RAILROAD = 'railroad'
    UTILITY = 'utility'
    CHANCE = 'chance'
    COMMUNITY_CHEST = 'community_chest'
    INCOME_TAX = 'income_tax'
    LUXURY_TAX = 'luxury_tax'
    JAIL = 'jail'
    FREE_PARKING = 'free_parking'
    GO_TO_JAIL = 'go_to_jail'


class ColorGroup(str, Enum):
    """The eight colour groups a street belongs to."""

    BROWN = 'brown'
    LIGHT_BLUE = 'light_blue'
    PINK = 'pink'
    ORANGE = 'orange'
    RED = 'red'
    YELLOW = 'yellow'
    GREEN = 'green'
    DARK_BLUE = 'dark_blue'


@dataclass(frozen=True)
class Space:
    """One space of the circuit.

    ``group`` is set only for a street: a railroad is a group of four for rent
    purposes, but that rule is a rent rule, not a colour group, so it must not
    be modelled as one.
    """

    index: int
    name: str
    kind: SpaceKind
    group: ColorGroup | None = None

    @property
    def is_purchasable(self) -> bool:
        """Whether the bank can sell this space to a player."""
        return self.kind in _PURCHASABLE_KINDS


_PURCHASABLE_KINDS = frozenset(
    (SpaceKind.STREET, SpaceKind.RAILROAD, SpaceKind.UTILITY)
)

# The circuit, from GO. This is the single source of the board: every rule
# reads it, and the board test pins it against the normative table of S3.
BOARD: tuple[Space, ...] = (
    Space(0, 'GO', SpaceKind.GO),
    Space(1, 'Avenida Mediterráneo', SpaceKind.STREET, ColorGroup.BROWN),
    Space(2, 'Community Chest', SpaceKind.COMMUNITY_CHEST),
    Space(3, 'Avenida Báltica', SpaceKind.STREET, ColorGroup.BROWN),
    Space(4, 'Income Tax', SpaceKind.INCOME_TAX),
    Space(5, 'Ferrocarril Reading', SpaceKind.RAILROAD),
    Space(6, 'Avenida Oriental', SpaceKind.STREET, ColorGroup.LIGHT_BLUE),
    Space(7, 'Chance', SpaceKind.CHANCE),
    Space(8, 'Avenida Vermont', SpaceKind.STREET, ColorGroup.LIGHT_BLUE),
    Space(9, 'Avenida Connecticut', SpaceKind.STREET, ColorGroup.LIGHT_BLUE),
    Space(10, 'Cárcel / Solo visitando', SpaceKind.JAIL),
    Space(11, 'St. Charles Place', SpaceKind.STREET, ColorGroup.PINK),
    Space(12, 'Compañía Eléctrica', SpaceKind.UTILITY),
    Space(13, 'Avenida States', SpaceKind.STREET, ColorGroup.PINK),
    Space(14, 'Avenida Virginia', SpaceKind.STREET, ColorGroup.PINK),
    Space(15, 'Ferrocarril Pennsylvania', SpaceKind.RAILROAD),
    Space(16, 'St. James Place', SpaceKind.STREET, ColorGroup.ORANGE),
    Space(17, 'Community Chest', SpaceKind.COMMUNITY_CHEST),
    Space(18, 'Avenida Tennessee', SpaceKind.STREET, ColorGroup.ORANGE),
    Space(19, 'Avenida New York', SpaceKind.STREET, ColorGroup.ORANGE),
    Space(20, 'Free Parking', SpaceKind.FREE_PARKING),
    Space(21, 'Avenida Kentucky', SpaceKind.STREET, ColorGroup.RED),
    Space(22, 'Chance', SpaceKind.CHANCE),
    Space(23, 'Avenida Indiana', SpaceKind.STREET, ColorGroup.RED),
    Space(24, 'Avenida Illinois', SpaceKind.STREET, ColorGroup.RED),
    Space(25, 'Ferrocarril B. & O.', SpaceKind.RAILROAD),
    Space(26, 'Avenida Atlantic', SpaceKind.STREET, ColorGroup.YELLOW),
    Space(27, 'Avenida Ventnor', SpaceKind.STREET, ColorGroup.YELLOW),
    Space(28, 'Water Works', SpaceKind.UTILITY),
    Space(29, 'Marvin Gardens', SpaceKind.STREET, ColorGroup.YELLOW),
    Space(30, 'Go to Jail', SpaceKind.GO_TO_JAIL),
    Space(31, 'Avenida Pacific', SpaceKind.STREET, ColorGroup.GREEN),
    Space(32, 'Avenida North Carolina', SpaceKind.STREET, ColorGroup.GREEN),
    Space(33, 'Community Chest', SpaceKind.COMMUNITY_CHEST),
    Space(34, 'Avenida Pennsylvania', SpaceKind.STREET, ColorGroup.GREEN),
    Space(35, 'Ferrocarril Short Line', SpaceKind.RAILROAD),
    Space(36, 'Chance', SpaceKind.CHANCE),
    Space(37, 'Park Place', SpaceKind.STREET, ColorGroup.DARK_BLUE),
    Space(38, 'Luxury Tax', SpaceKind.LUXURY_TAX),
    Space(39, 'Boardwalk', SpaceKind.STREET, ColorGroup.DARK_BLUE),
)

BOARD_SIZE = len(BOARD)

GO_INDEX = 0
INCOME_TAX_INDEX = 4
JAIL_INDEX = 10
GO_TO_JAIL_INDEX = 30
LUXURY_TAX_INDEX = 38

RAILROAD_INDEXES: tuple[int, ...] = tuple(
    space.index for space in BOARD if space.kind is SpaceKind.RAILROAD
)
UTILITY_INDEXES: tuple[int, ...] = tuple(
    space.index for space in BOARD if space.kind is SpaceKind.UTILITY
)
STREET_INDEXES: tuple[int, ...] = tuple(
    space.index for space in BOARD if space.kind is SpaceKind.STREET
)
PURCHASABLE_INDEXES: tuple[int, ...] = tuple(
    space.index for space in BOARD if space.is_purchasable
)

_GROUP_STREETS: dict[ColorGroup, tuple[int, ...]] = {
    group: tuple(space.index for space in BOARD if space.group is group)
    for group in ColorGroup
}


def space_at(index: int) -> Space:
    """Return the space at ``index``.

    Raises ``ValueError`` for an index outside the circuit instead of letting
    an ``IndexError`` from a negative position silently read the board from the
    wrong end.
    """
    if not 0 <= index < BOARD_SIZE:
        raise ValueError(f'space index out of the board: {index!r}')
    return BOARD[index]


def spaces_of_kind(kind: SpaceKind) -> tuple[Space, ...]:
    """Return every space of ``kind``, in circuit order."""
    return tuple(space for space in BOARD if space.kind is kind)


def street_indexes(group: ColorGroup) -> tuple[int, ...]:
    """Return the street indexes of ``group``, in circuit order."""
    return _GROUP_STREETS[group]


def group_of(index: int) -> ColorGroup | None:
    """Return the colour group of the street at ``index``, or ``None``."""
    return space_at(index).group


def indexes_of_kind(kind: SpaceKind) -> Iterator[int]:
    """Yield the indexes of every space of ``kind``, in circuit order."""
    for space in BOARD:
        if space.kind is kind:
            yield space.index
