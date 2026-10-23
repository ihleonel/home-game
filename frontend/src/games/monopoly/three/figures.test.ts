import { describe, expect, it } from 'vitest'
import { PIECE_FIGURES, figureFor } from './figures'

/**
 * The markers the room offers for ``monopoly``, in the order the server
 * publishes them (``backend/modules/games/monopoly/game.py``, ``seat_options``).
 *
 * The frontend is not allowed to import a Python catalogue, so the list is
 * copied here as the test's own contract: a marker added on the server and not
 * here falls back to the neutral counter, which the scene still draws. The last
 * two arrived with the flat tokens, when the catalogue stopped matching
 * ``MAX_SEATS`` one for one.
 */
const CLASSIC_MARKERS = [
  'sombrero',
  'automovil',
  'perro',
  'barco',
  'gato',
  'plancha',
  'botin',
  'dedal',
  'pinguino',
  'pato',
] as const

describe('the marker chooses the piece', () => {
  it('gives every classic marker a piece of its own', () => {
    const figures = CLASSIC_MARKERS.map(figureFor)
    expect(new Set(figures).size).toBe(CLASSIC_MARKERS.length)
    expect(figures).not.toContain('ficha')
  })

  it('knows exactly the ten classic pieces and the neutral counter', () => {
    const expected = [...CLASSIC_MARKERS, 'ficha']
    expect(new Set(PIECE_FIGURES)).toEqual(new Set(expected))
    expect(PIECE_FIGURES).toHaveLength(expected.length)
  })

  it('falls back to the neutral counter instead of inventing a piece', () => {
    // Empty (no roster entry), a marker from another game, and the catalogue id
    // with different case: the id travels verbatim, so no normalisation.
    expect([figureFor(''), figureFor('guante-rojo'), figureFor('SOMBRERO')]).toEqual([
      'ficha',
      'ficha',
      'ficha',
    ])
  })

  it('does not hand back an Object.prototype member as a piece', () => {
    // A plain object used as a lookup inherits ``toString``, ``constructor`` and
    // the rest, and the scene would then ask for a figure that is not in the
    // catalogue. Every one of them is an unknown marker and must be the counter.
    const inherited = ['toString', 'constructor', 'valueOf', 'hasOwnProperty', '__proto__']
    expect(inherited.map(figureFor)).toEqual(inherited.map(() => 'ficha'))
  })
})
