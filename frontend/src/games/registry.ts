import { createElement } from 'react'
import type { ComponentType, ReactElement } from 'react'
import { DueloMatch } from './duelo/DueloMatch'

/**
 * One resolved round exactly as the server reports it.
 *
 * ``picks`` is keyed by seat id and ``winner`` is a seat id or ``null`` for a
 * draw. The client never derives either value; it only renders them.
 */
export type MatchReveal = {
  round: number
  picks: Record<string, string>
  winner: string | null
}

/**
 * The seat-scoped or spectator ``view`` the match runtime returns.
 *
 * A seat receives ``you``, ``your_pick`` and ``opponent_has_picked``; a
 * spectator receives ``both_picked`` instead. Every optional field is
 * optional because the runtime already decides which projection a caller gets
 * and the client must not fill a missing one in by guessing.
 */
export type MatchView = {
  round: number
  scores: Record<string, number>
  you?: string
  your_pick?: string | null
  opponent_has_picked?: boolean
  both_picked?: boolean
  reveal: MatchReveal | null
  winner: string | null
  finished: boolean
  /**
   * Set by the game when the finish came from a seat that did not return
   * inside the reconnect grace (S3/S6). The client only renders it; it never
   * derives the reason.
   */
  ended_by_abandon?: boolean
}

/**
 * The single current match a session is following.
 *
 * ``version`` is the optimistic-concurrency token used as ``expected_version``.
 * It is ``null`` until the server has told this client a value: the WebSocket
 * ``match.snapshot`` only carries the reference and the view, so the version
 * arrives through the resync read.
 */
export type MatchState = {
  matchRef: string
  seatIndex: number | null
  version: number | null
  view: MatchView
}

export type MatchRendererProps = {
  match: MatchState
  busy: boolean
  onPick: (value: string) => void
}

/**
 * The renderer registry.
 *
 * Adding a game means adding its file and one entry here. The app asks for a
 * renderer by ``game_id`` and falls back to a plain message when none exists,
 * so an unknown game can never crash the room panel.
 */
const GAME_RENDERERS: Record<string, ComponentType<MatchRendererProps>> = {
  duelo: DueloMatch,
}

export function hasMatchRenderer(gameId: string | undefined): boolean {
  if (!gameId) return false
  return GAME_RENDERERS[gameId] !== undefined
}

/**
 * Render the match view registered for ``gameId``, or ``null`` when the game
 * has no renderer.
 *
 * This is a factory rather than a component so the caller never holds a
 * component reference it created during render, which would remount the
 * renderer on every pass.
 */
export function renderMatchScreen(
  gameId: string | undefined,
  props: MatchRendererProps,
): ReactElement | null {
  const renderer = gameId ? GAME_RENDERERS[gameId] : undefined
  if (!renderer) return null
  return createElement(renderer, props)
}
