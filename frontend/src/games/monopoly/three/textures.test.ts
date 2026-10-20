import { describe, expect, it } from 'vitest'
import type { ColorGroup } from '../board'
import { BOARD, BOARD_SIZE, PURCHASABLE_INDEXES, isPurchasable } from '../board'
import { HOTEL_LEVEL, deedFor, levelLabel, purchasePrice, rentForLevel } from '../deeds'
import { GROUP_INITIALS, GROUP_LABELS, KIND_LABELS, formatMoney } from '../display'
import { spaceSide } from '../grid'
import {
  CELL_TEXTURE_SIZE,
  GROUP_COLOURS,
  paintSpace,
  spaceTextureSpec,
  textRotationFor,
} from './textures'

/** The eight colour groups of the printed board, in their printed order. */
const GROUPS: readonly ColorGroup[] = [
  'brown',
  'light_blue',
  'pink',
  'orange',
  'red',
  'yellow',
  'green',
  'dark_blue',
]

/** One space of every kind the spec has to tell apart. */
const SAMPLES = {
  go: 0,
  street: 1,
  deck: 2,
  tax: 4,
  railroad: 5,
  utility: 12,
  jail: 10,
  freeParking: 20,
  goToJail: 30,
  luxuryTax: 38,
}

describe('the specification of one space', () => {
  it('names every space the board names, kind for kind', () => {
    for (const space of BOARD) {
      const spec = spaceTextureSpec(space.index)
      expect([space.index, spec.index, spec.name, spec.kind]).toEqual([
        space.index,
        space.index,
        space.name,
        space.kind,
      ])
      expect([space.index, spec.kindLabel]).toEqual([space.index, KIND_LABELS[space.kind]])
    }
  })

  it('paints the band only where the board gives a colour group', () => {
    for (const space of BOARD) {
      const spec = spaceTextureSpec(space.index)
      if (space.group === null) {
        expect([space.index, spec.band]).toEqual([space.index, null])
      } else {
        // Colour, initials and the Spanish name travel together: the band is
        // decoration, and the initials are what a player with no colour vision
        // reads instead (S3 of the panel increment).
        expect([space.index, spec.band]).toEqual([
          space.index,
          {
            group: space.group,
            colour: GROUP_COLOURS[space.group],
            initials: GROUP_INITIALS[space.group],
            label: GROUP_LABELS[space.group],
          },
        ])
      }
    }
  })

  it('declares one hex per colour group, and every one of them is a hex', () => {
    expect(Object.keys(GROUP_COLOURS).sort()).toEqual([...GROUPS].sort())
    for (const group of GROUPS) {
      expect([group, /^#[0-9a-f]{6}$/.test(GROUP_COLOURS[group])]).toEqual([group, true])
    }
    // Eight distinct values: two groups that share a hex would make the band lie.
    expect(new Set(Object.values(GROUP_COLOURS)).size).toBe(GROUPS.length)
  })

  it('prints the price exactly where the bank can sell, in the board’s money', () => {
    const priced: number[] = []
    for (const space of BOARD) {
      const spec = spaceTextureSpec(space.index)
      const expected = isPurchasable(space) ? formatMoney(purchasePrice(space.index)) : null
      expect([space.index, spec.price]).toEqual([space.index, expected])
      if (spec.price !== null) priced.push(space.index)
    }
    expect(priced).toEqual([...PURCHASABLE_INDEXES])
  })

  it('carries the printed rent lines of a street, straight from the deed table', () => {
    for (const space of BOARD) {
      const spec = spaceTextureSpec(space.index)
      if (space.kind !== 'street') {
        expect([space.index, spec.rents]).toEqual([space.index, null])
        continue
      }
      const deed = deedFor(space.index)
      const levels = [1, 2, 3, 4, HOTEL_LEVEL]
      expect([space.index, spec.rents]).toEqual([
        space.index,
        {
          base: formatMoney(rentForLevel(deed, 0)),
          group: formatMoney(deed.setRent),
          built: levels.map((level) => ({
            label: levelLabel(level),
            amount: formatMoney(rentForLevel(deed, level)),
          })),
        },
      ])
    }
  })

  it('carries no band and no rent on a corner, a tax or a deck', () => {
    // A railroad and a utility are purchasable and therefore priced, but they
    // have no colour group and no street deed: no band, no rent lines.
    for (const index of [
      SAMPLES.go,
      SAMPLES.jail,
      SAMPLES.freeParking,
      SAMPLES.goToJail,
      SAMPLES.tax,
      SAMPLES.luxuryTax,
      SAMPLES.deck,
      SAMPLES.railroad,
      SAMPLES.utility,
    ]) {
      const spec = spaceTextureSpec(index)
      expect([index, spec.band, spec.rents]).toEqual([index, null, null])
    }
  })

  it('keeps the side of the ring the grid gives the space', () => {
    // The band faces the centre of the board, which is a different physical edge
    // on every side of the ring; the painter needs it or the band lands outside.
    for (const space of BOARD) {
      expect([space.index, spaceTextureSpec(space.index).side]).toEqual([
        space.index,
        spaceSide(space.index),
      ])
    }
    expect(spaceTextureSpec(SAMPLES.street).side).toBe('bottom')
    expect(spaceTextureSpec(SAMPLES.jail).side).toBe('left')
    expect(spaceTextureSpec(SAMPLES.freeParking).side).toBe('top')
    expect(spaceTextureSpec(SAMPLES.goToJail).side).toBe('right')
  })

  it('refuses an index outside the board instead of painting the wrong space', () => {
    expect(() => spaceTextureSpec(BOARD_SIZE)).toThrow()
    expect(() => spaceTextureSpec(-1)).toThrow()
    expect(() => spaceTextureSpec(1.5)).toThrow()
  })
})

describe('the texture sizes', () => {
  it('is large enough to read a name on a cell', () => {
    // 256 px per cell: at a 26 px face that is about ten characters per line,
    // so "Avenida North Carolina" wraps in two and the longest name on the
    // board still fits when the near corner fills a third of the screen. Below
    // 256 the eye reads texture, not letters; above it each cell costs a
    // megabyte of GPU memory for a texel nobody can resolve at this angle.
    expect(CELL_TEXTURE_SIZE).toBeGreaterThanOrEqual(256)
    expect(Number.isInteger(Math.log2(CELL_TEXTURE_SIZE))).toBe(true)
  })

})

describe('the painters the scene calls', () => {
  it('exposes the cell painter, taking the context, the spec and a size', () => {
    // Never invoked here: this harness is Node with no DOM and no canvas. The
    // painters are checked by the headless capture (S12) and by the person
    // looking at the board.
    expect(typeof paintSpace).toBe('function')
    expect(paintSpace.length).toBe(3)
  })
})

describe('the way a cell is turned', () => {
  /** Where the top of the letters points, in the texture's own plane. */
  function textUp(side: 'bottom' | 'left' | 'top' | 'right'): { x: number; y: number } {
    const angle = textRotationFor(side)
    // The unrotated text points at the top of the image, which is (0, -1) here.
    return { x: Math.sin(angle), y: -Math.cos(angle) }
  }

  /** The middle of the board, seen from each side's own cell. */
  const inward = {
    bottom: { x: 0, y: -1 },
    top: { x: 0, y: 1 },
    left: { x: 1, y: 0 },
    right: { x: -1, y: 0 },
  } as const

  it('points the text at the middle of the board on all four sides', () => {
    // The rule the printed board follows, and the one the first capture got
    // wrong on three sides: the bands faced the centre while the text did not.
    for (const side of ['bottom', 'left', 'top', 'right'] as const) {
      const up = textUp(side)
      // A tolerance rather than a rounded pair: the trig residue is ~1e-17 and
      // rounding it can land on a signed zero, which is not a direction.
      expect([
        side,
        Math.abs(up.x - inward[side].x) < 1e-9,
        Math.abs(up.y - inward[side].y) < 1e-9,
      ]).toEqual([side, true, true])
    }
  })

  it('leaves the near row alone and turns the other three', () => {
    expect(textRotationFor('bottom')).toBe(0)
    expect(textRotationFor('top')).toBe(Math.PI)
    expect(textRotationFor('left')).toBe(Math.PI / 2)
    expect(textRotationFor('right')).toBe(-Math.PI / 2)
  })
})
