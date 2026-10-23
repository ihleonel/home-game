import { describe, expect, it } from 'vitest'
import { FIGURE_INK, INK_BOX } from './figureInk'
import type { InkLoop } from './figureInk'
import { PIECE_FIGURES } from './figures'

/**
 * The area a flat ``x0, y0, x1, y1, ...`` loop encloses, by the shoelace formula.
 *
 * The silhouettes are polygons in one box with no curves, so area is the honest
 * way to ask "is there ink here at all": a loop that came back empty or
 * degenerate still closes, and it would print an empty token.
 */
function loopArea(loop: InkLoop): number {
  let sum = 0
  for (let index = 0; index < loop.length; index += 2) {
    const x1 = loop[index]
    const y1 = loop[index + 1]
    const x2 = loop[(index + 2) % loop.length]
    const y2 = loop[(index + 3) % loop.length]
    sum += x1 * y2 - x2 * y1
  }
  return Math.abs(sum) / 2
}

describe('every figure has its silhouette', () => {
  it('draws exactly the figures the catalogue knows, and no others', () => {
    expect(Object.keys(FIGURE_INK).sort()).toEqual([...PIECE_FIGURES].sort())
  })

  it('gives every figure at least one closed loop of real ink', () => {
    for (const figure of PIECE_FIGURES) {
      const loops = FIGURE_INK[figure]
      expect(loops.length).toBeGreaterThan(0)
      for (const loop of loops) {
        // A flat list of points is even, and three points is the smallest
        // polygon that encloses anything.
        expect(loop.length % 2).toBe(0)
        expect(loop.length).toBeGreaterThanOrEqual(6)
        expect(loopArea(loop)).toBeGreaterThan(0)
      }
      const covered = loops.reduce((total, loop) => total + loopArea(loop), 0)
      expect(covered).toBeGreaterThan(INK_BOX)
    }
  })

  it('keeps every point inside the box the chip paints', () => {
    for (const figure of PIECE_FIGURES) {
      for (const loop of FIGURE_INK[figure]) {
        for (const value of loop) {
          expect(Number.isFinite(value)).toBe(true)
          expect(value).toBeGreaterThanOrEqual(0)
          expect(value).toBeLessThanOrEqual(INK_BOX)
        }
      }
    }
  })

  it('gives every figure its own silhouette', () => {
    const drawn = PIECE_FIGURES.map((figure) => JSON.stringify(FIGURE_INK[figure]))
    expect(new Set(drawn).size).toBe(drawn.length)
  })

  it('prints a neutral counter that is no marker in disguise', () => {
    const counter = JSON.stringify(FIGURE_INK.ficha)
    for (const figure of PIECE_FIGURES) {
      if (figure === 'ficha') continue
      expect(JSON.stringify(FIGURE_INK[figure])).not.toBe(counter)
    }
  })
})
