import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ExpulsionVote, Participant } from '../api/types'
import {
  expulsionVoteMessage,
  expulsionVoteOriginLabel,
  expulsionVoteTargets,
  expulsionVoteTargetNames,
} from '../lib/format'
import { ExpulsionVotePanel } from './ExpulsionVotePanel'

function participant(ref: string, displayName: string): Participant {
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
  }
}

const roster: Participant[] = [participant('p-ana', 'Ana'), participant('p-beto', 'Beto')]

function vote(overrides: Partial<ExpulsionVote> = {}): ExpulsionVote {
  return {
    vote_ref: 'vote-1',
    targets: ['p-beto'],
    origin: 'automatic',
    started_by_ref: null,
    status: 'pending',
    resolution_reason: '',
    started_at: '2026-10-16T00:00:00Z',
    resolved_at: null,
    eligible_count: 2,
    yes_count: 0,
    no_count: 0,
    ballots: [],
    ...overrides,
  }
}

describe('the expulsion vote copy', () => {
  it('never promises that a rejected player stays in the room', () => {
    const message = expulsionVoteMessage(vote({ status: 'rejected' }))

    expect(message).toContain('rechazada')
    expect(message).not.toMatch(/permanece/i)
  })

  it('says an automatic vote opened on its own, with no starter', () => {
    const label = expulsionVoteOriginLabel(
      vote({ origin: 'automatic', started_by_ref: null }),
      roster,
    )

    expect(label).toContain('automáticamente')
    expect(label).not.toContain('iniciada por')
  })

  it('names the starter of a manual vote', () => {
    const label = expulsionVoteOriginLabel(
      vote({ origin: 'manual', started_by_ref: 'p-ana' }),
      roster,
    )

    expect(label).toContain('Ana')
  })

  it('resolves every target of the batch from the roster', () => {
    const names = expulsionVoteTargetNames(vote({ targets: ['p-ana', 'p-beto'] }), roster)

    expect(names).toEqual(['Ana', 'Beto'])
  })

  it('reads an older payload without targets or origin as a manual vote of one target', () => {
    const legacy = {
      ...vote(),
      targets: undefined,
      origin: undefined,
      target_ref: 'p-beto',
      started_by_ref: null,
    } as unknown as ExpulsionVote

    expect(expulsionVoteTargets(legacy)).toEqual(['p-beto'])
    expect(expulsionVoteTargetNames(legacy, roster)).toEqual(['Beto'])
    expect(expulsionVoteOriginLabel(legacy, roster)).toContain('manualmente')
  })
})

function renderPanel(voteValue: ExpulsionVote, participants: Participant[] = roster): string {
  return renderToStaticMarkup(
    <ExpulsionVotePanel
      busy={false}
      canVote
      isTarget={false}
      onCast={() => {}}
      ownBallot={undefined}
      participants={participants}
      vote={voteValue}
    />,
  )
}

describe('the expulsion vote panel', () => {
  it('renders every target name of the batch', () => {
    const markup = renderPanel(vote({ targets: ['p-ana', 'p-beto'] }))

    expect(markup).toContain('Ana')
    expect(markup).toContain('Beto')
  })

  it('notes that an automatic vote opened on its own', () => {
    const markup = renderPanel(vote({ origin: 'automatic', started_by_ref: null }))

    expect(markup).toContain('automáticamente')
  })

  it('names the starter of a manual vote', () => {
    const markup = renderPanel(vote({ origin: 'manual', started_by_ref: 'p-ana' }))

    expect(markup).toContain('Votación iniciada por Ana')
  })
})
