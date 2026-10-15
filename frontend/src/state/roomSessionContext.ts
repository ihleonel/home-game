import { createContext, useContext } from 'react'
import type {
  ExpulsionBallot,
  ExpulsionVote,
  Game,
  Participant,
  Room,
  RoomIntent,
} from '../api/types'
import type { MatchState } from '../games/registry'
import type { GuestIdentity, RoomSession } from '../lib/session'

/**
 * The shared lobby countdown this client is currently ticking.
 *
 * ``runId`` identifies the run this state belongs to, so a tick scheduled by
 * an older run can never decrement a newer one. The live sentence is announced
 * from ``seconds`` (the stable total), never from the decrementing
 * ``remainingSeconds``, so assistive tech is not told the whole sentence every
 * second.
 */
export type MatchCountdown = {
  runId: number
  seconds: number
  remainingSeconds: number
}

/**
 * The action one request is currently in flight for, or ``null``.
 *
 * ``match`` is the marker for a match action: the specific action name belongs
 * to the game's own screen, so the room-level union does not list it.
 */
export type PendingAction =
  | RoomIntent
  | 'ready'
  | 'leave'
  | 'vote'
  | 'play'
  | 'match'
  | null

/**
 * How a create-or-join attempt ended.
 *
 * ``joined`` entered the room, ``conflict`` means the server refused because
 * the room moved under this client (404/409) and the caller should resync, and
 * ``rejected`` is every other failure, including a draft the server never saw.
 */
export type CreateOrJoinOutcome = 'joined' | 'rejected' | 'conflict'

export type RoomSessionContextValue = {
  room: Room | null
  roomSession: RoomSession | null
  match: MatchState | null
  countdown: MatchCountdown | null
  countdownNotice: string | null
  voteNotice: string | null
  connectionError: string | null
  actionError: string | null
  busy: boolean
  pendingAction: PendingAction
  isJoined: boolean
  currentParticipant: Participant | undefined
  activeExpulsionVote: ExpulsionVote | null
  currentBallot: ExpulsionBallot | undefined
  allReady: boolean
  ownReady: boolean
  activeMatch: MatchState | null
  matchInProgress: boolean
  matchRendererAvailable: boolean
  createOrJoin: (
    intent: RoomIntent,
    game: Game,
    identity: GuestIdentity,
    options?: { asSpectator?: boolean },
  ) => Promise<CreateOrJoinOutcome>
  toggleReady: () => Promise<void>
  requestPlayerSeat: () => Promise<void>
  leaveRoom: () => Promise<void>
  startExpulsionVote: (targetRef: string) => Promise<void>
  castExpulsionBallot: (voteRef: string, choice: 'yes' | 'no') => Promise<void>
  submitAction: (name: string, value: string | null) => Promise<void>
  submitPick: (value: string) => Promise<void>
  setActionError: (message: string | null) => void
}

export const RoomSessionContext = createContext<RoomSessionContextValue | null>(null)

export function useRoomSession(): RoomSessionContextValue {
  const value = useContext(RoomSessionContext)
  if (value === null) {
    throw new Error('useRoomSession must be used inside a RoomSessionProvider.')
  }
  return value
}
