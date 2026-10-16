import { describe, expect, it } from 'vitest'
import type { ColorGroup } from './board'
import { PURCHASABLE_INDEXES, RAILROAD_INDEXES, STREET_INDEXES, UTILITY_INDEXES, streetIndexes } from './board'
import {
  HOTEL_LEVEL,
  MAX_HOUSE_LEVEL,
  RAILROAD_MORTGAGE,
  RAILROAD_PRICE,
  RAILROAD_RENTS,
  STREET_DEEDS,
  UTILITY_DICE_MULTIPLIERS,
  UTILITY_MORTGAGE,
  UTILITY_PRICE,
  deedFor,
  developmentCost,
  levelLabel,
  mortgageLiftCost,
  mortgageValue,
  purchasePrice,
  rentForLevel,
  sellBack,
} from './deeds'

/**
 * ``[index, price, baseRent, setRent, houseRents, hotelRent, houseCost,
 * mortgage]`` for each of the 22 streets, in circuit order.
 *
 * The normative deed economy (S4 of ``monopoly.md``), intentionally literal.
 * The backend pins the same table in ``test_monopoly_deeds.py``.
 */
const EXPECTED: readonly (readonly [
  number,
  number,
  number,
  number,
  readonly number[],
  number,
  number,
  number,
])[] = [
  [1, 60, 2, 4, [10, 30, 90, 160], 250, 50, 30],
  [3, 60, 4, 8, [20, 60, 180, 320], 450, 50, 30],
  [6, 100, 6, 12, [30, 90, 270, 400], 550, 50, 50],
  [8, 100, 6, 12, [30, 90, 270, 400], 550, 50, 50],
  [9, 120, 8, 16, [40, 100, 300, 450], 600, 50, 60],
  [11, 140, 10, 20, [50, 150, 450, 625], 750, 100, 70],
  [13, 140, 10, 20, [50, 150, 450, 625], 750, 100, 70],
  [14, 160, 12, 24, [60, 180, 500, 700], 900, 100, 80],
  [16, 180, 14, 28, [70, 200, 550, 750], 950, 100, 90],
  [18, 180, 14, 28, [70, 200, 550, 750], 950, 100, 90],
  [19, 200, 16, 32, [80, 220, 600, 800], 1000, 100, 100],
  [21, 220, 18, 36, [90, 250, 700, 875], 1050, 150, 110],
  [23, 220, 18, 36, [90, 250, 700, 875], 1050, 150, 110],
  [24, 240, 20, 40, [100, 300, 750, 925], 1100, 150, 120],
  [26, 260, 22, 44, [110, 330, 800, 975], 1150, 150, 130],
  [27, 260, 22, 44, [110, 330, 800, 975], 1150, 150, 130],
  [29, 280, 24, 48, [120, 360, 850, 1025], 1200, 150, 140],
  [31, 300, 26, 52, [130, 390, 900, 1100], 1275, 200, 150],
  [32, 300, 26, 52, [130, 390, 900, 1100], 1275, 200, 150],
  [34, 320, 28, 56, [150, 450, 1000, 1200], 1400, 200, 160],
  [37, 350, 35, 70, [175, 500, 1100, 1300], 1500, 200, 175],
  [39, 400, 50, 100, [200, 600, 1400, 1700], 2000, 200, 200],
]

/** ``group -> printed price total``, the cheapest checksum for a wrong price. */
const GROUP_TOTALS: readonly (readonly [ColorGroup, number])[] = [
  ['brown', 120],
  ['light_blue', 320],
  ['pink', 440],
  ['orange', 560],
  ['red', 680],
  ['yellow', 800],
  ['green', 920],
  ['dark_blue', 750],
]

/** ``group -> house cost``; every street of a group shares it. */
const GROUP_HOUSE_COSTS: readonly (readonly [ColorGroup, number])[] = [
  ['brown', 50],
  ['light_blue', 50],
  ['pink', 100],
  ['orange', 100],
  ['red', 150],
  ['yellow', 150],
  ['green', 200],
  ['dark_blue', 200],
]

describe('the monopoly deed economy', () => {
  it('matches the normative table, field by field', () => {
    expect(
      STREET_DEEDS.map((deed) => [
        deed.index,
        deed.price,
        deed.baseRent,
        deed.setRent,
        deed.houseRents,
        deed.hotelRent,
        deed.houseCost,
        deed.mortgage,
      ]),
    ).toEqual(EXPECTED)
  })

  it('covers exactly the streets of the board', () => {
    expect(STREET_DEEDS.map((deed) => deed.index)).toEqual(STREET_INDEXES)
    for (const index of STREET_INDEXES) expect(deedFor(index).index).toBe(index)
  })

  it('doubles the unimproved rent on a complete set', () => {
    for (const deed of STREET_DEEDS) {
      expect([deed.index, deed.setRent]).toEqual([deed.index, deed.baseRent * 2])
    }
  })

  it('adds each group up to its printed total', () => {
    for (const [group, total] of GROUP_TOTALS) {
      const sum = streetIndexes(group).reduce((acc, index) => acc + deedFor(index).price, 0)
      expect([group, sum]).toEqual([group, total])
    }
  })

  it('charges every street of a group the group building cost', () => {
    for (const [group, cost] of GROUP_HOUSE_COSTS) {
      for (const index of streetIndexes(group)) {
        expect([index, deedFor(index).houseCost]).toEqual([index, cost])
      }
    }
  })

  it('pays the rent of the development level, hotel included', () => {
    const deed = deedFor(1)
    expect(rentForLevel(deed, 0)).toBe(2)
    expect(rentForLevel(deed, 1)).toBe(10)
    expect(rentForLevel(deed, 4)).toBe(160)
    expect(rentForLevel(deed, 5)).toBe(250)
  })

  it('rejects a development level off the scale', () => {
    const deed = deedFor(1)
    expect(() => rentForLevel(deed, -1)).toThrow()
    expect(() => rentForLevel(deed, 6)).toThrow()
  })

  it('prices the development of a street as so many house costs', () => {
    const deed = deedFor(1)

    expect(developmentCost(deed, 0)).toBe(0)
    expect(developmentCost(deed, 1)).toBe(deed.houseCost)
    expect(developmentCost(deed, 4)).toBe(deed.houseCost * 4)
    expect(developmentCost(deed, HOTEL_LEVEL)).toBe(deed.houseCost * 5)
  })

  it('values a hotel at five houses on every street', () => {
    for (const deed of STREET_DEEDS) {
      expect(developmentCost(deed, HOTEL_LEVEL)).toBe(deed.houseCost * 5)
    }
  })

  it('rejects a development cost off the scale', () => {
    const deed = deedFor(1)
    expect(() => developmentCost(deed, -1)).toThrow()
    expect(() => developmentCost(deed, 6)).toThrow()
  })

  it('pays back half the house cost for one sold level', () => {
    for (const deed of STREET_DEEDS) {
      expect(sellBack(deed)).toBe(deed.houseCost / 2)
      expect(Number.isInteger(sellBack(deed))).toBe(true)
    }
  })

  it('matches selling level by level with half of the development value', () => {
    for (const deed of STREET_DEEDS) {
      for (let level = 1; level <= HOTEL_LEVEL; level += 1) {
        const sold = Array.from({ length: level }, () => sellBack(deed)).reduce(
          (total, value) => total + value,
          0,
        )
        expect([deed.index, level, sold]).toEqual([
          deed.index,
          level,
          Math.trunc(developmentCost(deed, level) / 2),
        ])
      }
    }
  })

  it('labels a built level in Spanish, the hotel included', () => {
    expect(levelLabel(1)).toBe('1 casa')
    expect(levelLabel(2)).toBe('2 casas')
    expect(levelLabel(MAX_HOUSE_LEVEL)).toBe('4 casas')
    expect(levelLabel(HOTEL_LEVEL)).toBe('Hotel')
  })

  it('rejects a label for a level nothing is built at', () => {
    expect(() => levelLabel(0)).toThrow()
    expect(() => levelLabel(6)).toThrow()
  })

  it('prices a railroad and scales its rent with how many are held', () => {
    expect(RAILROAD_PRICE).toBe(200)
    expect(RAILROAD_MORTGAGE).toBe(100)
    expect(RAILROAD_RENTS).toEqual([25, 50, 100, 200])
    for (const index of RAILROAD_INDEXES) {
      expect(purchasePrice(index)).toBe(200)
      expect(mortgageValue(index)).toBe(100)
    }
  })

  it('prices a utility and pays a dice multiple', () => {
    expect(UTILITY_PRICE).toBe(150)
    expect(UTILITY_MORTGAGE).toBe(75)
    expect(UTILITY_DICE_MULTIPLIERS).toEqual([4, 10])
    for (const index of UTILITY_INDEXES) {
      expect(purchasePrice(index)).toBe(150)
      expect(mortgageValue(index)).toBe(75)
    }
  })

  it('lifts a mortgage for the value plus a tenth rounded up', () => {
    // Park Place: $175 of mortgage plus $18 of interest is $193 (S4).
    expect(mortgageLiftCost(37)).toBe(193)
    for (const index of PURCHASABLE_INDEXES) {
      const mortgage = mortgageValue(index)
      expect([index, mortgageLiftCost(index)]).toEqual([
        index,
        mortgage + Math.ceil(mortgage / 10),
      ])
    }
    for (const index of RAILROAD_INDEXES) expect(mortgageLiftCost(index)).toBe(110)
    for (const index of UTILITY_INDEXES) expect(mortgageLiftCost(index)).toBe(83)
  })

  it('refuses a lift cost for a space the bank cannot mortgage', () => {
    for (let index = 0; index < 40; index += 1) {
      if (PURCHASABLE_INDEXES.includes(index)) continue
      expect(() => mortgageLiftCost(index)).toThrow()
    }
  })

  it('prices every purchasable space and nothing else', () => {
    for (const index of PURCHASABLE_INDEXES) {
      expect(purchasePrice(index)).toBeGreaterThan(0)
      expect(mortgageValue(index)).toBeGreaterThan(0)
    }
    for (let index = 0; index < 40; index += 1) {
      if (PURCHASABLE_INDEXES.includes(index)) continue
      expect(() => purchasePrice(index)).toThrow()
      expect(() => mortgageValue(index)).toThrow()
      expect(() => deedFor(index)).toThrow()
    }
  })
})
