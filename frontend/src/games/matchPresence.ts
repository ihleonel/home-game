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
 *
 * ``remaining_seconds`` is read just as defensively (S8): only a whole number
 * greater than or equal to zero survives; a string, a decimal, a negative or a
 * missing value becomes ``null``, so a bad payload costs the number, not the
 * screen.
 */
export function parseSeatPresence(value: unknown): SeatPresence[] | null {
  if (!Array.isArray(value)) return null
  const seats: SeatPresence[] = []
  for (const entry of value) {
    if (typeof entry !== 'object' || entry === null) continue
    const candidate = entry as {
      index?: unknown
      presence?: unknown
      remaining_seconds?: unknown
    }
    if (typeof candidate.index !== 'number' || !Number.isInteger(candidate.index)) continue
    const presence = candidate.presence
    if (presence !== 'online' && presence !== 'reconnecting' && presence !== 'inactive') {
      continue
    }
    const remainingSeconds = candidate.remaining_seconds
    seats.push({
      index: candidate.index,
      presence,
      remaining_seconds:
        typeof remainingSeconds === 'number' &&
        Number.isInteger(remainingSeconds) &&
        remainingSeconds >= 0
          ? remainingSeconds
          : null,
    })
  }
  return seats
}
