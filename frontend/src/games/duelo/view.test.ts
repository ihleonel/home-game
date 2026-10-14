import { describe, expect, it } from 'vitest'
import { parseDueloView } from './view'

/**
 * A complete seat view exactly as ``duelo`` projects it.
 *
 * ``overrides`` lets a case break one field at a time, so a rejection can be
 * attributed to that field and not to an accidentally malformed payload.
 */
function payload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    round: 2,
    scores: { 'seat-0': 1, 'seat-1': 0 },
    you: 'seat-0',
    your_pick: 'rock',
    opponent_has_picked: true,
    reveal: {
      round: 1,
      picks: { 'seat-0': 'rock', 'seat-1': 'scissors' },
      winner: 'seat-0',
    },
    winner: null,
    finished: false,
    ended_by_abandon: false,
    ...overrides,
  }
}

describe('parseDueloView', () => {
  it('accepts a complete seat view and keeps every field', () => {
    const view = parseDueloView(payload())

    expect(view).toEqual(payload())
  })

  it('accepts a spectator view, which carries no `you`', () => {
    const spectator = {
      round: 1,
      scores: { 'seat-0': 0, 'seat-1': 0 },
      both_picked: true,
      reveal: null,
      winner: null,
      finished: false,
      ended_by_abandon: false,
    }

    const view = parseDueloView(spectator)

    expect(view).toEqual(spectator)
    expect(view?.you).toBeUndefined()
  })

  it('keeps the runtime fields the match screen reads', () => {
    const view = parseDueloView(
      payload({ finished: true, winner: 'seat-1', ended_by_abandon: true }),
    )

    expect(view?.finished).toBe(true)
    expect(view?.winner).toBe('seat-1')
    expect(view?.ended_by_abandon).toBe(true)
  })

  it('accepts a resolved round and a null reveal alike', () => {
    expect(parseDueloView(payload())?.reveal).toEqual({
      round: 1,
      picks: { 'seat-0': 'rock', 'seat-1': 'scissors' },
      winner: 'seat-0',
    })
    expect(parseDueloView(payload({ reveal: null }))?.reveal).toBeNull()
  })

  it('rejects anything that is not an object', () => {
    expect(parseDueloView(null)).toBeNull()
    expect(parseDueloView(undefined)).toBeNull()
    expect(parseDueloView('duelo')).toBeNull()
    expect(parseDueloView(7)).toBeNull()
    expect(parseDueloView([])).toBeNull()
  })

  it('rejects a payload missing the duelo core, so a wrong game never renders here', () => {
    expect(parseDueloView({})).toBeNull()
    expect(parseDueloView(payload({ finished: undefined }))).toBeNull()
    expect(parseDueloView(payload({ round: undefined }))).toBeNull()
    expect(parseDueloView(payload({ scores: undefined }))).toBeNull()
    expect(parseDueloView(payload({ winner: undefined }))).toBeNull()
  })

  it('rejects core fields of the wrong type', () => {
    expect(parseDueloView(payload({ finished: 'yes' }))).toBeNull()
    expect(parseDueloView(payload({ winner: 3 }))).toBeNull()
    expect(parseDueloView(payload({ round: 1.5 }))).toBeNull()
    expect(parseDueloView(payload({ round: -1 }))).toBeNull()
    expect(parseDueloView(payload({ scores: { 'seat-0': 'one' } }))).toBeNull()
    expect(parseDueloView(payload({ scores: [] }))).toBeNull()
  })

  it('drops an optional field of the wrong type instead of blanking the screen', () => {
    const view = parseDueloView(payload({ you: 42, your_pick: false }))

    expect(view).not.toBeNull()
    expect(view?.you).toBeUndefined()
    expect(view?.your_pick).toBeUndefined()
    expect(view?.round).toBe(2)
  })

  it('degrades a malformed reveal to null instead of rejecting the payload', () => {
    const view = parseDueloView(payload({ reveal: 'not-a-round' }))

    expect(view).not.toBeNull()
    expect(view?.reveal).toBeNull()
  })
})
