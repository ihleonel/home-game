import type { Room } from '../api/types'
import type { GuestIdentity } from './session'

/**
 * The rejection the ordinary entry keeps when the identity is incomplete.
 *
 * A spectator entry never sees it: the platform assigns whatever the guest did
 * not type, so the shared form can offer the spectator action without asking
 * for a ficha.
 */
export const MISSING_IDENTITY_MESSAGE =
  'Escribe un nombre y elige una ficha para continuar.'

export type MembershipRequest = {
  game_id: string
  display_name?: string
  game_marker?: string
  session_id?: string
  as_spectator?: true
}

export function identityProblem(
  identity: GuestIdentity,
  options?: { asSpectator?: boolean },
): string | null {
  if (options?.asSpectator) return null
  if (!identity.displayName.trim() || !identity.gameMarker) {
    return MISSING_IDENTITY_MESSAGE
  }
  return null
}

/**
 * The REST body for one room entry.
 *
 * An empty identity is omitted rather than sent blank: the backend then
 * assigns one for the spectator, and a supplied value travels trimmed exactly
 * as it did before.
 */
export function buildMembershipRequest(
  gameId: string,
  identity: GuestIdentity,
  options: { asSpectator?: boolean; sessionId?: string } = {},
): MembershipRequest {
  const displayName = identity.displayName.trim()
  return {
    game_id: gameId,
    ...(displayName ? { display_name: displayName } : {}),
    ...(identity.gameMarker ? { game_marker: identity.gameMarker } : {}),
    ...(options.sessionId ? { session_id: options.sessionId } : {}),
    ...(options.asSpectator ? { as_spectator: true as const } : {}),
  }
}

/**
 * The identity this session actually holds in the room.
 *
 * The server is authoritative: an anonymous spectator is named and given a
 * marker there, so the screen reads them back from the snapshot instead of
 * keeping the empty draft it submitted.
 */
export function resolveAssignedIdentity(
  room: Room,
  participantRef: string,
  fallback: GuestIdentity,
): GuestIdentity {
  const participant = room.participants.find(
    (entry) => entry.participant_ref === participantRef,
  )
  if (!participant) return fallback
  return {
    displayName: participant.display_name,
    gameMarker: participant.game_marker,
  }
}
