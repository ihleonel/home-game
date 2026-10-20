import { describe, expect, it } from 'vitest'
import { BOARD, BOARD_SIZE } from './board'
import { GRID_SIZE, spaceArea, spaceSide } from './grid'
import {
  WINDOW_SIZE,
  canMoveWindow,
  cellFor,
  moveWindow,
  nextTurns,
  recentreForFocus,
  seatWindow,
  sideFor,
  startTurns,
  visibleSpaces,
  windowAround,
} from './viewport'

/** The four corners in circuit order, each with where it sits on the printed board. */
const CORNERS: readonly (readonly [number, number, number])[] = [
  [0, 11, 11],
  [10, 11, 1],
  [20, 1, 1],
  [30, 1, 11],
]

describe('turning the table', () => {
  it('leaves the printed orientation untouched at zero turns', () => {
    for (const space of BOARD) {
      expect([space.index, cellFor(space.index, 0)]).toEqual([space.index, spaceArea(space.index)])
      expect([space.index, sideFor(space.index, 0)]).toEqual([
        space.index,
        spaceSide(space.index),
      ])
    }
  })

  it('puts GO bottom-left after a quarter turn, so the text never leaves the horizontal', () => {
    // The printed board holds GO bottom-right. A quarter turn of the square ring
    // moves it to the bottom-left corner; the other corners follow the circuit.
    expect(cellFor(0, 1)).toEqual({ row: 11, column: 1 })
    expect(cellFor(10, 1)).toEqual({ row: 1, column: 1 })
    expect(cellFor(20, 1)).toEqual({ row: 1, column: 11 })
    expect(cellFor(30, 1)).toEqual({ row: 11, column: 11 })
    for (const [index, row, column] of CORNERS) {
      // A clockwise quarter turn of the square sends (row, column) to
      // (column, 12 - row); deriving it from the printed corners keeps this an
      // independent oracle instead of a second copy of cellFor.
      expect([index, cellFor(index, 1)]).toEqual([index, { row: column, column: 12 - row }])
    }
  })

  it('rotates the side of the ring with the cell, so the band still faces the centre', () => {
    expect(sideFor(0, 1)).toBe('left')
    expect(sideFor(10, 1)).toBe('top')
    expect(sideFor(20, 1)).toBe('right')
    expect(sideFor(30, 1)).toBe('bottom')
    // Every space keeps a side whose edge of the grid it actually sits on.
    for (const turns of [0, 1, 2, 3] as const) {
      for (const space of BOARD) {
        const { row, column } = cellFor(space.index, turns)
        const onItsEdge = {
          bottom: row === GRID_SIZE,
          top: row === 1,
          left: column === 1,
          right: column === GRID_SIZE,
        }[sideFor(space.index, turns)]
        expect([space.index, turns, onItsEdge]).toEqual([space.index, turns, true])
      }
    }
  })

  it('gives every space a different cell at every turn, never the centre', () => {
    for (const turns of [0, 1, 2, 3] as const) {
      const cells = BOARD.map((space) => {
        const { row, column } = cellFor(space.index, turns)
        const onPerimeter = row === 1 || row === GRID_SIZE || column === 1 || column === GRID_SIZE
        expect([space.index, turns, onPerimeter]).toEqual([space.index, turns, true])
        return `${row}:${column}`
      })
      expect([turns, new Set(cells).size]).toEqual([turns, BOARD_SIZE])
    }
  })

  it('rejects an index outside the board before shifting it', () => {
    // 40 would wrap to GO if the shift ran first, so the bound is checked on the
    // index the caller gave, not on the shifted one.
    expect(() => cellFor(40, 0)).toThrow()
    expect(() => cellFor(-1, 0)).toThrow()
    expect(() => cellFor(2.5, 0)).toThrow()
    expect(() => sideFor(40, 0)).toThrow()
  })

  it('spreads the ring evenly over the four sides after any turn', () => {
    for (const turns of [0, 1, 2, 3] as const) {
      for (const side of ['bottom', 'left', 'top', 'right'] as const) {
        const onSide = BOARD.filter((space) => sideFor(space.index, turns) === side)
        expect([turns, side, onSide.length]).toEqual([turns, side, 10])
      }
    }
  })
})

describe('the turn controls', () => {
  it('wraps a quarter turn in both directions', () => {
    expect([nextTurns(0, 1), nextTurns(3, 1), nextTurns(0, -1), nextTurns(2, 2)]).toEqual([
      1, 0, 3, 0,
    ])
  })

  it('returns to the printed orientation after four quarter turns', () => {
    let turns = nextTurns(0, 1)
    for (let step = 0; step < 3; step += 1) turns = nextTurns(turns, 1)
    expect(turns).toBe(0)
  })

  it('gives each seat one of the four sides, the first seat keeping the printed one', () => {
    // Every seat starts on GO after the opening throw, so the position cannot
    // pick an orientation and the seat order does: people sit around a table.
    expect([0, 1, 2, 3, 4, 5, 6, 7].map((seat) => startTurns(seat))).toEqual([
      0, 1, 2, 3, 0, 1, 2, 3,
    ])
  })
})

describe('the seat window', () => {
  it('shows seven of the eleven cells a side', () => {
    expect(WINDOW_SIZE).toBe(7)
    expect(GRID_SIZE - WINDOW_SIZE + 1).toBe(5)
  })

  it('centres on the own cell and stays on the board at the four extremes', () => {
    expect(windowAround({ row: 6, column: 6 })).toEqual({ row: 3, column: 3 })
    expect(windowAround({ row: 11, column: 11 })).toEqual({ row: 5, column: 5 })
    expect(windowAround({ row: 1, column: 1 })).toEqual({ row: 1, column: 1 })
    expect(windowAround({ row: 11, column: 1 })).toEqual({ row: 5, column: 1 })
    expect(windowAround({ row: 1, column: 11 })).toEqual({ row: 1, column: 5 })
    expect(windowAround({ row: 3, column: 9 })).toEqual({ row: 1, column: 5 })
  })

  it('moves one cell at a time and refuses to leave the board', () => {
    const centre = { row: 3, column: 3 }
    expect(moveWindow(centre, 'up')).toEqual({ row: 2, column: 3 })
    expect(moveWindow(centre, 'down')).toEqual({ row: 4, column: 3 })
    expect(moveWindow(centre, 'left')).toEqual({ row: 3, column: 2 })
    expect(moveWindow(centre, 'right')).toEqual({ row: 3, column: 4 })
    const corner = { row: 1, column: 1 }
    expect([canMoveWindow(corner, 'up'), canMoveWindow(corner, 'left')]).toEqual([false, false])
    expect([canMoveWindow(corner, 'down'), canMoveWindow(corner, 'right')]).toEqual([true, true])
    // The refusals also clamp, so calling the move anyway cannot leave the board.
    expect(moveWindow(corner, 'up')).toEqual(corner)
    expect(moveWindow({ row: 5, column: 5 }, 'down')).toEqual({ row: 5, column: 5 })
  })

  it('reports the spaces the window actually shows, in circuit order', () => {
    // Rows 1..7 and columns 1..7 hold the tail of the left side and the head of
    // the top one: spaces 14 to 26, both included.
    expect(visibleSpaces({ row: 1, column: 1 }, 0)).toEqual(
      Array.from({ length: 13 }, (_, step) => 14 + step),
    )
    // A quarter turn shifts the circuit by ten, so the same window shows 4..16.
    expect(visibleSpaces({ row: 1, column: 1 }, 1)).toEqual(
      Array.from({ length: 13 }, (_, step) => 4 + step),
    )
  })

  it('starts the arc after the hidden space, so a corner window reads across the seam', () => {
    // The bottom-right window holds the right column's tail and the bottom row's
    // head: 34..39 followed by 0..6, the arc that crosses GO. It is one arc on
    // the circle, so the list begins at 34 -- 33 is not visible -- and must not
    // be described as "34 to 6".
    expect(visibleSpaces({ row: 5, column: 5 }, 0)).toEqual([
      34, 35, 36, 37, 38, 39, 0, 1, 2, 3, 4, 5, 6,
    ])
  })

  it('names no space when the window sits over the centre of the table', () => {
    // Panning inward can leave a 7x7 window over the empty middle; the status
    // line has to say so instead of inventing a range.
    expect(visibleSpaces({ row: 3, column: 3 }, 0)).toEqual([])
    expect(visibleSpaces({ row: 2, column: 4 }, 0)).toEqual([])
  })

  it('counts exactly the spaces whose turned cell falls inside the window', () => {
    for (const turns of [0, 1, 2, 3] as const) {
      for (const window of [
        { row: 1, column: 1 },
        { row: 5, column: 5 },
        { row: 1, column: 5 },
        { row: 4, column: 2 },
      ]) {
        const inside = BOARD.map((space) => space.index).filter((index) => {
          const { row, column } = cellFor(index, turns)
          return (
            row >= window.row &&
            row <= window.row + WINDOW_SIZE - 1 &&
            column >= window.column &&
            column <= window.column + WINDOW_SIZE - 1
          )
        })
        const shown = visibleSpaces(window, turns)
        expect([turns, window, [...shown].sort((left, right) => left - right)]).toEqual([
          turns,
          window,
          inside,
        ])
        // One arc on the circle: consecutive entries are consecutive spaces.
        const isArc = shown.every((index, position) =>
          position === 0 ? true : index === (shown[position - 1] + 1) % BOARD_SIZE,
        )
        expect([turns, window, isArc]).toEqual([turns, window, true])
        if (shown.length > 0) {
          // The list opens on the space whose predecessor is hidden.
          const before = (shown[0] + BOARD_SIZE - 1) % BOARD_SIZE
          expect([turns, window, shown.includes(before)]).toEqual([turns, window, false])
        }
      }
    }
  })
})

describe("the seat's window follows", () => {
  it('centres on the own cell when the player has not panned', () => {
    expect(seatWindow({ row: 6, column: 6 }, null)).toEqual({ row: 3, column: 3 })
    expect(seatWindow({ row: 11, column: 2 }, null)).toEqual({ row: 5, column: 1 })
  })

  it('keeps a manual pan while the own token has not moved', () => {
    // Looking somewhere else is legitimate: the window must not snap back on
    // the next render, only when the token itself moves (S8).
    const looking = { window: { row: 1, column: 1 }, at: { row: 6, column: 6 } }
    expect(seatWindow({ row: 6, column: 6 }, looking)).toEqual({ row: 1, column: 1 })
  })

  it('drops the manual pan when the own token moves', () => {
    const looking = { window: { row: 1, column: 1 }, at: { row: 6, column: 6 } }
    expect(seatWindow({ row: 9, column: 6 }, looking)).toEqual({ row: 5, column: 3 })
  })

  it('recentres on a focused space only when the window cut it off', () => {
    const window = { row: 1, column: 1 }
    expect(recentreForFocus(window, { row: 1, column: 1 })).toBeNull()
    expect(recentreForFocus(window, { row: 7, column: 7 })).toBeNull()
    // Every space the crop hides is one the keyboard can reach, so each of the
    // four sides has to move the window and none may leave the board.
    expect(recentreForFocus(window, { row: 11, column: 11 })).toEqual({ row: 5, column: 5 })
    expect(recentreForFocus(window, { row: 11, column: 1 })).toEqual({ row: 5, column: 1 })
    expect(recentreForFocus(window, { row: 1, column: 11 })).toEqual({ row: 1, column: 5 })
    expect(recentreForFocus(window, { row: 8, column: 2 })).toEqual({ row: 5, column: 1 })
    // A window over the empty middle shows no ring space at all, so a focused
    // space of the ring has to bring it back; a space of the middle itself is
    // inside the crop and must not move anything.
    expect(recentreForFocus({ row: 3, column: 3 }, { row: 6, column: 6 })).toBeNull()
    expect(recentreForFocus({ row: 3, column: 3 }, { row: 11, column: 4 })).toEqual({
      row: 5,
      column: 1,
    })
  })
})
