/**
 * Where each space of the circuit sits on the 11x11 board.
 *
 * The printed board is a square ring: the perimeter holds exactly the 40
 * spaces and the middle 9x9 stays free. GO is the bottom-right corner and the
 * circuit runs clockwise -- right to left along the bottom, up the left side,
 * left to right along the top and down the right side -- which is the direction
 * the printed board's arrow points and the direction the rules move a token in.
 *
 * The corners are ten spaces apart, so a spot is described by which corner its
 * segment starts at and how far along that segment it is. Keeping the
 * arithmetic (instead of a 40-entry table) means the placement cannot disagree
 * with the circuit order it is derived from, and ``grid.test.ts`` pins the
 * corners and one space per side.
 */

import { BOARD_SIZE, spaceAt } from './board'

/** Rows and columns are 1..GRID_SIZE, row 1 being the top row. */
export const GRID_SIZE = 11

/** Spaces between two corners: the four sides of the ring. */
const SIDE_LENGTH = GRID_SIZE - 2

/** Distance between two corners: a side plus the corner itself. */
const CORNER_STEP = SIDE_LENGTH + 1

export type GridArea = { row: number; column: number }

/** The four corners, in circuit order, as ``[row, column]``. */
const CORNERS: readonly (readonly [number, number])[] = [
  [GRID_SIZE, GRID_SIZE],
  [GRID_SIZE, 1],
  [1, 1],
  [1, GRID_SIZE],
]

/**
 * Return the row and column of the space at ``index``.
 *
 * Throws for an index outside the circuit, delegating the validation to
 * ``spaceAt`` so the grid and the board cannot disagree about what a valid
 * index is.
 */
export function spaceArea(index: number): GridArea {
  spaceAt(index)
  const corner = Math.floor(index / CORNER_STEP)
  const offset = index % CORNER_STEP
  const [cornerRow, cornerColumn] = CORNERS[corner]
  if (corner === 0) return { row: cornerRow, column: cornerColumn - offset }
  if (corner === 1) return { row: cornerRow - offset, column: cornerColumn }
  if (corner === 2) return { row: cornerRow, column: cornerColumn + offset }
  return { row: cornerRow + offset, column: cornerColumn }
}

/** The perimeter size this grid can address, for the invariant the board keeps. */
export const BOARD_CAPACITY = 4 * CORNER_STEP

if (BOARD_CAPACITY !== BOARD_SIZE) {
  throw new Error(
    `the ${GRID_SIZE}x${GRID_SIZE} grid holds ${BOARD_CAPACITY} spaces, not ${BOARD_SIZE}`,
  )
}
