import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Game, Participant } from '../api/types'
import { Roster } from './Roster'

const game: Game = {
  id: 'duelo',
  label: 'Duelo',
  description: 'Piedra, papel o tijera.',
  markers: [{ id: 'rock', label: 'Piedra' }],
}

function participant(overrides: Partial<Participant> = {}): Participant {
  return {
    participant_ref: 'p-1',
    display_name: 'Ana',
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

function render(participants: Participant[]): string {
  return renderToStaticMarkup(<Roster game={game} participants={participants} />)
}

describe('the room roster', () => {
  it.each(['online', 'reconnecting', 'inactive', 'offline'] as const)(
    'offers no expulsion-vote action for a %s player',
    (presence) => {
      const markup = render([
        participant({ participant_ref: 'p-target', display_name: 'Beto', presence }),
      ])

      expect(markup).not.toContain('Iniciar votación de expulsión')
      expect(markup).not.toContain('vote-start-button')
    },
  )

  it('still shows the participants it always showed', () => {
    const markup = render([
      participant({ participant_ref: 'p-ana', display_name: 'Ana' }),
      participant({ participant_ref: 'p-beto', display_name: 'Beto', role: 'spectator' }),
    ])

    expect(markup).toContain('Ana')
    expect(markup).toContain('Beto')
    expect(markup).toContain('Espectador')
  })
})
