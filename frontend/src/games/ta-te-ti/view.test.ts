import { describe, expect, it } from 'vitest'
import { parseTaTeTiView } from './view'

/**
 * A complete seat view exactly as ``ta-te-ti`` projects it.
 *
 * ``overrides`` lets a case break one field at a time, so a rejection can be
 * attributed to that field and not to an accidentally malformed payload.
 */
function payload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    board: ['seat-0', null, 'seat-1', null, 'seat-0', null, null, null, 'seat-1'],
    turn: 'seat-0',
    symbols: { 'seat-0': 'X', 'seat-1': 'O' },
    winner_line: null,
    winner: null,
    finished: false,
    ended_by_abandon: false,
    you: 'seat-0',
    ...overrides,
  }
}

describe('parseTaTeTiView', () => {
  it('accepts a complete seat view and keeps every field', () => {
    const view = parseTaTeTiView(payload())

    expect(view).toEqual(payload())
  })

  it('accepts a spectator view, which carries no `you`', () => {
    const spectator = {
      board: Array<string | null>(9).fill(null),
      turn: 'seat-1',
      symbols: { 'seat-0': 'X', 'seat-1': 'O' },
      winner_line: null,
      winner: null,
      finished: false,
      ended_by_abandon: false,
    }

    const view = parseTaTeTiView(spectator)

    expect(view).toEqual(spectator)
    expect(view?.you).toBeUndefined()
  })

  it('keeps the runtime fields the match screen reads', () => {
    const view = parseTaTeTiView(
      payload({ finished: true, winner: 'seat-1', ended_by_abandon: true }),
    )

    expect(view?.finished).toBe(true)
    expect(view?.winner).toBe('seat-1')
    expect(view?.ended_by_abandon).toBe(true)
  })

  it('accepts a winning line and a null line alike', () => {
    expect(parseTaTeTiView(payload({ winner_line: [0, 1, 2] }))?.winner_line).toEqual([0, 1, 2])
    expect(parseTaTeTiView(payload({ winner_line: null }))?.winner_line).toBeNull()
  })

  it('rejects anything that is not an object', () => {
    expect(parseTaTeTiView(null)).toBeNull()
    expect(parseTaTeTiView(undefined)).toBeNull()
    expect(parseTaTeTiView('ta-te-ti')).toBeNull()
    expect(parseTaTeTiView(7)).toBeNull()
    expect(parseTaTeTiView([])).toBeNull()
  })

  it('rejects a payload missing the ta-te-ti core, so a wrong game never renders here', () => {
    expect(parseTaTeTiView({})).toBeNull()
    expect(parseTaTeTiView(payload({ finished: undefined }))).toBeNull()
    expect(parseTaTeTiView(payload({ winner: undefined }))).toBeNull()
    expect(parseTaTeTiView(payload({ board: undefined }))).toBeNull()
    expect(parseTaTeTiView(payload({ symbols: undefined }))).toBeNull()
  })

  it('rejects core fields of the wrong type', () => {
    expect(parseTaTeTiView(payload({ finished: 'yes' }))).toBeNull()
    expect(parseTaTeTiView(payload({ winner: 3 }))).toBeNull()
    expect(parseTaTeTiView(payload({ board: 'nine' }))).toBeNull()
    expect(parseTaTeTiView(payload({ board: ['seat-0'] }))).toBeNull()
    expect(parseTaTeTiView(payload({ board: [...Array<string | null>(8).fill(null), 4] }))).toBeNull()
    expect(parseTaTeTiView(payload({ symbols: [] }))).toBeNull()
    expect(parseTaTeTiView(payload({ symbols: { 'seat-0': 'Y' } }))).toBeNull()
  })

  it('drops an optional field of the wrong type instead of blanking the screen', () => {
    const view = parseTaTeTiView(payload({ you: 42, ended_by_abandon: 'yes' }))

    expect(view).not.toBeNull()
    expect(view?.you).toBeUndefined()
    expect(view?.ended_by_abandon).toBeUndefined()
  })

  it('degrades a malformed turn or line to null instead of rejecting the payload', () => {
    const view = parseTaTeTiView(payload({ turn: 5, winner_line: 'the top row' }))

    expect(view).not.toBeNull()
    expect(view?.turn).toBeNull()
    expect(view?.winner_line).toBeNull()
    expect(view?.board).toEqual(payload().board)
  })
})
