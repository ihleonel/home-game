import type { MatchEnvelope } from '../api/types'
import { parseMatchRoster } from '../games/matchRoster'
import type { MatchSeatRosterEntry } from '../games/matchRoster'
import type { MatchState, MatchView } from '../games/registry'

/**
 * Apply a resync response over the current match.
 *
 * The current match must still be the one the response is for, and an older
 * version never overwrites a newer one, so a slow resync cannot regress the
 * view a WebSocket event already advanced.
 *
 * The roster is refreshed only when the response carries one: a frame that
 * omits it leaves the identity already on screen untouched (S2/S5).
 */
export function mergeMatch(
  current: MatchState | null,
  incoming: MatchEnvelope,
): MatchState | null {
  if (!current || current.matchRef !== incoming.match_ref) return current
  if (current.version !== null && incoming.version < current.version) return current
  return {
    matchRef: incoming.match_ref,
    seatIndex: incoming.seat_index,
    version: incoming.version,
    roster: parseMatchRoster(incoming.roster) ?? current.roster,
    view: incoming.view,
  }
}

/**
 * Apply a ``match.event`` over the current match.
 *
 * Events for any match that is not the current one are ignored, as are events
 * whose version is older than the one already held. The view itself is kept
 * exactly as the server sent it; nothing here derives a game fact.
 */
export function mergeMatchEvent(
  current: MatchState | null,
  matchRef: string,
  version: number | null,
  view: MatchView,
  roster?: MatchSeatRosterEntry[],
): MatchState | null {
  if (!current || current.matchRef !== matchRef) return current
  if (version !== null && current.version !== null && version < current.version) {
    return current
  }
  return {
    ...current,
    version: version ?? current.version,
    roster: parseMatchRoster(roster) ?? current.roster,
    view,
  }
}
