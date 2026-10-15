import type { MatchRuntimeView } from '../registry'

/**
 * One resolved round exactly as ``duelo`` reports it.
 *
 * ``picks`` is keyed by seat id and ``winner`` is a seat id or ``null`` for a
 * draw. The client never derives either value; it only renders them.
 */
export type DueloReveal = {
  round: number
  picks: Record<string, string>
  winner: string | null
}

/**
 * The ``duelo`` play payload, on top of the runtime fields every view carries.
 *
 * ``you``, ``winner``, ``finished`` and ``ended_by_abandon`` stay in
 * :type:`MatchRuntimeView` because the match screen reads them for every game.
 * Everything declared here belongs to ``duelo`` and nowhere else: a second game
 * declares its own view beside it instead of widening a shared one.
 *
 * A seat receives ``your_pick`` and ``opponent_has_picked``; a spectator
 * receives ``both_picked`` instead. Every optional field is optional because
 * the runtime already decides which projection a caller gets, and the client
 * must not fill a missing one in by guessing.
 */
export type DueloView = MatchRuntimeView & {
  round: number
  scores: Record<string, number>
  your_pick?: string | null
  opponent_has_picked?: boolean
  both_picked?: boolean
  reveal: DueloReveal | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Read a round number without trusting its shape: a whole, non-negative number or nothing. */
function readRound(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) return null
  return value
}

/** Read a seat-id keyed map of whole numbers without trusting its shape. */
function readScores(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) return null
  const scores: Record<string, number> = {}
  for (const [seatId, score] of Object.entries(value)) {
    if (typeof score !== 'number' || !Number.isInteger(score)) return null
    scores[seatId] = score
  }
  return scores
}

/** Read one resolved round without trusting its shape. */
function readReveal(value: unknown): DueloReveal | null {
  if (!isRecord(value)) return null
  const round = readRound(value.round)
  if (round === null) return null
  if (!isRecord(value.picks)) return null
  const picks: Record<string, string> = {}
  for (const [seatId, pick] of Object.entries(value.picks)) {
    if (typeof pick !== 'string') return null
    picks[seatId] = pick
  }
  const winner = value.winner
  if (!(winner === null || typeof winner === 'string')) return null
  return { round, picks, winner }
}

/**
 * Read the raw payload the runtime projected as a ``duelo`` view.
 *
 * ``null`` means the payload is **not** a ``duelo`` view: it is not an object,
 * or it is missing one of the fields that identify it -- the runtime fields
 * every view carries (``finished``, ``winner``) plus ``duelo``'s own
 * ``round`` and ``scores``. The caller falls back to its own notice instead of
 * rendering a panel over bytes the game never recognized, which is the defect
 * this parser exists to prevent.
 *
 * Past those identifiers it degrades instead of rejecting, exactly as the
 * roster and presence parsers do: a malformed optional field costs that field,
 * never the whole match screen. A malformed ``reveal`` becomes ``null``, and
 * an optional field of the wrong type is left out so the component's own
 * fallback covers it.
 */
export function parseDueloView(raw: unknown): DueloView | null {
  if (!isRecord(raw)) return null

  const finished = raw.finished
  if (typeof finished !== 'boolean') return null

  const winner = raw.winner
  if (!(winner === null || typeof winner === 'string')) return null

  const round = readRound(raw.round)
  if (round === null) return null

  const scores = readScores(raw.scores)
  if (scores === null) return null

  const view: DueloView = { round, scores, winner, finished, reveal: readReveal(raw.reveal) }

  if (typeof raw.you === 'string') view.you = raw.you
  if (raw.your_pick === null || typeof raw.your_pick === 'string') {
    view.your_pick = raw.your_pick
  }
  if (typeof raw.opponent_has_picked === 'boolean') {
    view.opponent_has_picked = raw.opponent_has_picked
  }
  if (typeof raw.both_picked === 'boolean') view.both_picked = raw.both_picked
  if (typeof raw.ended_by_abandon === 'boolean') {
    view.ended_by_abandon = raw.ended_by_abandon
  }

  return view
}
