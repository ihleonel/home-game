import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Game, Room } from '../api/types'
import type { MatchState } from '../games/registry'
import type { RoomSessionContextValue } from '../state/roomSessionContext'

/**
 * The values the mocked providers answer with.
 *
 * ``vi.hoisted`` keeps them above the ``vi.mock`` factories that read them,
 * while the factories themselves stay lazy: the arrow bodies run during render,
 * so a test can swap the state before every render.
 */
const state = vi.hoisted(() => ({
  session: {} as Record<string, unknown>,
  games: [] as unknown[],
}))

vi.mock('../state/roomSessionContext', () => ({
  useRoomSession: () => state.session,
}))

vi.mock('../state/catalogContext', () => ({
  useCatalog: () => ({
    games: state.games,
    isLoading: false,
    loadError: null,
    reload: () => {},
  }),
}))

vi.mock('../games/matchPresence', () => ({
  useMatchPresence: () => [],
}))

import { MatchPage } from './MatchPage'

const dueloGame: Game = {
  id: 'duelo',
  label: 'Duelo',
  description: 'Piedra, papel o tijera.',
  markers: [{ id: 'rock', label: 'Piedra' }],
}

const chessGame: Game = {
  id: 'ajedrez',
  label: 'Ajedrez',
  description: 'Todavía sin vista de partida.',
  markers: [],
}

const validDueloView = {
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

function roomFor(gameId: string): Room {
  return {
    game_id: gameId,
    status: 'in_match',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    participants: [],
    expulsion_vote: null,
    seat_limits: { min_seats: 2, max_seats: 2 },
  }
}

/**
 * The slice of the room session the match screen reads, plus the fields the
 * shared context type requires for the other pages.
 */
function sessionFor(gameId: string, view: unknown): RoomSessionContextValue {
  const match = {
    matchRef: 'match-1',
    seatIndex: 0,
    version: 3,
    roster: [],
    view,
  } as unknown as MatchState

  return {
    room: roomFor(gameId),
    roomSession: {
      displayName: 'Ana',
      gameMarker: 'rock',
      gameId,
      sessionId: 'session-1',
      participantRef: 'participant-1',
      isReady: true,
    },
    match,
    countdown: null,
    countdownNotice: null,
    voteNotice: null,
    connectionError: null,
    actionError: null,
    busy: false,
    pendingAction: null,
    isJoined: true,
    currentParticipant: undefined,
    activeExpulsionVote: null,
    currentBallot: undefined,
    allReady: true,
    ownReady: true,
    activeMatch: match,
    matchInProgress: true,
    matchRendererAvailable: gameId === 'duelo',
    createOrJoin: async () => 'rejected',
    toggleReady: async () => {},
    requestPlayerSeat: async () => {},
    leaveRoom: async () => {},
    startExpulsionVote: async () => {},
    castExpulsionBallot: async () => {},
    submitPick: async () => {},
    setActionError: () => {},
  }
}

function render(games: Game[], gameId: string, view: unknown): string {
  state.games = games
  state.session = sessionFor(gameId, view) as unknown as Record<string, unknown>
  return renderToStaticMarkup(
    <MemoryRouter>
      <MatchPage />
    </MemoryRouter>,
  )
}

describe('the match screen', () => {
  beforeEach(() => {
    state.games = []
    state.session = {}
  })

  it('renders the unavailable notice for a game without a registered screen', () => {
    const markup = render([chessGame], 'ajedrez', {})

    expect(markup).toContain('Vista de partida no disponible')
  })

  it('renders the game screen for a registered game with a valid payload', () => {
    const markup = render([dueloGame], 'duelo', validDueloView)

    expect(markup).toContain('Ronda 2')
    expect(markup).not.toContain('Vista de partida no disponible')
  })

  it('names the game once: the screen header owns the title and the panel does not repeat it', () => {
    // The match screen already prints the game's label as the page heading, so a
    // second copy inside the panel is the same word twice on the same screen.
    const markup = render([dueloGame], 'duelo', validDueloView)

    expect(markup.match(/Duelo/g)).toHaveLength(1)
  })

  it('falls back to the notice when a registered game sends an unrecognizable payload', () => {
    // Regression guard for the reason the screen registry parses at all: a
    // registered game must never be handed bytes it does not recognize.
    const markup = render([dueloGame], 'duelo', {})

    expect(markup).toContain('Vista de partida no disponible')
  })
})
