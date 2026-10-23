import { describe, expect, it } from 'vitest'
import { BOARD } from '../board'
import type { CellIcon, IconShape } from './cellIcons'
import {
  ICON_ACCENTS,
  ICON_BOX,
  ICON_SHAPES,
  paintIcon,
  spaceIcon,
} from './cellIcons'
import type { IconPalette } from './cellIcons'
import { RecordingContext } from './recordingContext'

/** Every illustration the board can print, in the order the sheet reads them. */
const ICONS: readonly CellIcon[] = [
  'go',
  'train',
  'faucet',
  'bulb',
  'question',
  'chest',
  'note',
  'ring',
  'jail',
  'car',
  'police',
]

const PALETTE: IconPalette = { ink: '#241f2e', paper: '#e9efe6' }

/** The box a shape can reach, stroke width included. */
function bounds(shape: IconShape): {
  minX: number
  maxX: number
  minY: number
  maxY: number
} {
  if (shape.kind === 'rect') {
    return {
      minX: shape.x,
      maxX: shape.x + shape.width,
      minY: shape.y,
      maxY: shape.y + shape.height,
    }
  }
  if (shape.kind === 'circle') {
    return {
      minX: shape.x - shape.radius,
      maxX: shape.x + shape.radius,
      minY: shape.y - shape.radius,
      maxY: shape.y + shape.radius,
    }
  }
  if (shape.kind === 'arc') {
    // A conservative box: the arc cannot leave the full circle it belongs to.
    return {
      minX: shape.x - shape.radius - shape.width / 2,
      maxX: shape.x + shape.radius + shape.width / 2,
      minY: shape.y - shape.radius - shape.width / 2,
      maxY: shape.y + shape.radius + shape.width / 2,
    }
  }
  if (shape.kind === 'text') {
    // Text is measured by an engine the harness does not have, so its box is an
    // approximation: one em per letter is generous enough to catch a stray
    // coordinate without pretending to know the font's metrics.
    const halfWidth = (shape.size * shape.text.length) / 2
    return {
      minX: shape.x - halfWidth,
      maxX: shape.x + halfWidth,
      minY: shape.y - shape.size / 2,
      maxY: shape.y + shape.size / 2,
    }
  }
  const half = shape.kind === 'line' ? shape.width / 2 : 0
  const xs: number[] = []
  const ys: number[] = []
  for (let index = 0; index < shape.points.length; index += 2) {
    xs.push(shape.points[index])
    ys.push(shape.points[index + 1])
  }
  return {
    minX: Math.min(...xs) - half,
    maxX: Math.max(...xs) + half,
    minY: Math.min(...ys) - half,
    maxY: Math.max(...ys) + half,
  }
}

describe('the illustration of one space', () => {
  it('gives every space the picture the sheet prints on it', () => {
    const expected: Record<string, CellIcon | null> = {
      go: 'go',
      street: null,
      railroad: 'train',
      chance: 'question',
      community_chest: 'chest',
      income_tax: 'note',
      luxury_tax: 'ring',
      jail: 'jail',
      free_parking: 'car',
      go_to_jail: 'police',
    }
    for (const space of BOARD) {
      if (space.kind === 'utility') continue
      expect([space.index, space.kind, spaceIcon(space)]).toEqual([
        space.index,
        space.kind,
        expected[space.kind] ?? null,
      ])
    }
  })

  it('draws Water Works and the electric company differently', () => {
    // The printed sheet does not draw the two utilities the same, and the kind
    // alone cannot tell them apart: the board's order is what names them.
    const electric = BOARD.find((space) => space.kind === 'utility' && space.index === 12)
    const water = BOARD.find((space) => space.kind === 'utility' && space.index === 28)
    expect([spaceIcon(electric!), spaceIcon(water!)]).toEqual(['bulb', 'faucet'])
    expect(spaceIcon({ index: 12, kind: 'utility' })).not.toBe(
      spaceIcon({ index: 28, kind: 'utility' }),
    )
  })

  it('gives all four railroads the locomotive', () => {
    const railroads = BOARD.filter((space) => space.kind === 'railroad')
    expect(railroads.length).toBe(4)
    expect(railroads.map((space) => spaceIcon(space))).toEqual(['train', 'train', 'train', 'train'])
  })

  it('leaves a street without an illustration', () => {
    const streets = BOARD.filter((space) => space.kind === 'street')
    expect(streets.length).toBe(22)
    expect(streets.every((space) => spaceIcon(space) === null)).toBe(true)
  })
})

describe('the catalogue of illustrations', () => {
  it('has an entry for every icon and no extra key', () => {
    expect(Object.keys(ICON_SHAPES).sort()).toEqual([...ICONS].sort())
  })

  it('gives every illustration the shapes it needs to read', () => {
    // The arrow of GO is a head and a tail; every other illustration is a
    // silhouette plus at least one paper detail. One shape alone would be a
    // blob, and the sheet never prints one.
    for (const icon of ICONS) {
      expect([icon, ICON_SHAPES[icon].length >= 2]).toEqual([icon, true])
    }
  })

  it('keeps every shape inside the 0..100 box', () => {
    for (const icon of ICONS) {
      for (const shape of ICON_SHAPES[icon]) {
        const box = bounds(shape)
        expect([
          icon,
          shape.kind,
          box.minX >= -0.001,
          box.maxX <= ICON_BOX + 0.001,
          box.minY >= -0.001,
          box.maxY <= ICON_BOX + 0.001,
        ]).toEqual([icon, shape.kind, true, true, true, true])
      }
    }
  })

  it('uses one printed spot colour per illustration that has one', () => {
    for (const [icon, colour] of Object.entries(ICON_ACCENTS)) {
      expect([icon, /^#[0-9a-f]{6}$/.test(colour)]).toEqual([icon, true])
      expect([icon, ICONS.includes(icon as CellIcon)]).toEqual([icon, true])
    }
    // The three red illustrations and the gold ring are exactly the exceptions
    // the sheet paints; everything else is ink on paper.
    expect(Object.keys(ICON_ACCENTS).sort()).toEqual(['car', 'go', 'question', 'ring'])
  })
})

describe('the icon painter', () => {
  it('clips every illustration to its own box', () => {
    for (const icon of ICONS) {
      const ctx = new RecordingContext()
      paintIcon(ctx as unknown as CanvasRenderingContext2D, icon, 64, PALETTE)
      const clip = ctx.of('rect').find((call) => call.args.join() === '0,0,100,100')
      expect([icon, clip === undefined]).toEqual([icon, false])
      expect([icon, ctx.of('clip').length]).toEqual([icon, 1])
    }
  })

  it('scales the 0..100 data to the size the cell gives it', () => {
    const ctx = new RecordingContext()
    paintIcon(ctx as unknown as CanvasRenderingContext2D, 'train', 50, PALETTE)
    const scale = ctx.of('scale')[0]
    expect(scale.args).toEqual([0.5, 0.5])
  })

  it('draws ink for every illustration, not just a clip', () => {
    for (const icon of ICONS) {
      const ctx = new RecordingContext()
      paintIcon(ctx as unknown as CanvasRenderingContext2D, icon, 100, PALETTE)
      const drawn = ctx.calls.filter(
        (call) => call.op === 'fill' || call.op === 'stroke' || call.op === 'fillRect',
      )
      expect([icon, drawn.length >= 2]).toEqual([icon, true])
      expect([icon, drawn.every((call) => call.ink === PALETTE.ink || call.ink === PALETTE.paper || call.ink === ICON_ACCENTS[icon])]).toEqual([icon, true])
    }
  })

  it('resolves the spot colour of the red and gold illustrations', () => {
    const red = new RecordingContext()
    paintIcon(red as unknown as CanvasRenderingContext2D, 'question', 100, PALETTE)
    expect(red.calls.some((call) => call.ink === ICON_ACCENTS.question)).toBe(true)

    const gold = new RecordingContext()
    paintIcon(gold as unknown as CanvasRenderingContext2D, 'ring', 100, PALETTE)
    expect(gold.calls.some((call) => call.ink === ICON_ACCENTS.ring)).toBe(true)

    // A utility has no spot colour: it stays ink and paper.
    const bulb = new RecordingContext()
    paintIcon(bulb as unknown as CanvasRenderingContext2D, 'bulb', 100, PALETTE)
    expect(bulb.calls.some((call) => call.ink === ICON_ACCENTS.question)).toBe(false)
  })

  it('prints the bank’s seal in the bill with a type the painter already draws', () => {
    const ctx = new RecordingContext()
    paintIcon(ctx as unknown as CanvasRenderingContext2D, 'note', 100, PALETTE)
    expect(ctx.texts()).toEqual(['$'])
  })
})
