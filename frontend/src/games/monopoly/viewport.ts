/**
 * The seat's view of the board: how the table is turned and which window of it
 * the player is looking at (S4-S9 of ``monopoly-seat-viewport.md``).
 *
 * Two facts make this module pure arithmetic instead of geometry on pixels:
 *
 * 1. The ring of forty spaces is a square, so a quarter turn maps it onto
 *    itself. Turning the table is therefore a **shift of the circuit**, never a
 *    ``transform``: the cell a space lands in is the cell that space
 *    ``SHIFT_PER_TURN`` further along the circuit normally holds. That is what
 *    keeps every name and every token upright and horizontal.
 * 2. A window is just the origin of a ``WINDOW_SIZE`` square in grid
 *    coordinates, clamped so it never leaves the board. The stylesheet turns
 *    that origin into a translation; nothing here knows about pixels.
 *
 * The spectator has no window: it sees the whole board, which is exactly this
 * module used at zero turns and the untouched grid placement.
 */

import { BOARD_SIZE, spaceAt } from './board'
import { GRID_SIZE, spaceArea, spaceSide } from './grid'
import type { BoardSide, GridArea } from './grid'

/** Spaces between two corners: one quarter turn of the square ring. */
export const SHIFT_PER_TURN = 10

/** How many of the eleven cells a side the seat sees. */
export const WINDOW_SIZE = 7

/** Last legal window origin: the window is seven cells and the board eleven. */
const LAST_ORIGIN = GRID_SIZE - WINDOW_SIZE + 1

/** Half a window, the offset that centres a cell when the geometry allows it. */
const WINDOW_HALF = Math.floor(WINDOW_SIZE / 2)

/** The four sides of the ring, in the order a turn advances them. */
const SIDES: readonly BoardSide[] = ['bottom', 'left', 'top', 'right']

/** A quarter of a turn, counted clockwise. */
export type QuarterTurns = 0 | 1 | 2 | 3

/** Top-left corner of the visible window, in the board's own coordinates. */
export type ViewWindow = { row: number; column: number }

/** One step of the manual pan (S9). */
export type ViewDirection = 'up' | 'down' | 'left' | 'right'

/**
 * The cell the space at ``index`` sits in once the table is turned ``turns``
 * quarters (S4).
 *
 * The index is validated **before** the shift, so an out-of-range index throws
 * instead of wrapping into a legal one (``40`` would otherwise become GO).
 */
export function cellFor(index: number, turns: QuarterTurns): GridArea {
  spaceAt(index)
  return spaceArea((index + SHIFT_PER_TURN * turns) % BOARD_SIZE)
}

/**
 * The side of the ring the space belongs to after ``turns`` quarters (S4).
 *
 * The band of colour faces the centre of the board and the names on the two
 * side columns read vertically, both keyed off ``data-side``, so the side has
 * to turn with the cell or the skin would point outwards on two edges.
 */
export function sideFor(index: number, turns: QuarterTurns): BoardSide {
  spaceAt(index)
  const side = SIDES.indexOf(spaceSide(index))
  return SIDES[(side + turns) % SIDES.length]
}

/** ``turns`` advanced by ``step`` quarters, wrapped in both directions (S6). */
export function nextTurns(turns: QuarterTurns, step: number): QuarterTurns {
  return ((((turns + step) % 4) + 4) % 4) as QuarterTurns
}

/**
 * The orientation a seat starts at (S5).
 *
 * Every seat begins on GO, so where a player stands cannot choose an
 * orientation; the seat order does, the way people take a side of a real table.
 * Seat 0 keeps the printed orientation, and with eight seats two share a side.
 */
export function startTurns(seatIndex: number): QuarterTurns {
  return nextTurns(0, seatIndex)
}

/** Clamp a window origin to the board. */
function clampOrigin(value: number): number {
  return Math.min(Math.max(value, 1), LAST_ORIGIN)
}

/**
 * The window that centres on ``area`` as much as the board allows (S8).
 *
 * A cell on an edge cannot be centred -- there is no board beyond it -- so the
 * window sticks to that edge and the cell sits three cells in.
 */
export function windowAround(area: GridArea): ViewWindow {
  return {
    row: clampOrigin(area.row - WINDOW_HALF),
    column: clampOrigin(area.column - WINDOW_HALF),
  }
}

/** Whether one step in ``direction`` stays on the board (S9). */
export function canMoveWindow(window: ViewWindow, direction: ViewDirection): boolean {
  if (direction === 'up') return window.row > 1
  if (direction === 'down') return window.row < LAST_ORIGIN
  if (direction === 'left') return window.column > 1
  return window.column < LAST_ORIGIN
}

/** ``window`` moved one cell, clamped so it can never leave the board (S9). */
export function moveWindow(window: ViewWindow, direction: ViewDirection): ViewWindow {
  if (!canMoveWindow(window, direction)) return window
  if (direction === 'up') return { row: window.row - 1, column: window.column }
  if (direction === 'down') return { row: window.row + 1, column: window.column }
  if (direction === 'left') return { row: window.row, column: window.column - 1 }
  return { row: window.row, column: window.column + 1 }
}

/** Whether ``area`` falls inside ``window``. */
function covers(window: ViewWindow, area: GridArea): boolean {
  const lastRow = window.row + WINDOW_SIZE - 1
  const lastColumn = window.column + WINDOW_SIZE - 1
  return (
    area.row >= window.row &&
    area.row <= lastRow &&
    area.column >= window.column &&
    area.column <= lastColumn
  )
}

/**
 * The spaces the window shows, in circuit order (S12).
 *
 * The answer is an arc of the ring, and it can cross GO: the bottom-right
 * window holds the right column's tail followed by the bottom row's head. The
 * list therefore **opens on the space whose predecessor is hidden**, so it
 * always reads as one run of consecutive spaces and never as "34 to 6".
 *
 * An empty list means the window is over the empty middle of the board: panning
 * inward can leave a seven-cell window on the centre of the table, and the
 * status line has to say that instead of inventing a range.
 */
export function visibleSpaces(window: ViewWindow, turns: QuarterTurns): number[] {
  const shown: number[] = []
  for (let index = 0; index < BOARD_SIZE; index += 1) {
    if (covers(window, cellFor(index, turns))) shown.push(index)
  }
  if (shown.length === 0) return shown
  const opens = shown.findIndex(
    (index) => !shown.includes((index + BOARD_SIZE - 1) % BOARD_SIZE),
  )
  if (opens <= 0) return shown
  return [...shown.slice(opens), ...shown.slice(0, opens)]
}
