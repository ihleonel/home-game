/**
 * Static data of the classic Monopoly board.
 *
 * This is the frontend copy of the normative table the backend owns in
 * ``modules/games/monopoly/board.py`` (S1 of ``monopoly-interface.md``): the
 * board is static, so it is duplicated here instead of travelling in every
 * match frame, and ``board.test.ts`` pins the same literal table the backend
 * test pins, so a wrong transcription fails on its own side.
 *
 * Every space is indexed by its position on the circuit, starting at GO
 * (index ``0``) and moving clockwise, which is the only ordering the rules
 * need. How those indexes are painted onto the 11x11 grid is ``grid.ts``'s job.
 */

export type SpaceKind =
  | 'go'
  | 'street'
  | 'railroad'
  | 'utility'
  | 'chance'
  | 'community_chest'
  | 'income_tax'
  | 'luxury_tax'
  | 'jail'
  | 'free_parking'
  | 'go_to_jail'

export type ColorGroup =
  | 'brown'
  | 'light_blue'
  | 'pink'
  | 'orange'
  | 'red'
  | 'yellow'
  | 'green'
  | 'dark_blue'

/**
 * One space of the circuit.
 *
 * ``group`` is set only for a street: a railroad is a group of four for rent
 * purposes, but that is a rent rule, not a colour group.
 */
export type Space = {
  index: number
  name: string
  kind: SpaceKind
  group: ColorGroup | null
}

/** The circuit, from GO. The single source of the board on this side. */
export const BOARD: readonly Space[] = [
  { index: 0, name: 'GO', kind: 'go', group: null },
  { index: 1, name: 'Avenida Mediterráneo', kind: 'street', group: 'brown' },
  { index: 2, name: 'Community Chest', kind: 'community_chest', group: null },
  { index: 3, name: 'Avenida Báltica', kind: 'street', group: 'brown' },
  { index: 4, name: 'Income Tax', kind: 'income_tax', group: null },
  { index: 5, name: 'Ferrocarril Reading', kind: 'railroad', group: null },
  { index: 6, name: 'Avenida Oriental', kind: 'street', group: 'light_blue' },
  { index: 7, name: 'Chance', kind: 'chance', group: null },
  { index: 8, name: 'Avenida Vermont', kind: 'street', group: 'light_blue' },
  { index: 9, name: 'Avenida Connecticut', kind: 'street', group: 'light_blue' },
  { index: 10, name: 'Cárcel / Solo visitando', kind: 'jail', group: null },
  { index: 11, name: 'St. Charles Place', kind: 'street', group: 'pink' },
  { index: 12, name: 'Compañía Eléctrica', kind: 'utility', group: null },
  { index: 13, name: 'Avenida States', kind: 'street', group: 'pink' },
  { index: 14, name: 'Avenida Virginia', kind: 'street', group: 'pink' },
  { index: 15, name: 'Ferrocarril Pennsylvania', kind: 'railroad', group: null },
  { index: 16, name: 'St. James Place', kind: 'street', group: 'orange' },
  { index: 17, name: 'Community Chest', kind: 'community_chest', group: null },
  { index: 18, name: 'Avenida Tennessee', kind: 'street', group: 'orange' },
  { index: 19, name: 'Avenida New York', kind: 'street', group: 'orange' },
  { index: 20, name: 'Free Parking', kind: 'free_parking', group: null },
  { index: 21, name: 'Avenida Kentucky', kind: 'street', group: 'red' },
  { index: 22, name: 'Chance', kind: 'chance', group: null },
  { index: 23, name: 'Avenida Indiana', kind: 'street', group: 'red' },
  { index: 24, name: 'Avenida Illinois', kind: 'street', group: 'red' },
  { index: 25, name: 'Ferrocarril B. & O.', kind: 'railroad', group: null },
  { index: 26, name: 'Avenida Atlantic', kind: 'street', group: 'yellow' },
  { index: 27, name: 'Avenida Ventnor', kind: 'street', group: 'yellow' },
  { index: 28, name: 'Water Works', kind: 'utility', group: null },
  { index: 29, name: 'Marvin Gardens', kind: 'street', group: 'yellow' },
  { index: 30, name: 'Go to Jail', kind: 'go_to_jail', group: null },
  { index: 31, name: 'Avenida Pacific', kind: 'street', group: 'green' },
  { index: 32, name: 'Avenida North Carolina', kind: 'street', group: 'green' },
  { index: 33, name: 'Community Chest', kind: 'community_chest', group: null },
  { index: 34, name: 'Avenida Pennsylvania', kind: 'street', group: 'green' },
  { index: 35, name: 'Ferrocarril Short Line', kind: 'railroad', group: null },
  { index: 36, name: 'Chance', kind: 'chance', group: null },
  { index: 37, name: 'Park Place', kind: 'street', group: 'dark_blue' },
  { index: 38, name: 'Luxury Tax', kind: 'luxury_tax', group: null },
  { index: 39, name: 'Boardwalk', kind: 'street', group: 'dark_blue' },
]

export const BOARD_SIZE = BOARD.length

export const GO_INDEX = 0
export const INCOME_TAX_INDEX = 4
export const JAIL_INDEX = 10
export const GO_TO_JAIL_INDEX = 30
export const LUXURY_TAX_INDEX = 38

const PURCHASABLE_KINDS: readonly SpaceKind[] = ['street', 'railroad', 'utility']

export const RAILROAD_INDEXES: readonly number[] = BOARD.filter(
  (space) => space.kind === 'railroad',
).map((space) => space.index)

export const UTILITY_INDEXES: readonly number[] = BOARD.filter(
  (space) => space.kind === 'utility',
).map((space) => space.index)

export const STREET_INDEXES: readonly number[] = BOARD.filter(
  (space) => space.kind === 'street',
).map((space) => space.index)

export const PURCHASABLE_INDEXES: readonly number[] = BOARD.filter(isPurchasable).map(
  (space) => space.index,
)

/**
 * Return the space at ``index``.
 *
 * Throws for an index outside the circuit instead of reading the board from
 * the wrong end, mirroring the backend's ``space_at``.
 */
export function spaceAt(index: number): Space {
  if (!Number.isInteger(index) || index < 0 || index >= BOARD_SIZE) {
    throw new Error(`space index out of the board: ${index}`)
  }
  return BOARD[index]
}

/** Return every space of ``kind``, in circuit order. */
export function spacesOfKind(kind: SpaceKind): readonly Space[] {
  return BOARD.filter((space) => space.kind === kind)
}

/** Return the street indexes of ``group``, in circuit order. */
export function streetIndexes(group: ColorGroup): readonly number[] {
  return BOARD.filter((space) => space.group === group).map((space) => space.index)
}

/** Whether the bank can sell this space to a player. */
export function isPurchasable(space: Space): boolean {
  return PURCHASABLE_KINDS.includes(space.kind)
}
