/**
 * Which cells of the printed board belong to a seat, and in which tone their
 * frame glows.
 *
 * The scene paints the forty faces once and keeps them, so it needs one cheap
 * fact to know when a face must be repainted: the owner of every cell, in the
 * same ink the 2D board's badge and the players list already use. This module
 * is the single place that reads it, and it is deliberately free of ``three``
 * and of the DOM so the harness can pin the mapping while the canvas painting
 * stays with the visual review (``textures.ts``).
 *
 * Two facts are never derived from each other:
 *
 * 1. **Ownership** comes from ``view.owners`` -- the server says which space the
 *    bank sold, keyed by the space's index because the state is ``jsonb``.
 * 2. **The ink** comes from the owning seat's roster ``index``, through the same
 *    palette the 2D board paints. A seat the roster cannot name keeps the frame
 *    and loses only the colour: ``ink`` is ``null``, never a made-up tone.
 */

import { BOARD } from '../board'
import { seatIndexOf, seatTone } from '../display'
import type { MatchState } from '../../registry'
import type { MonopolyView } from '../view'

/** One cell the bank no longer owns, as the scene needs it. */
export type OwnedCell = {
  /** The index on the circuit, which is also the key of ``view.owners``. */
  index: number
  /**
   * The owning seat's tone, or ``null`` when the roster cannot name that seat.
   *
   * ``null`` is not a fallback colour: it is the honest answer, and the painter
   * uses neutral ink for it so ownership is still marked without claiming an
   * identity.
   */
  ink: string | null
}

/**
 * Every cell a seat owns, in board order.
 *
 * It walks ``BOARD`` instead of the ``owners`` map on purpose: the map is
 * whatever the server serialised, and an index outside the circuit is not a
 * cell of this board, so it can never make the scene paint a face that does not
 * exist.
 */
export function ownedCells(match: MatchState<MonopolyView>): OwnedCell[] {
  return BOARD.flatMap((space) => {
    const seat = match.view.owners[String(space.index)]
    if (seat === undefined) return []
    return [{ index: space.index, ink: seatTone(seatIndexOf(match.roster, seat)) }]
  })
}

/**
 * A stable key for what the forty faces are painted from.
 *
 * The board polls, so ``match`` is a fresh object on every answer and an owner
 * map rebuilt from the same JSON is not the same object twice. This string is:
 * two boards with the same owners have the same key, and any purchase, sale or
 * change of hands produces a different one -- which is exactly when the scene
 * has to repaint a face.
 */
export function ownerSignature(cells: readonly OwnedCell[]): string {
  return cells.map((cell) => `${cell.index}:${cell.ink ?? ''}`).join(',')
}
