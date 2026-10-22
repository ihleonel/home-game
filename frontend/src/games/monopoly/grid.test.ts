import { describe, expect, it } from 'vitest'
import { BOARD, BOARD_SIZE } from './board'
import { GRID_SIZE, spaceArea, spaceSide } from './grid'

/** The four corners, at the corners of the printed board. */
const CORNERS: readonly (readonly [number, number, number])[] = [
  [0, 11, 11],
  [10, 11, 1],
  [20, 1, 1],
  [30, 1, 11],
]

/** One space of each side, to pin the direction the circuit runs in. */
const SIDES: readonly (readonly [number, number, number])[] = [
  [1, 11, 10],
  [9, 11, 2],
  [11, 10, 1],
  [19, 2, 1],
  [21, 1, 2],
  [29, 1, 10],
  [31, 2, 11],
  [39, 10, 11],
]

describe('the board grid placement', () => {  it('is an 11x11 grid whose perimeter is exactly the 40 spaces', () => {
    expect(GRID_SIZE).toBe(11)
    expect(4 * (GRID_SIZE - 1)).toBe(BOARD_SIZE)
  })

  it('puts GO bottom-right and runs clockwise, as the printed board does', () => {
    for (const [index, row, column] of CORNERS) {
      expect([index, spaceArea(index)]).toEqual([index, { row, column }])
    }
    for (const [index, row, column] of SIDES) {
      expect([index, spaceArea(index)]).toEqual([index, { row, column }])
    }
  })

  it('leaves the centre free for the detail panel', () => {
    for (const index of BOARD.map((space) => space.index)) {
      const { row, column } = spaceArea(index)
      const inCentre = row >= 2 && row <= 10 && column >= 2 && column <= 10
      expect([index, inCentre]).toEqual([index, false])
    }
  })

  it('gives every space its own perimeter cell', () => {
    const areas = BOARD.map((space) => {
      const { row, column } = spaceArea(space.index)
      return `${row}:${column}`
    })
    expect(new Set(areas).size).toBe(BOARD_SIZE)
    for (const area of areas) {
      const [row, column] = area.split(':').map(Number)
      const onPerimeter = row === 1 || row === GRID_SIZE || column === 1 || column === GRID_SIZE
      expect([area, onPerimeter]).toEqual([area, true])
    }
  })

  it('rejects an index outside the board', () => {
    expect(() => spaceArea(-1)).toThrow()
    expect(() => spaceArea(40)).toThrow()
    expect(() => spaceArea(2.5)).toThrow()
  })

  it('gives every space the side of the ring it belongs to', () => {
    // The corners belong to the segment that starts in them, which is how the
    // printed board reads: GO opens the bottom edge and Go to Jail the right one.
    expect(
      [0, 10, 20, 30].map((index) => spaceSide(index)),
    ).toEqual(['bottom', 'left', 'top', 'right'])
  })

  it('spreads the forty spaces evenly over the four sides', () => {
    for (const side of ['bottom', 'left', 'top', 'right'] as const) {
      const onSide = BOARD.filter((space) => spaceSide(space.index) === side)
      expect([side, onSide.length]).toEqual([side, 10])
    }
  })

  it('agrees with the placement: each side sits on its own edge of the grid', () => {
    for (const space of BOARD) {
      const { row, column } = spaceArea(space.index)
      const expected = {
        bottom: row === GRID_SIZE,
        top: row === 1,
        left: column === 1,
        right: column === GRID_SIZE,
      }[spaceSide(space.index)]
      expect([space.index, expected]).toEqual([space.index, true])
    }
  })

  it('rejects a side for an index outside the board', () => {
    expect(() => spaceSide(-1)).toThrow()
    expect(() => spaceSide(40)).toThrow()
  })
})
