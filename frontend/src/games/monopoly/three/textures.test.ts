import { describe, expect, it } from 'vitest'
import type { ColorGroup } from '../board'
import { BOARD, BOARD_SIZE, PURCHASABLE_INDEXES, isPurchasable } from '../board'
import { HOTEL_LEVEL, deedFor, levelLabel, purchasePrice, rentForLevel } from '../deeds'
import { GROUP_INITIALS, GROUP_LABELS, KIND_LABELS, formatMoney } from '../display'
import { spaceSide } from '../grid'
import {
  CELL_TEXTURE_SIZE,
  GROUP_COLOURS,
  TABLE_SEED,
  TABLE_TEXTURE_SIZE,
  WOOD_TONES,
  paintSpace,
  paintTable,
  spaceTextureSpec,
  tableTextureSpec,
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

describe('the specification of the wooden table', () => {
  it('returns exactly the same table on two different calls', () => {
    // The visual check compares captures between runs, so the wood cannot
    // wobble: same seed, same planks, same grain.
    expect(tableTextureSpec()).toEqual(tableTextureSpec())
    expect(tableTextureSpec()).toEqual(tableTextureSpec(TABLE_SEED))
    expect(JSON.stringify(tableTextureSpec())).toBe(JSON.stringify(tableTextureSpec()))
  })

  it('builds a different table from a different seed', () => {
    const first = JSON.stringify(tableTextureSpec(TABLE_SEED))
    expect(first).not.toBe(JSON.stringify(tableTextureSpec(TABLE_SEED + 1)))
    expect(first).not.toBe(JSON.stringify(tableTextureSpec(TABLE_SEED + 7)))
  })

  it('tiles the whole texture with planks that keep the tonal steps it declares', () => {
    const spec = tableTextureSpec()
    expect(spec.planks.length).toBeGreaterThan(3)
    let edge = 0
    for (const plank of spec.planks) {
      expect(plank.width).toBeGreaterThan(0)
      expect(Math.abs(plank.start - edge)).toBeLessThan(1e-9)
      // A tone is an index into the palette, never an arbitrary value, so the
      // painter can map it without arithmetic of its own.
      expect(Number.isInteger(plank.tone)).toBe(true)
      expect(plank.tone).toBeGreaterThanOrEqual(0)
      expect(plank.tone).toBeLessThan(WOOD_TONES.length)
      edge = plank.start + plank.width
    }
    expect(Math.abs(edge - 1)).toBeLessThan(1e-9)
  })

  it('gives every plank grain lines that lie inside it', () => {
    const spec = tableTextureSpec()
    for (const plank of spec.planks) {
      expect(plank.grain.length).toBeGreaterThan(0)
      for (const line of plank.grain) {
        expect(line.offset).toBeGreaterThanOrEqual(0)
        expect(line.offset).toBeLessThanOrEqual(1)
        expect(line.start).toBeGreaterThanOrEqual(0)
        expect(line.start + line.length).toBeLessThanOrEqual(1 + 1e-9)
        expect(line.length).toBeGreaterThan(0)
        expect(line.weight).toBeGreaterThan(0)
        expect(line.weight).toBeLessThanOrEqual(1)
      }
    }
  })

  it('declares a warm palette the painter can step through', () => {
    expect(WOOD_TONES.length).toBeGreaterThanOrEqual(3)
    for (const tone of WOOD_TONES) {
      expect(/^#[0-9a-f]{6}$/.test(tone)).toBe(true)
    }
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

  it('is large enough to show a plank and its grain under the board', () => {
    // 1024 px across the table: seven planks are ~146 px each, so a two-pixel
    // grain line and the seam between planks survive mipmapping. 2048 would
    // quadruple the memory of a surface that sits out of focus behind the board.
    expect(TABLE_TEXTURE_SIZE).toBeGreaterThanOrEqual(1024)
    expect(Number.isInteger(Math.log2(TABLE_TEXTURE_SIZE))).toBe(true)
  })
})

describe('the painters the scene calls', () => {
  it('exposes one painter per texture, taking the context and the spec', () => {
    // Never invoked here: this harness is Node with no DOM and no canvas. The
    // painters are checked by the headless capture (S12) and by the person
    // looking at the board.
    expect(typeof paintSpace).toBe('function')
    expect(typeof paintTable).toBe('function')
    expect(paintSpace.length).toBe(3)
    expect(paintTable.length).toBe(3)
  })
})
