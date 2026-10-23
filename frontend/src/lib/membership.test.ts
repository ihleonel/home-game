import { describe, expect, it } from 'vitest'
import type { Room } from '../api/types'
import {
  MISSING_IDENTITY_MESSAGE,
  buildMembershipRequest,
  identityProblem,
  resolveAssignedIdentity,
} from './membership'

function room(): Room {
  return {
    game_id: 'duelo',
    status: 'active',
    created_at: '2026-10-16T00:00:00Z',
    updated_at: '2026-10-16T00:00:00Z',
    participants: [
      {
        participant_ref: 'p-1',
        display_name: 'Espectador 1',
        game_marker: 'sol',
        role: 'spectator',
        is_ready: false,
        presence: 'online',
        remaining_seconds: null,
        disconnected_at: null,
        joined_at: '2026-10-16T00:00:00Z',
      },
    ],
    expulsion_vote: null,
    seat_limits: { min_seats: 2, max_seats: 2 },
  }
}

describe('identityProblem', () => {
  it('requires a name and a marker for an ordinary entry', () => {
    expect(identityProblem({ displayName: '  ', gameMarker: '' })).toBe(
      MISSING_IDENTITY_MESSAGE,
    )
    expect(identityProblem({ displayName: 'Ana', gameMarker: '' })).toBe(
      MISSING_IDENTITY_MESSAGE,
    )
    expect(identityProblem({ displayName: 'Ana', gameMarker: 'sol' })).toBeNull()
  })

  it('never blocks a spectator entry', () => {
    expect(
      identityProblem({ displayName: '', gameMarker: '' }, { asSpectator: true }),
    ).toBeNull()
  })
})

describe('buildMembershipRequest', () => {
  it('omits the identity a spectator did not type', () => {
    expect(
      buildMembershipRequest(
        'duelo',
        { displayName: '  ', gameMarker: '' },
        { asSpectator: true },
      ),
    ).toEqual({ game_id: 'duelo', as_spectator: true })
  })

  it('keeps a typed identity trimmed and the stored session', () => {
    expect(
      buildMembershipRequest(
        'duelo',
        { displayName: '  Ana ', gameMarker: 'sol' },
        { sessionId: 'session-1' },
      ),
    ).toEqual({
      game_id: 'duelo',
      display_name: 'Ana',
      game_marker: 'sol',
      session_id: 'session-1',
    })
  })
})

describe('resolveAssignedIdentity', () => {
  it('reads the identity the platform assigned to this participant', () => {
    expect(
      resolveAssignedIdentity(room(), 'p-1', { displayName: '', gameMarker: '' }),
    ).toEqual({ displayName: 'Espectador 1', gameMarker: 'sol' })
  })

  it('keeps the submitted identity when the room does not name the participant', () => {
    expect(
      resolveAssignedIdentity(room(), 'p-missing', {
        displayName: 'Ana',
        gameMarker: 'sol',
      }),
    ).toEqual({ displayName: 'Ana', gameMarker: 'sol' })
  })
})
