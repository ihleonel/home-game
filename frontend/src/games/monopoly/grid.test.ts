import { describe, expect, it } from 'vitest'
import { BOARD, BOARD_SIZE } from './board'
import { GRID_SIZE, spaceArea } from './grid'

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

describe('the board grid placement', () => {
  it('is an 11x11 grid whose perimeter is exactly the 40 spaces', () => {
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
})
