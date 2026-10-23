import { describe, expect, it } from 'vitest'
import type { ColorGroup } from '../board'
import { BOARD, BOARD_SIZE, PURCHASABLE_INDEXES, isPurchasable } from '../board'
import { HOTEL_LEVEL, deedFor, levelLabel, purchasePrice, rentForLevel } from '../deeds'
import { GROUP_INITIALS, GROUP_LABELS, KIND_LABELS, formatMoney, GAME_NAME, deckLabel } from '../display'
import { spaceSide } from '../grid'
import { spaceIcon } from './cellIcons'
import { RecordingContext } from './recordingContext'
import {
  CELL_TEXTURE_SIZE,
  CENTRE_FACE,
  CENTRE_TEXTURE_HEIGHT,
  CENTRE_TEXTURE_WIDTH,
  GROUP_COLOURS,
  DIE_TEXTURE_SIZE,
  PILE_FACE,
  PILE_TEXTURE_HEIGHT,
  PILE_TEXTURE_WIDTH,
  bandInnerRule,
  cellCaption,
  cellZones,
  centrePrint,
  deckPilePrint,
  diePips,
  paintCentre,
  paintDeckPile,
  paintSpace,
  spaceTextureSpec,
  textRotationFor,
} from './textures'
import type { CellZone } from './textures'

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
    // The signature is part of the scene's contract. The painter itself is
    // exercised below through a recording context (S7 of
    // ``monopoly-printed-cells.md``); what it *looks like* is still the headless
    // capture and the person looking at the board.
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

describe('what a deck pile prints on its face', () => {
  it('takes the deck name from the labels the rest of the screen reads', () => {
    // The pile must not invent a second copy of "Suerte" / "Caja de comunidad":
    // it names the deck the way the card and the panel name it.
    for (const deck of ['chance', 'community_chest']) {
      expect([deck, deckPilePrint(deck, 16).label]).toEqual([deck, deckLabel(deck)])
    }
  })

  it('prints the count the view publishes, including a spent deck', () => {
    expect([
      deckPilePrint('chance', 16).count,
      deckPilePrint('chance', 0).count,
      deckPilePrint('chance', 7).count,
    ]).toEqual(['16', '0', '7'])
  })

  it('prints no count when the view does not publish the decks', () => {
    // The image of the table can arrive before the deck counts do; the pile is
    // still on the board, so its face says which deck it is and nothing else.
    expect(deckPilePrint('community_chest', null).count).toBeNull()
  })

  it('falls back to the id for a deck the view does not name', () => {
    expect(deckPilePrint('guante-rojo', 3).label).toBe('guante-rojo')
  })
})

describe('what the middle of the board prints', () => {
  it('prints the game name the screen already publishes, not a copy', () => {
    expect(centrePrint().name).toBe(GAME_NAME)
  })
})

describe('the faces the board prints on', () => {
  it('gives every texture the shape of the face it covers', () => {
    // A texture whose aspect disagrees with its plane stretches the letters: one
    // wide and one tall, both checked against the world size of the face.
    expect(Math.abs(PILE_TEXTURE_HEIGHT - (PILE_TEXTURE_WIDTH * PILE_FACE.depth) / PILE_FACE.width)).toBeLessThan(1)
    expect(
      Math.abs(CENTRE_TEXTURE_HEIGHT - (CENTRE_TEXTURE_WIDTH * CENTRE_FACE.depth) / CENTRE_FACE.width),
    ).toBeLessThan(1)
  })

  it('gives the pile and the centre enough pixels to be read from a seat', () => {
    // A pile is about the size of a cell, and a cell is 256 px (see above); the
    // middle of the board is six cells wide, so it asks for more.
    expect(PILE_TEXTURE_WIDTH).toBeGreaterThanOrEqual(CELL_TEXTURE_SIZE)
    expect(CENTRE_TEXTURE_WIDTH).toBeGreaterThanOrEqual(PILE_TEXTURE_WIDTH * 2)
  })
})

describe('the pile and centre painters', () => {
  it('exposes both painters, taking the context and what they print', () => {
    // Never invoked here: Node, no DOM, no canvas. The faces are judged in the
    // headless capture and by the person looking at the table.
    expect([typeof paintDeckPile, typeof paintCentre]).toEqual(['function', 'function'])
    expect([paintDeckPile.length, paintCentre.length]).toEqual([3, 3])
  })
})

describe('the pips of one die', () => {
  const VALUES = [1, 2, 3, 4, 5, 6] as const

  it('prints as many pips as the value says', () => {
    expect(VALUES.map((value) => [value, diePips(value).length])).toEqual(
      VALUES.map((value) => [value, value]),
    )
  })

  it('keeps every pip on the face and none on top of another', () => {
    for (const value of VALUES) {
      const pips = diePips(value)
      for (const pip of pips) {
        expect([value, pip.x > 0.1 && pip.x < 0.9, pip.y > 0.1 && pip.y < 0.9]).toEqual([
          value,
          true,
          true,
        ])
      }
      expect([value, new Set(pips.map((pip) => `${pip.x}:${pip.y}`)).size]).toEqual([value, value])
    }
  })

  it('lays them out symmetrically, the way a real die does', () => {
    // Every printed layout is unchanged by a half turn of the face, which is what
    // keeps a six from looking like a badly placed five.
    for (const value of VALUES) {
      const pips = diePips(value)
      const mirrored = pips.map((pip) => `${(1 - pip.x).toFixed(6)}:${(1 - pip.y).toFixed(6)}`)
      const own = pips.map((pip) => `${pip.x.toFixed(6)}:${pip.y.toFixed(6)}`)
      expect([value, mirrored.sort()]).toEqual([value, own.sort()])
    }
  })

  it('puts the single pip in the middle and the six in two columns', () => {
    expect(diePips(1)).toEqual([{ x: 0.5, y: 0.5 }])
    const columns = new Set(diePips(6).map((pip) => pip.x))
    expect([columns.size, diePips(6).length]).toEqual([2, 6])
  })

  it('gives the face enough pixels to draw a pip', () => {
    expect(DIE_TEXTURE_SIZE).toBeGreaterThanOrEqual(128)
    expect(Number.isInteger(Math.log2(DIE_TEXTURE_SIZE))).toBe(true)
  })
})

describe('the illustration of a cell', () => {
  it('travels in the specification, so the painter never asks the board again', () => {
    for (const space of BOARD) {
      expect([space.index, spaceTextureSpec(space.index).icon]).toEqual([
        space.index,
        spaceIcon(space),
      ])
    }
  })
})

describe('the rule that closes the colour band', () => {
  const SIZE = 100
  const THICKNESS = 18
  const RULE = 2

  it('sits on the paper side of the band on all four edges', () => {
    // The band occupies the edge that faces the centre; the rule is painted on
    // the paper right next to it, so the printed band is bounded on both sides.
    expect(bandInnerRule('bottom', SIZE, THICKNESS, RULE)).toEqual({
      x: 0,
      y: 18,
      width: 100,
      height: 2,
    })
    expect(bandInnerRule('top', SIZE, THICKNESS, RULE)).toEqual({
      x: 0,
      y: 80,
      width: 100,
      height: 2,
    })
    expect(bandInnerRule('left', SIZE, THICKNESS, RULE)).toEqual({
      x: 80,
      y: 0,
      width: 2,
      height: 100,
    })
    expect(bandInnerRule('right', SIZE, THICKNESS, RULE)).toEqual({
      x: 18,
      y: 0,
      width: 2,
      height: 100,
    })
  })
})

describe('the caption a cell prints', () => {
  const caption = (index: number): string | null => cellCaption(spaceTextureSpec(index))

  it('translates the English names and leaves the Spanish ones alone', () => {
    expect(caption(0)).toBe('Salida')
    expect(caption(2)).toBe('Caja de comunidad')
    expect(caption(4)).toBe('Impuesto sobre los ingresos')
    expect(caption(7)).toBe('Suerte')
    expect(caption(20)).toBe('Parada libre')
    expect(caption(30)).toBe('Ir a la cárcel')
    expect(caption(38)).toBe('Impuesto de lujo')
    // "Cárcel / Solo visitando" already says the kind in Spanish: printing the
    // caption would be the same word twice on a 30 mm tile.
    expect(caption(10)).toBeNull()
  })

  it('never prints a caption on a street, a railroad or a utility', () => {
    for (const space of BOARD) {
      if (space.kind === 'street' || space.kind === 'railroad' || space.kind === 'utility') {
        expect([space.index, caption(space.index)]).toEqual([space.index, null])
      }
    }
  })
})

describe('the rows of a cell face', () => {
  const BOXES = [
    { width: 225, height: 225 },
    { width: 180, height: 225 },
    { width: 225, height: 179 },
    { width: 180, height: 179 },
  ]

  it('keeps every row inside the face, square and in printed order', () => {
    for (const space of BOARD) {
      const spec = spaceTextureSpec(space.index)
      for (const box of BOXES) {
        const zones = cellZones(spec, box, CELL_TEXTURE_SIZE)
        const rows = [
          zones.caption,
          zones.initials,
          zones.name,
          zones.icon,
          zones.price,
        ].filter((zone): zone is CellZone => zone !== null)
        for (const row of rows) {
          expect([
            space.index,
            box.width,
            box.height,
            row.width > 0,
            row.height > 0,
            row.x >= 0,
            row.x + row.width <= box.width + 1,
            row.y >= 0,
            row.y + row.height <= box.height + 1,
          ]).toEqual([
            space.index,
            box.width,
            box.height,
            true,
            true,
            true,
            true,
            true,
            true,
          ])
        }
        const ordered = rows.every(
          (row, index) => index === 0 || row.y >= rows[index - 1].y + rows[index - 1].height,
        )
        expect([space.index, box.width, box.height, ordered]).toEqual([
          space.index,
          box.width,
          box.height,
          true,
        ])
        if (zones.icon !== null) {
          expect([space.index, zones.icon.width]).toEqual([space.index, zones.icon.height])
        }
        if (zones.price !== null) {
          expect([space.index, zones.price.y + zones.price.height]).toEqual([space.index, box.height])
        }
        expect([space.index, zones.name.height >= 20]).toEqual([space.index, true])
      }
    }
  })
})

describe('the cell painter', () => {
  const BAND = Math.round(CELL_TEXTURE_SIZE * 0.18)
  const BANDED = { bottom: 1, left: 11, top: 21, right: 31 } as const
  const SIDES = ['bottom', 'left', 'top', 'right'] as const

  function painted(index: number): {
    spec: ReturnType<typeof spaceTextureSpec>
    ctx: RecordingContext
  } {
    const spec = spaceTextureSpec(index)
    const ctx = new RecordingContext()
    paintSpace(ctx as unknown as CanvasRenderingContext2D, spec, CELL_TEXTURE_SIZE)
    return { spec, ctx }
  }

  it('paints every space of the board without throwing', () => {
    for (const space of BOARD) {
      const { ctx } = painted(space.index)
      expect([space.index, ctx.calls.length > 10]).toEqual([space.index, true])
    }
  })

  it('puts the band on the edge that faces the centre, on all four sides', () => {
    const expected = {
      bottom: [0, 0, CELL_TEXTURE_SIZE, BAND],
      left: [CELL_TEXTURE_SIZE - BAND, 0, BAND, CELL_TEXTURE_SIZE],
      top: [0, CELL_TEXTURE_SIZE - BAND, CELL_TEXTURE_SIZE, BAND],
      right: [0, 0, BAND, CELL_TEXTURE_SIZE],
    }
    for (const side of SIDES) {
      const { spec, ctx } = painted(BANDED[side])
      expect([side, spec.side]).toEqual([side, side])
      const call = ctx.calls.find(
        (candidate) => candidate.op === 'fillRect' && candidate.ink === spec.band?.colour,
      )
      expect([side, call?.args]).toEqual([side, expected[side]])
    }
  })

  it('closes the band with exactly one ink rule on the paper side', () => {
    const rule = Math.max(1, Math.round(CELL_TEXTURE_SIZE * 0.008))
    for (const side of SIDES) {
      const { ctx } = painted(BANDED[side])
      const borderInk = ctx.of('strokeRect')[0].ink
      const rules = ctx.of('fillRect').filter((call) => call.ink === borderInk)
      expect([side, rules.length]).toEqual([side, 1])
      expect([side, rules[0].args]).toEqual([
        side,
        Object.values(bandInnerRule(side, CELL_TEXTURE_SIZE, BAND, rule)),
      ])
    }
  })

  it('prints the name in uppercase, letter by letter, without a cut word', () => {
    // The longest name on the board, on the narrowest face: if this one fits
    // without an ellipsis, the fitting loop is doing its job.
    const { spec, ctx } = painted(32)
    const letters = ctx
      .of('fillText')
      .filter(
        (call) =>
          call.text !== undefined && [...call.text].length === 1 && call.text !== ' ',
      )
      .map((call) => call.text)
      .join('')
    expect(letters).toContain(spec.name.toUpperCase().replaceAll(' ', ''))
    expect(letters).not.toContain(spec.name.replaceAll(' ', ''))
    expect(ctx.texts().some((text) => text.includes('…'))).toBe(false)
  })

  it('prints the price once, at the foot, and never on a space the bank cannot sell', () => {
    for (const index of PURCHASABLE_INDEXES) {
      const { spec, ctx } = painted(index)
      const prices = ctx.texts().filter((text) => text === spec.price)
      expect([index, prices.length]).toEqual([index, 1])
    }
    for (const space of BOARD.filter((candidate) => !isPurchasable(candidate))) {
      const { ctx } = painted(space.index)
      expect([space.index, ctx.texts().some((text) => /^\$\d/.test(text))]).toEqual([
        space.index,
        false,
      ])
    }
  })

  it('draws an illustration exactly where the space has one', () => {
    for (const space of BOARD) {
      const { spec, ctx } = painted(space.index)
      expect([space.index, ctx.of('clip').length]).toEqual([
        space.index,
        spec.icon === null ? 0 : 1,
      ])
    }
  })
})
