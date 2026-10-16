/**
 * Static deed economy of the classic Monopoly board.
 *
 * The frontend copy of the normative table the backend owns in
 * ``modules/games/monopoly/deeds.py`` (S1 of ``monopoly-interface.md``), with
 * ``deeds.test.ts`` pinning the same literal table the backend test pins.
 *
 * It exists so the board and the player panel can show the printed price and
 * the printed rents of a property without asking the server for data that never
 * changes. It is **reference data only**: which rent is actually owed is the
 * server's decision and arrives in the match view.
 */

import { spaceAt } from './board'

/** A street reaches its hotel at level 5 and holds at most four houses. */
export const MAX_HOUSE_LEVEL = 4
export const HOTEL_LEVEL = 5

export const RAILROAD_PRICE = 200
export const RAILROAD_MORTGAGE = 100
/** Rent by the number of railroads held, so index 0 is one railroad. */
export const RAILROAD_RENTS: readonly number[] = [25, 50, 100, 200]

export const UTILITY_PRICE = 150
export const UTILITY_MORTGAGE = 75
/** Rent multiplier by the number of utilities held: 4x with one, 10x with both. */
export const UTILITY_DICE_MULTIPLIERS: readonly number[] = [4, 10]

/**
 * The title deed of one street.
 *
 * ``setRent`` is the unimproved rent an owner may charge once the whole colour
 * group is held; the server decides when it applies. ``houseRents`` holds the
 * rents for one to four houses, in order.
 */
export type Deed = {
  index: number
  price: number
  baseRent: number
  setRent: number
  houseRents: readonly number[]
  hotelRent: number
  houseCost: number
  mortgage: number
}

/** Keyed by the space index, so a deed is found by the space it belongs to. */
const DEEDS: Record<number, Deed> = {
  1: { index: 1, price: 60, baseRent: 2, setRent: 4, houseRents: [10, 30, 90, 160], hotelRent: 250, houseCost: 50, mortgage: 30 },
  3: { index: 3, price: 60, baseRent: 4, setRent: 8, houseRents: [20, 60, 180, 320], hotelRent: 450, houseCost: 50, mortgage: 30 },
  6: { index: 6, price: 100, baseRent: 6, setRent: 12, houseRents: [30, 90, 270, 400], hotelRent: 550, houseCost: 50, mortgage: 50 },
  8: { index: 8, price: 100, baseRent: 6, setRent: 12, houseRents: [30, 90, 270, 400], hotelRent: 550, houseCost: 50, mortgage: 50 },
  9: { index: 9, price: 120, baseRent: 8, setRent: 16, houseRents: [40, 100, 300, 450], hotelRent: 600, houseCost: 50, mortgage: 60 },
  11: { index: 11, price: 140, baseRent: 10, setRent: 20, houseRents: [50, 150, 450, 625], hotelRent: 750, houseCost: 100, mortgage: 70 },
  13: { index: 13, price: 140, baseRent: 10, setRent: 20, houseRents: [50, 150, 450, 625], hotelRent: 750, houseCost: 100, mortgage: 70 },
  14: { index: 14, price: 160, baseRent: 12, setRent: 24, houseRents: [60, 180, 500, 700], hotelRent: 900, houseCost: 100, mortgage: 80 },
  16: { index: 16, price: 180, baseRent: 14, setRent: 28, houseRents: [70, 200, 550, 750], hotelRent: 950, houseCost: 100, mortgage: 90 },
  18: { index: 18, price: 180, baseRent: 14, setRent: 28, houseRents: [70, 200, 550, 750], hotelRent: 950, houseCost: 100, mortgage: 90 },
  19: { index: 19, price: 200, baseRent: 16, setRent: 32, houseRents: [80, 220, 600, 800], hotelRent: 1000, houseCost: 100, mortgage: 100 },
  21: { index: 21, price: 220, baseRent: 18, setRent: 36, houseRents: [90, 250, 700, 875], hotelRent: 1050, houseCost: 150, mortgage: 110 },
  23: { index: 23, price: 220, baseRent: 18, setRent: 36, houseRents: [90, 250, 700, 875], hotelRent: 1050, houseCost: 150, mortgage: 110 },
  24: { index: 24, price: 240, baseRent: 20, setRent: 40, houseRents: [100, 300, 750, 925], hotelRent: 1100, houseCost: 150, mortgage: 120 },
  26: { index: 26, price: 260, baseRent: 22, setRent: 44, houseRents: [110, 330, 800, 975], hotelRent: 1150, houseCost: 150, mortgage: 130 },
  27: { index: 27, price: 260, baseRent: 22, setRent: 44, houseRents: [110, 330, 800, 975], hotelRent: 1150, houseCost: 150, mortgage: 130 },
  29: { index: 29, price: 280, baseRent: 24, setRent: 48, houseRents: [120, 360, 850, 1025], hotelRent: 1200, houseCost: 150, mortgage: 140 },
  31: { index: 31, price: 300, baseRent: 26, setRent: 52, houseRents: [130, 390, 900, 1100], hotelRent: 1275, houseCost: 200, mortgage: 150 },
  32: { index: 32, price: 300, baseRent: 26, setRent: 52, houseRents: [130, 390, 900, 1100], hotelRent: 1275, houseCost: 200, mortgage: 150 },
  34: { index: 34, price: 320, baseRent: 28, setRent: 56, houseRents: [150, 450, 1000, 1200], hotelRent: 1400, houseCost: 200, mortgage: 160 },
  37: { index: 37, price: 350, baseRent: 35, setRent: 70, houseRents: [175, 500, 1100, 1300], hotelRent: 1500, houseCost: 200, mortgage: 175 },
  39: { index: 39, price: 400, baseRent: 50, setRent: 100, houseRents: [200, 600, 1400, 1700], hotelRent: 2000, houseCost: 200, mortgage: 200 },
}

/** Every street deed, in circuit order. */
export const STREET_DEEDS: readonly Deed[] = Object.values(DEEDS).sort(
  (left, right) => left.index - right.index,
)

/**
 * Return the deed of the street at ``index``.
 *
 * Throws for a space that is not a street: a railroad and a utility are
 * purchasable, but they have no title deed, and handing one back would let a
 * caller build houses on Boardwalk's neighbours.
 */
export function deedFor(index: number): Deed {
  const deed = DEEDS[index]
  if (deed === undefined) throw new Error(`space ${index} has no street deed`)
  return deed
}

/** Return the rent printed for a development level (0 unimproved, 5 hotel). */
export function rentForLevel(deed: Deed, level: number): number {
  if (!Number.isInteger(level) || level < 0 || level > HOTEL_LEVEL) {
    throw new Error(`development level out of range: ${level}`)
  }
  if (level === 0) return deed.baseRent
  if (level === HOTEL_LEVEL) return deed.hotelRent
  return deed.houseRents[level - 1]
}

/**
 * The cost price of a street's buildings at ``level`` (S5).
 *
 * Level 5 is a hotel and is worth **five** houses: its seat paid four houses
 * (returned to the bank when the hotel went up) plus the hotel's own price.
 * This is the only place the equivalence lives, so the rent, the tax and the
 * bankruptcy cannot drift. Raises for a level off the scale.
 */
export function developmentCost(deed: Deed, level: number): number {
  if (!Number.isInteger(level) || level < 0 || level > HOTEL_LEVEL) {
    throw new Error(`development level out of range: ${level}`)
  }
  return deed.houseCost * level
}

/**
 * The cash one sold level returns to its owner (S4/S5).
 *
 * Vending is the reverse of buying, level by level, at one half of the price
 * paid. Every ``houseCost`` on this board is even, so the half is an integer
 * and there is no rounding to choose.
 */
export function sellBack(deed: Deed): number {
  return deed.houseCost / 2
}

/**
 * The Spanish label of a built level: ``1 casa`` … ``4 casas`` and ``Hotel``.
 *
 * It lives beside the level constants because it names the same scale the rest
 * of this module prices, and the board and the panel must say it the same way.
 * Raises for level 0, where nothing is built and there is nothing to announce.
 */
export function levelLabel(level: number): string {
  if (!Number.isInteger(level) || level < 1 || level > HOTEL_LEVEL) {
    throw new Error(`development level out of range: ${level}`)
  }
  if (level === HOTEL_LEVEL) return 'Hotel'
  return `${level} ${level === 1 ? 'casa' : 'casas'}`
}

/** Return the printed purchase price of a purchasable space. */
export function purchasePrice(index: number): number {
  const space = spaceAt(index)
  if (space.kind === 'street') return deedFor(index).price
  if (space.kind === 'railroad') return RAILROAD_PRICE
  if (space.kind === 'utility') return UTILITY_PRICE
  throw new Error(`space ${index} (${space.name}) is not purchasable`)
}

/** Return the printed mortgage value of a purchasable space. */
export function mortgageValue(index: number): number {
  const space = spaceAt(index)
  if (space.kind === 'street') return deedFor(index).mortgage
  if (space.kind === 'railroad') return RAILROAD_MORTGAGE
  if (space.kind === 'utility') return UTILITY_MORTGAGE
  throw new Error(`space ${index} (${space.name}) is not purchasable`)
}
