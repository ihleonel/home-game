import { describe, expect, it } from 'vitest'
import {
  BOARD,
  BOARD_SIZE,
  GO_INDEX,
  GO_TO_JAIL_INDEX,
  INCOME_TAX_INDEX,
  JAIL_INDEX,
  LUXURY_TAX_INDEX,
  PURCHASABLE_INDEXES,
  RAILROAD_INDEXES,
  STREET_INDEXES,
  UTILITY_INDEXES,
  isPurchasable,
  spaceAt,
  spacesOfKind,
  streetIndexes,
} from './board'
import type { ColorGroup, SpaceKind } from './board'

/**
 * ``[name, kind, group]`` for each of the 40 spaces, in circuit order from GO.
 *
 * This table is the normative board (S3 of ``monopoly.md``) transcribed from
 * the classic U.S. board, and it is intentionally literal: a change to
 * ``board.ts`` alone can never rewrite the expectation. The backend pins the
 * same table in ``test_monopoly_board.py``, so a wrong transcription fails on
 * its own side.
 */
const EXPECTED: readonly (readonly [string, SpaceKind, ColorGroup | null])[] = [
  ['GO', 'go', null],
  ['Avenida Mediterráneo', 'street', 'brown'],
  ['Community Chest', 'community_chest', null],
  ['Avenida Báltica', 'street', 'brown'],
  ['Income Tax', 'income_tax', null],
  ['Ferrocarril Reading', 'railroad', null],
  ['Avenida Oriental', 'street', 'light_blue'],
  ['Chance', 'chance', null],
  ['Avenida Vermont', 'street', 'light_blue'],
  ['Avenida Connecticut', 'street', 'light_blue'],
  ['Cárcel / Solo visitando', 'jail', null],
  ['St. Charles Place', 'street', 'pink'],
  ['Compañía Eléctrica', 'utility', null],
  ['Avenida States', 'street', 'pink'],
  ['Avenida Virginia', 'street', 'pink'],
  ['Ferrocarril Pennsylvania', 'railroad', null],
  ['St. James Place', 'street', 'orange'],
  ['Community Chest', 'community_chest', null],
  ['Avenida Tennessee', 'street', 'orange'],
  ['Avenida New York', 'street', 'orange'],
  ['Free Parking', 'free_parking', null],
  ['Avenida Kentucky', 'street', 'red'],
  ['Chance', 'chance', null],
  ['Avenida Indiana', 'street', 'red'],
  ['Avenida Illinois', 'street', 'red'],
  ['Ferrocarril B. & O.', 'railroad', null],
  ['Avenida Atlantic', 'street', 'yellow'],
  ['Avenida Ventnor', 'street', 'yellow'],
  ['Water Works', 'utility', null],
  ['Marvin Gardens', 'street', 'yellow'],
  ['Go to Jail', 'go_to_jail', null],
  ['Avenida Pacific', 'street', 'green'],
  ['Avenida North Carolina', 'street', 'green'],
  ['Community Chest', 'community_chest', null],
  ['Avenida Pennsylvania', 'street', 'green'],
  ['Ferrocarril Short Line', 'railroad', null],
  ['Chance', 'chance', null],
  ['Park Place', 'street', 'dark_blue'],
  ['Luxury Tax', 'luxury_tax', null],
  ['Boardwalk', 'street', 'dark_blue'],
]

/** ``group -> streets`` in circuit order, for the eight colour groups (S4). */
const EXPECTED_GROUPS: readonly (readonly [ColorGroup, readonly number[]])[] = [
  ['brown', [1, 3]],
  ['light_blue', [6, 8, 9]],
  ['pink', [11, 13, 14]],
  ['orange', [16, 18, 19]],
  ['red', [21, 23, 24]],
  ['yellow', [26, 27, 29]],
  ['green', [31, 32, 34]],
  ['dark_blue', [37, 39]],
]

const KIND_COUNTS: readonly (readonly [SpaceKind, number])[] = [
  ['street', 22],
  ['railroad', 4],
  ['utility', 2],
  ['chance', 3],
  ['community_chest', 3],
  ['income_tax', 1],
  ['luxury_tax', 1],
  ['go', 1],
  ['jail', 1],
  ['free_parking', 1],
  ['go_to_jail', 1],
]

describe('the monopoly board data', () => {
  it('matches the normative table, in order', () => {
    expect(BOARD).toHaveLength(40)
    expect(BOARD_SIZE).toBe(40)
    expect(
      BOARD.map((space) => [space.index, space.name, space.kind, space.group]),
    ).toEqual(EXPECTED.map(([name, kind, group], index) => [index, name, kind, group]))
  })

  it('is a contiguous run from GO', () => {
    expect(BOARD.map((space) => space.index)).toEqual(
      Array.from({ length: 40 }, (_, index) => index),
    )
    expect(GO_INDEX).toBe(0)
    expect(spaceAt(GO_INDEX).kind).toBe('go')
  })

  it('places the landmark constants on the right spaces', () => {
    expect(spaceAt(JAIL_INDEX).kind).toBe('jail')
    expect(spaceAt(INCOME_TAX_INDEX).kind).toBe('income_tax')
    expect(spaceAt(LUXURY_TAX_INDEX).kind).toBe('luxury_tax')
    expect(spaceAt(GO_TO_JAIL_INDEX).kind).toBe('go_to_jail')
    expect([JAIL_INDEX, INCOME_TAX_INDEX]).toEqual([10, 4])
    expect([LUXURY_TAX_INDEX, GO_TO_JAIL_INDEX]).toEqual([38, 30])
  })

  it('holds the composition of the classic board', () => {
    for (const [kind, count] of KIND_COUNTS) {
      expect([kind, spacesOfKind(kind).length]).toEqual([kind, count])
    }
  })

  it('has the 28 purchasable spaces', () => {
    const expected = EXPECTED.map(([, kind], index) => ({ kind, index }))
      .filter(({ kind }) => kind === 'street' || kind === 'railroad' || kind === 'utility')
      .map(({ index }) => index)
    expect(PURCHASABLE_INDEXES).toEqual(expected)
    expect(PURCHASABLE_INDEXES).toHaveLength(28)
    expect(RAILROAD_INDEXES).toEqual([5, 15, 25, 35])
    expect(UTILITY_INDEXES).toEqual([12, 28])
    expect(STREET_INDEXES).toEqual(
      EXPECTED.map(([, kind], index) => ({ kind, index }))
        .filter(({ kind }) => kind === 'street')
        .map(({ index }) => index),
    )
  })

  it('maps every colour group to its streets', () => {
    for (const [group, indexes] of EXPECTED_GROUPS) {
      expect([group, streetIndexes(group)]).toEqual([group, indexes])
    }
  })

  it('gives every street a group and no other space one', () => {
    for (const space of BOARD) {
      if (space.kind === 'street') expect(space.group).not.toBeNull()
      else expect(space.group).toBeNull()
    }
  })

  it('rejects an index outside the board', () => {
    expect(() => spaceAt(-1)).toThrow()
    expect(() => spaceAt(40)).toThrow()
    expect(() => spaceAt(1.5)).toThrow()
  })

  it('tells which spaces the bank can sell', () => {
    expect(BOARD.filter(isPurchasable)).toHaveLength(28)
    expect(isPurchasable(spaceAt(1))).toBe(true)
    expect(isPurchasable(spaceAt(4))).toBe(false)
  })
})
