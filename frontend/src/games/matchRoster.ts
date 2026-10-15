/**
 * The public identity the server projects for one seat of a match.
 *
 * It mirrors exactly the backend roster entry (S1): the seat id, its index,
 * the participant's current ``display_name`` and its marker id and resolved
 * label. The label is resolved centrally by the server, so the client never
 * maps ``game_marker`` to a label itself (S4).
 */
export type MatchSeatRosterEntry = {
  seat_id: string
  index: number
  display_name: string
  game_marker: string
  game_marker_label: string
}

/**
 * Parse the ``roster`` field of a match frame without trusting its shape.
 *
 * A frame the server never promised (wrong type, missing field, an unknown
 * value) is dropped entry by entry instead of throwing, so a malformed update
 * can never blank the match screen. ``null`` means the frame carried no usable
 * ``roster`` array at all; an empty array is a valid, explicit "no roster".
 */
export function parseMatchRoster(value: unknown): MatchSeatRosterEntry[] | null {
  if (!Array.isArray(value)) return null
  const roster: MatchSeatRosterEntry[] = []
  for (const entry of value) {
    if (typeof entry !== 'object' || entry === null) continue
    const candidate = entry as {
      seat_id?: unknown
      index?: unknown
      display_name?: unknown
      game_marker?: unknown
      game_marker_label?: unknown
    }
    if (
      typeof candidate.seat_id !== 'string' ||
      typeof candidate.index !== 'number' ||
      !Number.isInteger(candidate.index) ||
      typeof candidate.display_name !== 'string' ||
      typeof candidate.game_marker !== 'string' ||
      typeof candidate.game_marker_label !== 'string'
    ) {
      continue
    }
    roster.push({
      seat_id: candidate.seat_id,
      index: candidate.index,
      display_name: candidate.display_name,
      game_marker: candidate.game_marker,
      game_marker_label: candidate.game_marker_label,
    })
  }
  return roster
}
