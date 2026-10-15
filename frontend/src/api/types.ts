import type { MatchRuntimeView } from '../games/registry'
import type { MatchSeatRosterEntry } from '../games/matchRoster'

/**
 * The presence of one seat of the running match.
 *
 * It is the runtime's public projection (S6): it never carries a pick or any
 * other hidden play, only whether the seat's socket is still there.
 *
 * ``remaining_seconds`` is the reconnect window the server still grants that
 * seat, in seconds. The server computes it (S8) so the screen never depends on
 * the browser clock; it is ``null`` for an ``online`` or already ``inactive``
 * seat, and also when the server sent no usable value.
 */
export type SeatPresence = {
  index: number
  presence: 'online' | 'reconnecting' | 'inactive'
  remaining_seconds: number | null
}

export type Marker = { id: string; label: string }

export type Game = {
  id: string
  label: string
  description: string
  markers: Marker[]
}

export type Participant = {
  participant_ref: string
  display_name: string
  game_marker: string
  /**
   * The room role the backend resolved for this participant (S1/S2). A
   * ``spectator`` does not occupy a seat, cannot be marked ready and is not
   * an expulsion-vote target.
   */
  role: 'player' | 'spectator'
  is_ready: boolean
  presence: 'offline' | 'online' | 'reconnecting' | 'inactive'
  /**
   * The reconnect window the server still grants this participant, in whole
   * seconds. The server computes it so the roster never depends on the browser
   * clock (S8); ``null`` for a participant that is not reconnecting inside its
   * window, and also when the server sent no usable value.
   */
  remaining_seconds: number | null
  disconnected_at: string | null
  joined_at: string
}

export type ExpulsionBallot = {
  participant_ref: string
  display_name: string
  choice: 'yes' | 'no' | null
}

export type ExpulsionVote = {
  vote_ref: string
  target_ref: string
  target_display_name: string
  started_by_ref: string
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  resolution_reason: string
  started_at: string
  resolved_at: string | null
  eligible_count: number
  yes_count: number
  no_count: number
  ballots: ExpulsionBallot[]
}

export type Room = {
  game_id: string
  status: string
  created_at: string
  updated_at: string
  participants: Participant[]
  expulsion_vote: ExpulsionVote | null
  /**
   * The seat capacity resolved from the game registry for this room (S6), so
   * the lobby can offer the spectator's promotion without guessing. It is
   * ``null`` for an unknown ``game_id``.
   */
  seat_limits: { min_seats: number; max_seats: number } | null
}

export type RoomEnvelope = { room: Room }

export type MembershipResponse = RoomEnvelope & {
  session_id: string
  participant_ref: string
}

export type VoteResponse = RoomEnvelope & { vote: ExpulsionVote }

export type RoomIntent = 'create' | 'join'

export type MatchEnvelope = {
  match_ref: string
  version: number
  status: string
  seat_index: number | null
  /**
   * The public seat identity the server resolves for the match (S1/S2). It is
   * additive: a response that does not carry it leaves the on-screen roster
   * untouched. The client only renders it (S4).
   */
  roster?: MatchSeatRosterEntry[]
  view: MatchRuntimeView
}

/**
 * The ``countdown`` payload shared by both countdown frames.
 *
 * ``match_countdown`` carries the total and remaining seconds;
 * ``match_countdown_cancelled`` carries only a reason.
 */
export type CountdownFrame = {
  seconds?: number
  remaining_seconds?: number
  reason?: string
}

/**
 * Every frame the room socket can send.
 *
 * A room frame carries ``room`` (and optionally ``vote``); a match frame
 * carries ``match_ref`` and ``view``. They share one socket, so the client
 * branches on ``type`` instead of assuming a room shape.
 */
export type ServerMessage = {
  type?: string
  room?: Room
  vote?: ExpulsionVote
  countdown?: CountdownFrame
  match_ref?: string
  seat_index?: number | null
  version?: number
  view?: MatchRuntimeView
  seats?: SeatPresence[]
  /**
   * The public seat identity of a ``match.snapshot`` frame (S2). It is
   * additive and optional: frames that do not carry it keep whatever roster
   * the match already had.
   */
  roster?: MatchSeatRosterEntry[]
}
