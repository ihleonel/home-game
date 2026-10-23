import type { Game } from '../api/types'

export type GuestIdentity = { displayName: string; gameMarker: string }

export type RoomSession = GuestIdentity & {
  gameId: string
  sessionId: string
  participantRef: string
  isReady: boolean
}

export type StoredRoomSession = Pick<RoomSession, 'gameId' | 'sessionId' | 'isReady'> & {
  /**
   * Whether the guest typed this session's identity. A platform-assigned
   * spectator identity belongs to the room only: it is never remembered as
   * this browser's own name and marker for a later room.
   */
  rememberIdentity: boolean
}

const DISPLAY_NAME_KEY = 'homegame:display-name'
const ROOM_SESSION_KEY = 'homegame:room-session'

export function readSessionValue(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeSessionValue(key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    // The flow remains usable for this page even when browser storage is unavailable.
  }
}

function markerStorageKey(gameId: string): string {
  return `homegame:marker:${gameId}`
}

export function readStoredIdentity(game: Game): GuestIdentity {
  const savedMarker = readSessionValue(markerStorageKey(game.id))
  return {
    displayName: readSessionValue(DISPLAY_NAME_KEY) ?? '',
    gameMarker:
      savedMarker && game.markers.some((marker) => marker.id === savedMarker)
        ? savedMarker
        : '',
  }
}

export function readStoredRoomSession(gameId: string): StoredRoomSession | null {
  const savedSession = readSessionValue(ROOM_SESSION_KEY)
  if (!savedSession) return null

  try {
    const session = JSON.parse(savedSession) as Partial<StoredRoomSession>
    if (session.gameId !== gameId || typeof session.sessionId !== 'string') return null
    return {
      gameId,
      sessionId: session.sessionId,
      isReady: session.isReady === true,
      rememberIdentity: session.rememberIdentity !== false,
    }
  } catch {
    return null
  }
}

export function saveGuestSession(
  session: RoomSession,
  options: { rememberIdentity?: boolean } = {},
): void {
  const rememberIdentity = options.rememberIdentity ?? true
  if (rememberIdentity) {
    writeSessionValue(DISPLAY_NAME_KEY, session.displayName)
    writeSessionValue(markerStorageKey(session.gameId), session.gameMarker)
  }
  writeSessionValue(
    ROOM_SESSION_KEY,
    JSON.stringify({
      gameId: session.gameId,
      sessionId: session.sessionId,
      isReady: session.isReady,
      rememberIdentity,
    } satisfies StoredRoomSession),
  )
}
