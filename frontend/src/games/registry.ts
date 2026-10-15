import type { ReactElement } from 'react'
import { renderDueloMatch } from './duelo/screen'
import type { MatchSeatRosterEntry } from './matchRoster'
import { renderMonopolyMatch } from './monopoly/screen'
import { renderTaTeTiMatch } from './ta-te-ti/screen'

/**
 * The fields every game's match view carries.
 *
 * They belong to the runtime, not to a game: the match screen reads them to
 * decide whether the match is over, to word the abandonment result and to mark
 * the viewer's own seat. A game only adds its own play payload on top of them
 * (see ``duelo``'s ``DueloView``), so adding a game never widens this shape.
 *
 * ``you`` is a seat id. It stays here because the runtime already knows the
 * seat it projected the view for, so a game never has to repeat it.
 */
export type MatchRuntimeView = {
  finished: boolean
  winner: string | null
  ended_by_abandon?: boolean
  you?: string
}

/**
 * The single current match a session is following.
 *
 * ``version`` is the optimistic-concurrency token used as ``expected_version``.
 * It is ``null`` until the server has told this client a value: the WebSocket
 * ``match.snapshot`` only carries the reference and the view, so the version
 * arrives through the resync read.
 *
 * ``TView`` is the payload of the game this match belongs to. The plumbing
 * between the socket and the screen only ever needs the runtime fields, so it
 * holds the default; the game's own screen narrows it after parsing.
 */
export type MatchState<TView extends MatchRuntimeView = MatchRuntimeView> = {
  matchRef: string
  seatIndex: number | null
  version: number | null
  /**
   * The public identity of every seat as the server projected it (S1/S3).
   * The client renders it and never derives it: an empty array is a valid
   * match whose screen falls back to the neutral seat label.
   */
  roster: MatchSeatRosterEntry[]
  view: TView
}

export type MatchRendererProps<TView extends MatchRuntimeView = MatchRuntimeView> = {
  match: MatchState<TView>
  busy: boolean
  /**
   * Submit one action by name, with the value the server offered for it.
   *
   * This is the general channel. The runtime validates the name against the
   * actions the seat was offered and the value against that action's own
   * ``options``, so a screen submits what it was handed and never composes a
   * play the server did not offer. ``value`` is ``null`` for an action that
   * carries none, which is exactly what the runtime requires for an action
   * whose option list is empty.
   */
  onAction: (name: string, value: string | null) => void
  /**
   * The single-action games' shorthand, fixed to the action name ``pick``.
   *
   * ``duelo`` and ``ta-te-ti`` both name their only action ``pick``, so their
   * screens keep one callback instead of repeating the name at every button.
   * A game with more than one action uses ``onAction``.
   */
  onPick: (value: string) => void
}

/**
 * One game's screen, already past its own parser.
 *
 * It receives the runtime's raw view and either returns the game's element or
 * ``null`` when it does not recognize the payload.
 */
export type GameScreen = (props: MatchRendererProps) => ReactElement | null

/**
 * The screen registry.
 *
 * Adding a game means adding its folder -- the component, its own view type and
 * parser, its stylesheet and a factory like ``renderDueloMatch`` -- and one
 * entry here. The factory is what keeps the payload honest: the app asks for a
 * screen by ``game_id`` and falls back to a plain message when there is none or
 * when the payload is not that game's view, so an unknown game or a malformed
 * frame can never crash the room panel.
 */
const GAME_SCREENS: Record<string, GameScreen> = {
  duelo: renderDueloMatch,
  'ta-te-ti': renderTaTeTiMatch,
  monopoly: renderMonopolyMatch,
}

export function hasMatchRenderer(gameId: string | undefined): boolean {
  if (!gameId) return false
  return GAME_SCREENS[gameId] !== undefined
}

/**
 * Render the match screen registered for ``gameId``, or ``null`` when the game
 * has no screen or its parser did not recognize the payload.
 *
 * The caller owns what ``null`` looks like; every caller renders its own
 * "vista de partida no disponible" notice.
 */
export function renderMatchScreen(
  gameId: string | undefined,
  props: MatchRendererProps,
): ReactElement | null {
  const screen = gameId ? GAME_SCREENS[gameId] : undefined
  if (!screen) return null
  return screen(props)
}
