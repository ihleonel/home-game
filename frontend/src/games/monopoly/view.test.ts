import { describe, expect, it } from 'vitest'
import { parseMonopolyView } from './view'

/**
 * A well-formed payload as the runtime projects it (S7).
 *
 * It is deliberately spelled out field by field instead of built from the
 * parser's own types: the parser exists because the payload arrives
 * unvalidated over the network, so these tests feed raw values on purpose.
 */
function rawView(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    finished: false,
    winner: null,
    ended_by_abandon: false,
    phase: 'awaiting_roll',
    turn: 'seat-0',
    players: [
      {
        seat: 'seat-0',
        cash: 1500,
        position: 0,
        properties: [],
        in_jail: false,
        jail_turns: 0,
        eliminated: false,
      },
      {
        seat: 'seat-1',
        cash: 1500,
        position: 0,
        properties: [],
        in_jail: false,
        jail_turns: 0,
        eliminated: false,
      },
    ],
    owners: { '3': 'seat-0' },
    last_roll: [1, 2],
    pending: null,
    actions: [{ name: 'roll', prompt: 'Tirá los dados.', options: [] }],
    you: 'seat-0',
    ...overrides,
  }
}

describe('the monopoly view parser', () => {
  it('reads a well-formed payload field by field', () => {
    expect(parseMonopolyView(rawView())).toEqual(rawView())
  })

  it('keeps the public board and economy for a spectator payload', () => {
    const payload = rawView({ actions: [] })
    delete payload.you

    const view = parseMonopolyView(payload)

    expect(view).not.toBeNull()
    expect(view).not.toHaveProperty('you')
    expect(view?.players).toHaveLength(2)
    expect(view?.owners).toEqual({ '3': 'seat-0' })
    expect(view?.actions).toEqual([])
  })

  it('recognizes a payload with nothing but the identifying fields', () => {
    const payload = rawView()
    delete payload.ended_by_abandon
    delete payload.turn
    delete payload.last_roll
    delete payload.pending
    delete payload.actions
    delete payload.you

    expect(parseMonopolyView(payload)).toEqual({
      finished: false,
      winner: null,
      phase: 'awaiting_roll',
      turn: null,
      players: payload.players,
      owners: { '3': 'seat-0' },
      last_roll: null,
      pending: null,
      actions: [],
    })
  })

  it('reads a finished match', () => {
    const view = parseMonopolyView(
      rawView({ finished: true, winner: 'seat-1', turn: null }),
    )

    expect([view?.finished, view?.winner, view?.turn]).toEqual([true, 'seat-1', null])
  })

  it('reads a pending purchase', () => {
    const view = parseMonopolyView(
      rawView({
        phase: 'awaiting_decision',
        pending: { kind: 'purchase', space: 3 },
        actions: [
          { name: 'buy', prompt: 'Comprá Avenida Báltica por $60.', options: [] },
          { name: 'decline', prompt: 'No la compres.', options: [] },
        ],
      }),
    )

    expect(view?.phase).toBe('awaiting_decision')
    expect(view?.pending).toEqual({ kind: 'purchase', space: 3 })
    expect(view?.actions.map((action) => action.name)).toEqual(['buy', 'decline'])
  })

  it('drops a malformed optional field instead of the whole screen', () => {
    const view = parseMonopolyView(
      rawView({
        turn: 7,
        last_roll: 'two',
        pending: { kind: 'purchase' },
        ended_by_abandon: 'yes',
      }),
    )

    expect(view).not.toBeNull()
    expect(view?.turn).toBeNull()
    expect(view?.last_roll).toBeNull()
    expect(view?.pending).toBeNull()
    expect(view).not.toHaveProperty('ended_by_abandon')
  })

  it('drops a malformed roll, not a roll with a wrong face count', () => {
    expect(parseMonopolyView(rawView({ last_roll: [] }))?.last_roll).toBeNull()
    expect(parseMonopolyView(rawView({ last_roll: [1] }))?.last_roll).toBeNull()
    expect(parseMonopolyView(rawView({ last_roll: [1, 2, 3] }))?.last_roll).toBeNull()
    expect(parseMonopolyView(rawView({ last_roll: [1, 7] }))?.last_roll).toBeNull()
    expect(parseMonopolyView(rawView({ last_roll: [6, 6] }))?.last_roll).toEqual([6, 6])
  })

  it('drops a malformed action and keeps the valid ones', () => {
    const view = parseMonopolyView(
      rawView({
        actions: [
          { name: 'roll', prompt: 'Tirá los dados.', options: [] },
          { name: 'buy' },
          { name: 'build', prompt: 'Construí.', options: ['6', '8'] },
          'nope',
        ],
      }),
    )

    expect(view?.actions.map((action) => action.name)).toEqual(['roll', 'build'])
  })

  it('treats a non-list of actions as no actions', () => {
    expect(parseMonopolyView(rawView({ actions: { name: 'roll' } }))?.actions).toEqual([])
  })

  it('rejects a payload that is not a monopoly view', () => {
    expect(parseMonopolyView(null)).toBeNull()
    expect(parseMonopolyView('monopoly')).toBeNull()
    expect(parseMonopolyView({})).toBeNull()
    expect(
      parseMonopolyView({ finished: false, winner: null, board: [], symbols: {} }),
    ).toBeNull()
    expect(
      parseMonopolyView({ finished: false, winner: null, round: 1, scores: {} }),
    ).toBeNull()
  })

  it('rejects a payload whose phase is not one of the three', () => {
    expect(parseMonopolyView(rawView({ phase: 'resolving' }))).toBeNull()
    expect(parseMonopolyView(rawView({ phase: undefined }))).toBeNull()
  })

  it('rejects a players list it cannot render honestly', () => {
    expect(parseMonopolyView(rawView({ players: [] }))).toBeNull()
    expect(parseMonopolyView(rawView({ players: {} }))).toBeNull()
    expect(
      parseMonopolyView(
        rawView({
          players: [
            {
              seat: 'seat-0',
              cash: 1500,
              position: 0,
              properties: [],
              in_jail: false,
              jail_turns: 0,
              eliminated: false,
            },
            { seat: 'seat-1' },
          ],
        }),
      ),
    ).toBeNull()
    expect(parseMonopolyView(rawView({ players: 'two seats' }))).toBeNull()
    expect(
      parseMonopolyView(
        rawView({
          players: [
            {
              seat: 'seat-0',
              cash: 1500,
              position: 99,
              properties: [],
              in_jail: false,
              jail_turns: 0,
              eliminated: false,
            },
          ],
        }),
      ),
    ).toBeNull()
  })

  it('rejects an owners map it cannot read', () => {
    expect(parseMonopolyView(rawView({ owners: undefined }))).toBeNull()
    expect(parseMonopolyView(rawView({ owners: [] }))).toBeNull()
    expect(parseMonopolyView(rawView({ owners: { '3': 1 } }))).toBeNull()
  })

  it('ignores a field the game does not own', () => {
    const view = parseMonopolyView(rawView({ future_field: 'ignored' }))

    expect(view).not.toBeNull()
    expect(view).not.toHaveProperty('future_field')
  })
})
