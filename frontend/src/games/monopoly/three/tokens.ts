/**
 * Which pieces the 3D table must draw, and in which seat tone.
 *
 * The scene paints one chip per seat still in the match. Three facts decide what
 * that chip looks like, and this module is the single place that reads them:
 *
 * 1. **The seat** comes from ``view.players`` -- the server says who is still
 *    playing, and an eliminated seat keeps no piece on the board.
 * 2. **The silhouette** comes from the roster's ``game_marker``, which is the
 *    player's own choice in the room, through ``figureFor``.
 * 3. **The tone** comes from the roster's ``index``, through the same palette the
 *    2D board, the owner badge and the players list paint. It is never derived
 *    from the marker or from the seat id: a marker is not unique per room, and
 *    the seat id is an opaque string.
 *
 * It is deliberately pure and free of ``three``, so the DOM-less harness can pin
 * the mapping while the canvas painting stays with the visual review, which is
 * the split ``figureTexture.ts`` already documents.
 */

import type { MatchState } from '../../registry'
import { seatTone } from '../display'
import type { MonopolyView } from '../view'
import { figureFor } from './figures'
import type { PieceFigure } from './figures'

/** One piece to draw on the 3D board. */
export type SeatedToken = {
  seat: string
  figure: PieceFigure
  tone: string | null
}

/**
 * What a seat the roster cannot name gets: the neutral counter and no tone.
 *
 * It is a named constant and not an inline fallback because it is the honest
 * answer, not a default that hides a bug: the server placed the seat on the
 * board, so the piece is drawn, and the colour is the only thing withheld.
 */
export const SEATED_TONE_FALLBACK: SeatedToken = {
  seat: '',
  figure: 'ficha',
  tone: null,
}

/** The pieces the 3D table draws, one per seat still in the match. */
export function seatedTokens(match: MatchState<MonopolyView>): SeatedToken[] {
  return match.view.players
    .filter((player) => !player.eliminated)
    .map((player) => {
      const entry = match.roster.find((candidate) => candidate.seat_id === player.seat)
      return {
        seat: player.seat,
        figure: entry === undefined ? SEATED_TONE_FALLBACK.figure : figureFor(entry.game_marker),
        tone: seatTone(entry === undefined ? null : entry.index),
      }
    })
}
