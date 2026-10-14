import { ApiError, requestJson } from './client'
import type { Room, RoomEnvelope } from './types'

/**
 * Read the active room of a game, or of one session inside that game.
 *
 * A room that does not exist is ``null``, not an error: the caller decides
 * whether that means "show the catalog" or "reconnect".
 */
export async function fetchActiveRoom(
  gameId: string,
  sessionId?: string,
): Promise<Room | null> {
  try {
    const query = new URLSearchParams(
      sessionId ? { session_id: sessionId } : { game_id: gameId },
    )
    const response = await requestJson<RoomEnvelope>(`/api/rooms/active/?${query.toString()}`)
    return response.room
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}
