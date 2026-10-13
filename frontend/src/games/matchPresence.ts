import { createContext, useContext } from 'react'
import type { SeatPresence } from '../api/types'

/**
 * The seat presence of the match currently on screen.
 *
 * It lives next to the match rather than inside the room session because it
 * belongs to one match: a new match starts with no presence and the provider
 * clears it when the match changes. The default is empty, so a screen rendered
 * without the provider simply announces nothing.
 */
export const MatchPresenceContext = createContext<SeatPresence[]>([])

export function useMatchPresence(): SeatPresence[] {
  return useContext(MatchPresenceContext)
}

/**
 * Parse the ``seats`` field of a match frame without trusting its shape.
 *
 * A frame the server never promised (wrong type, missing field, an unknown
 * presence value) is dropped entry by entry instead of throwing, so a
 * malformed update can never blank the match screen. ``null`` means the frame
 * carried no usable ``seats`` array at all; an empty array is a valid,
 * explicit "no seats".
 */
export function parseSeatPresence(value: unknown): SeatPresence[] | null {
  if (!Array.isArray(value)) return null
  const seats: SeatPresence[] = []
  for (const entry of value) {
    if (typeof entry !== 'object' || entry === null) continue
    const candidate = entry as { index?: unknown; presence?: unknown }
    if (typeof candidate.index !== 'number' || !Number.isInteger(candidate.index)) continue
    const presence = candidate.presence
    if (presence !== 'online' && presence !== 'reconnecting' && presence !== 'inactive') {
      continue
    }
    seats.push({ index: candidate.index, presence })
  }
  return seats
}
