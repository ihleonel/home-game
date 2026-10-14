import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { hasMatchRenderer, renderMatchScreen } from './registry'
import type { MatchState } from './registry'

const dueloView = {
  round: 2,
  scores: { 'seat-0': 1, 'seat-1': 0 },
  you: 'seat-0',
  your_pick: 'rock',
  opponent_has_picked: true,
  reveal: null,
  winner: null,
  finished: false,
  ended_by_abandon: false,
}

const roster = [
  {
    seat_id: 'seat-0',
    index: 0,
    display_name: 'Ana',
    game_marker: 'rock',
    game_marker_label: 'Piedra',
  },
  {
    seat_id: 'seat-1',
    index: 1,
    display_name: 'Beto',
    game_marker: 'scissors',
    game_marker_label: 'Tijera',
  },
]

/**
 * Build the match state a screen receives from a raw payload.
 *
 * The registry exists precisely because the payload arrives unvalidated over
 * the network, so the tests feed it raw values on purpose and this cast is the
 * only place the boundary is crossed.
 */
function rawMatch(view: unknown, seats = roster): MatchState {
  return {
    matchRef: 'match-1',
    seatIndex: 0,
    version: 3,
    roster: seats,
    view,
  } as unknown as MatchState
}

function render(gameId: string | undefined, view: unknown): string | null {
  const screen = renderMatchScreen(gameId, {
    busy: false,
    match: rawMatch(view),
    onPick: () => {},
  })
  return screen === null ? null : renderToStaticMarkup(screen)
}

describe('the game screen registry', () => {
  it('reports no screen for an unknown or missing game', () => {
    expect(hasMatchRenderer(undefined)).toBe(false)
    expect(hasMatchRenderer('')).toBe(false)
    expect(hasMatchRenderer('ajedrez')).toBe(false)
    expect(hasMatchRenderer('duelo')).toBe(true)
  })

  it('returns null instead of a screen for an unknown game', () => {
    expect(render('ajedrez', dueloView)).toBeNull()
    expect(render(undefined, dueloView)).toBeNull()
  })

  it('renders the registered screen for a valid payload', () => {
    const markup = render('duelo', dueloView)

    expect(markup).toContain('Duelo')
    expect(markup).toContain('Ronda 2')
  })

  it('renders the server roster identity and never a fabricated seat number', () => {
    const markup = render('duelo', dueloView) ?? ''

    expect(markup).toContain('Ana')
    expect(markup).toContain('Piedra')
    expect(markup).toContain('Beto')
    expect(markup).toContain('Tijera')
  })

  it('returns null for a registered game whose payload is not that game view', () => {
    // The new safety property: a registered game never receives bytes it did
    // not recognize, and the caller falls back to its own notice.
    expect(render('duelo', {})).toBeNull()
    expect(render('duelo', null)).toBeNull()
    expect(render('duelo', { round: 1, scores: { 'seat-0': 0 } })).toBeNull()
  })
})

const taTeTiView = {
  board: ['seat-0', null, 'seat-1', null, 'seat-0', null, null, null, 'seat-1'],
  turn: 'seat-0',
  symbols: { 'seat-0': 'X', 'seat-1': 'O' },
  winner_line: null,
  you: 'seat-0',
  winner: null,
  finished: false,
  ended_by_abandon: false,
}

describe('the ta-te-ti screen entry', () => {
  it('is registered beside duelo', () => {
    expect(hasMatchRenderer('ta-te-ti')).toBe(true)
  })

  it('renders its own panel for a valid payload', () => {
    const markup = render('ta-te-ti', taTeTiView)

    expect(markup).toContain('Ta-te-ti')
  })

  it('does not render one game screen over the other game view', () => {
    expect(render('ta-te-ti', dueloView)).toBeNull()
    expect(render('duelo', taTeTiView)).toBeNull()
  })
})
