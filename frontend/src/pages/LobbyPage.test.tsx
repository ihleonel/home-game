import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExpulsionVote, Game, Participant, Room } from '../api/types'
import type { RoomSessionContextValue } from '../state/roomSessionContext'

/**
 * The values the mocked providers answer with, swapped before every render
 * exactly as the match screen's tests do.
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

import { LobbyPage } from './LobbyPage'

const game: Game = {
  id: 'duelo',
  label: 'Duelo',
  description: 'Piedra, papel o tijera.',
  markers: [{ id: 'rock', label: 'Piedra' }],
}

function participant(
  ref: string,
  displayName: string,
  overrides: Partial<Participant> = {},
): Participant {
  return {
    participant_ref: ref,
    display_name: displayName,
    game_marker: 'rock',
    role: 'player',
    is_ready: false,
    presence: 'online',
    remaining_seconds: null,
    disconnected_at: null,
    joined_at: '2026-10-16T00:00:00Z',
    ...overrides,
  }
}

function vote(overrides: Partial<ExpulsionVote> = {}): ExpulsionVote {
  return {
    vote_ref: 'vote-1',
    targets: ['p-beto', 'p-caro'],
    origin: 'automatic',
    started_by_ref: null,
    status: 'pending',
    resolution_reason: '',
    started_at: '2026-10-16T00:00:00Z',
    resolved_at: null,
    eligible_count: 2,
    yes_count: 1,
    no_count: 0,
    ballots: [],
    ...overrides,
  }
}

function roomFor(voteValue: ExpulsionVote | null): Room {
  return {
    game_id: 'duelo',
    status: 'open',
    created_at: '2026-10-16T00:00:00Z',
    updated_at: '2026-10-16T00:00:00Z',
    participants: [
      participant('p-ana', 'Ana'),
      participant('p-beto', 'Beto', { presence: 'inactive' }),
      participant('p-caro', 'Caro', { presence: 'inactive' }),
    ],
    expulsion_vote: voteValue,
    seat_limits: { min_seats: 2, max_seats: 4 },
  }
}

function sessionFor(room: Room): RoomSessionContextValue {
  return {
    room,
    roomSession: {
      displayName: 'Ana',
      gameMarker: 'rock',
      gameId: 'duelo',
      sessionId: 'session-1',
      participantRef: 'p-ana',
      isReady: false,
    },
    match: null,
    countdown: null,
    countdownNotice: null,
    voteNotice: null,
    connectionError: null,
    actionError: null,
    busy: false,
    pendingAction: null,
    isJoined: true,
    currentParticipant: room.participants.find(
      (candidate) => candidate.participant_ref === 'p-ana',
    ),
    activeExpulsionVote: room.expulsion_vote,
    currentBallot: undefined,
    allReady: false,
    ownReady: false,
    activeMatch: null,
    matchInProgress: false,
    matchRendererAvailable: true,
    createOrJoin: async () => 'rejected',
    toggleReady: async () => {},
    requestPlayerSeat: async () => {},
    leaveRoom: async () => {},
    castExpulsionBallot: async () => {},
    submitAction: async () => {},
    submitPick: async () => {},
    setActionError: () => {},
  }
}

function render(room: Room): string {
  state.games = [game]
  state.session = sessionFor(room) as unknown as Record<string, unknown>
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={['/rooms/duelo']}>
      <Routes>
        <Route path="/rooms/:gameId" element={<LobbyPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the room lobby', () => {
  beforeEach(() => {
    state.games = [game]
    state.session = {}
  })

  it('renders the vote panel above the roster', () => {
    const markup = render(roomFor(vote()))

    expect(markup.indexOf('vote-title')).toBeGreaterThan(-1)
    expect(markup.indexOf('vote-title')).toBeLessThan(markup.indexOf('roster-title'))
  })

  it('offers no manual start action for any participant', () => {
    const markup = render(roomFor(null))

    expect(markup).not.toContain('Iniciar votación de expulsión')
    expect(markup).not.toContain('vote-start-button')
  })

  it('renders both names of the open batch inside the panel', () => {
    const markup = render(roomFor(vote({ targets: ['p-beto', 'p-caro'] })))
    const panel = markup.slice(markup.indexOf('vote-panel'), markup.indexOf('roster-section'))

    expect(panel).toContain('Beto')
    expect(panel).toContain('Caro')
  })
})
