import type { MatchRuntimeView } from '../registry'

/**
 * The ``ta-te-ti`` mark the server assigned to one seat.
 *
 * It is cosmetic at the board level: ``X`` belongs to the first seat and ``O``
 * to the second, and the room's chosen ficha never changes it (S2).
 */
export type TaTeTiSymbol = 'X' | 'O'

/**
 * The ``ta-te-ti`` play payload, on top of the runtime fields every view carries.
 *
 * ``you``, ``winner``, ``finished`` and ``ended_by_abandon`` stay in
 * :type:`MatchRuntimeView` because the match screen reads them for every game.
 * Everything declared here belongs to ``ta-te-ti`` and nowhere else: a second
 * game declares its own view beside it instead of widening a shared one (S6).
 *
 * The board is public: a seat and a spectator see the same nine cells, the same
 * turn and the same symbols, and only ``you`` differs. ``turn`` is ``null``
 * when the match is over, and ``winner_line`` is the three winning cell indices
 * or ``null``.
 */
export type TaTeTiView = MatchRuntimeView & {
  board: (string | null)[]
  turn: string | null
  symbols: Record<string, TaTeTiSymbol>
  winner_line: number[] | null
}

/** The nine cells of a ta-te-ti board, row by row (S2). */
const BOARD_SIZE = 9

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Read a nine-cell board without trusting its shape: each cell is a seat id or empty. */
function readBoard(value: unknown): (string | null)[] | null {
  if (!Array.isArray(value) || value.length !== BOARD_SIZE) return null
  const board: (string | null)[] = []
  for (const cell of value) {
    if (!(cell === null || typeof cell === 'string')) return null
    board.push(cell)
  }
  return board
}

/** Read a seat-id keyed symbol map without trusting its shape. */
function readSymbols(value: unknown): Record<string, TaTeTiSymbol> | null {
  if (!isRecord(value)) return null
  const symbols: Record<string, TaTeTiSymbol> = {}
  for (const [seatId, symbol] of Object.entries(value)) {
    if (symbol !== 'X' && symbol !== 'O') return null
    symbols[seatId] = symbol
  }
  return symbols
}

/** Read the optional turn as a seat id, dropping anything else to ``null``. */
function readTurn(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

/** Read the optional winning line: exactly three cell indices, or nothing. */
function readWinnerLine(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length !== 3) return null
  const line: number[] = []
  for (const index of value) {
    if (typeof index !== 'number' || !Number.isInteger(index) || index < 0) return null
    line.push(index)
  }
  return line
}

/**
 * Read the raw payload the runtime projected as a ``ta-te-ti`` view.
 *
 * ``null`` means the payload is **not** a ``ta-te-ti`` view: it is not an
 * object, or it is missing one of the fields that identify it -- the runtime
 * fields every view carries (``finished``, ``winner``) plus ``ta-te-ti``'s own
 * ``board`` and ``symbols``. The caller falls back to its own notice instead of
 * rendering a panel over bytes the game never recognized, which is the defect
 * this parser exists to prevent.
 *
 * Past those identifiers it degrades instead of rejecting, exactly as the
 * roster and presence parsers do: a malformed optional field costs that field,
 * never the whole match screen. A malformed ``turn`` or ``winner_line``
 * becomes ``null``, and an optional field of the wrong type is left out so the
 * component's own fallback covers it.
 */
export function parseTaTeTiView(raw: unknown): TaTeTiView | null {
  if (!isRecord(raw)) return null

  const finished = raw.finished
  if (typeof finished !== 'boolean') return null

  const winner = raw.winner
  if (!(winner === null || typeof winner === 'string')) return null

  const board = readBoard(raw.board)
  if (board === null) return null

  const symbols = readSymbols(raw.symbols)
  if (symbols === null) return null

  const view: TaTeTiView = {
    board,
    turn: readTurn(raw.turn),
    symbols,
    winner_line: readWinnerLine(raw.winner_line),
    winner,
    finished,
  }

  if (typeof raw.you === 'string') view.you = raw.you
  if (typeof raw.ended_by_abandon === 'boolean') {
    view.ended_by_abandon = raw.ended_by_abandon
  }

  return view
}
