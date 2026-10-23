/**
 * The illustration printed on each cell of the board (S1 and S2 of
 * ``monopoly-printed-cells.md``).
 *
 * The printed board does not only paint a colour band and a name: the railroads
 * carry a steam locomotive, the two utilities a faucet and a bulb, the decks a
 * chest and a question mark, the taxes a bill and a ring, and the four corners
 * the arrow of GO, the bars of the jail, the car of Free Parking and the officer
 * of Go to Jail. The scene's cells were missing that half of the print.
 *
 * **No binary asset**, because S3 of ``monopoly-3d-table.md`` still rules: an
 * illustration is data, and ``paintIcon`` draws it on the same canvas as the
 * name. The shapes are the same idea as the flat tokens of ``figureInk.ts``,
 * simplified to primitives -- a rectangle, a circle, a polygon, a polyline, an
 * arc and a text -- instead of traced loops, because an icon is read at about a
 * sixth of a cell and a trace of the scanned sheet would only add noise.
 *
 * Every shape lives in a **0..100 box with ``y`` pointing down**, like the
 * tokens, and is painted back to front: later shapes cover earlier ones. A
 * ``paper`` shape is not transparent: it is the cell's own paper, used to cut a
 * window, a wheel hub or a facet out of an ink silhouette, which is why order
 * matters and why the painter clips the icon to its box -- a stray coordinate
 * must not bleed into the name or the price.
 *
 * Pure and free of ``three``: the catalogue is pinned by the DOM-less harness,
 * and only ``paintIcon`` needs a 2D context.
 */

import type { SpaceKind } from '../board'

/** The illustrations the board prints. */
export type CellIcon =
  | 'go'
  | 'train'
  | 'faucet'
  | 'bulb'
  | 'question'
  | 'chest'
  | 'note'
  | 'ring'
  | 'jail'
  | 'car'
  | 'police'

/** The side of the box every shape lives in. */
export const ICON_BOX = 100

/**
 * Which ink a shape uses.
 *
 * ``ink`` and ``paper`` are the cell's own two colours, passed to the painter so
 * the illustration cannot disagree with the face it sits on. ``accent`` is the
 * one printed spot colour of that illustration (the red of GO and of the car,
 * the gold of the ring, the red of the question mark), and the few icons that
 * have no spot colour simply never use it.
 */
export type IconInk = 'ink' | 'paper' | 'accent'

/** A rectangle, in the 0..100 box. */
export type IconRect = {
  kind: 'rect'
  x: number
  y: number
  width: number
  height: number
  ink: IconInk
}

/** A filled circle. */
export type IconCircle = {
  kind: 'circle'
  x: number
  y: number
  radius: number
  ink: IconInk
}

/** A filled polygon; ``points`` is ``x0, y0, x1, y1, ...``. */
export type IconPolygon = {
  kind: 'polygon'
  points: readonly number[]
  ink: IconInk
}

/** A stroked polyline with round caps; ``points`` is ``x0, y0, x1, y1, ...``. */
export type IconLine = {
  kind: 'line'
  points: readonly number[]
  width: number
  ink: IconInk
}

/** A stroked arc of a circle, from ``from`` to ``to`` in radians, clockwise. */
export type IconArc = {
  kind: 'arc'
  x: number
  y: number
  radius: number
  from: number
  to: number
  width: number
  ink: IconInk
}

/** Centred text, in the box's own units. */
export type IconText = {
  kind: 'text'
  text: string
  x: number
  y: number
  size: number
  weight: number
  tracking: number
  ink: IconInk
}

/** One primitive of an illustration. */
export type IconShape = IconRect | IconCircle | IconPolygon | IconLine | IconArc | IconText

/**
 * The one spot colour of each illustration, when it has one.
 *
 * They mirror the printed sheet and nothing else in the app: GO's arrow, the
 * question mark and the car are red, and the ring is gold. An icon that is not
 * here is drawn in ink and paper only, which is what keeps most of the board
 * black and makes these four read as the exceptions they are on the print.
 */
export const ICON_ACCENTS: Partial<Record<CellIcon, string>> = {
  go: '#c8102e',
  question: '#c8102e',
  car: '#c8102e',
  ring: '#e0a70d',
}

/**
 * The illustration of one space, or ``null`` for a street.
 *
 * The two utilities are told apart by their position, which is a fact of the
 * classic board: 12 is the electric company and 28 is Water Works. The kind
 * alone cannot name them, and the printed board does not draw them the same.
 */
export function spaceIcon(space: { index: number; kind: SpaceKind }): CellIcon | null {
  switch (space.kind) {
    case 'go':
      return 'go'
    case 'railroad':
      return 'train'
    case 'utility':
      return space.index === 12 ? 'bulb' : 'faucet'
    case 'chance':
      return 'question'
    case 'community_chest':
      return 'chest'
    case 'income_tax':
      return 'note'
    case 'luxury_tax':
      return 'ring'
    case 'jail':
      return 'jail'
    case 'free_parking':
      return 'car'
    case 'go_to_jail':
      return 'police'
    case 'street':
      return null
  }
}

/**
 * The steam locomotive of the four railroads: rail, three wheels, boiler with
 * its smokebox, chimney, dome and cab, facing the start of the circuit.
 *
 * It is drawn in one heavy weight on purpose: at the size a cell gives it, the
 * details of the scanned sheet would merge, so what survives is the silhouette
 * that says "train" -- boiler, cab, chimney and drivers.
 */
const TRAIN: readonly IconShape[] = [
  { kind: 'rect', x: 2, y: 88, width: 96, height: 6, ink: 'ink' },
  { kind: 'polygon', points: [2, 86, 26, 86, 26, 56], ink: 'ink' },
  { kind: 'rect', x: 22, y: 42, width: 44, height: 36, ink: 'ink' },
  { kind: 'circle', x: 27, y: 60, radius: 10, ink: 'paper' },
  { kind: 'rect', x: 33, y: 22, width: 13, height: 22, ink: 'ink' },
  { kind: 'rect', x: 26, y: 16, width: 27, height: 8, ink: 'ink' },
  { kind: 'circle', x: 54, y: 40, radius: 7, ink: 'ink' },
  { kind: 'rect', x: 64, y: 28, width: 27, height: 44, ink: 'ink' },
  { kind: 'rect', x: 70, y: 36, width: 15, height: 15, ink: 'paper' },
  { kind: 'rect', x: 60, y: 20, width: 33, height: 9, ink: 'ink' },
  { kind: 'circle', x: 30, y: 78, radius: 11, ink: 'ink' },
  { kind: 'circle', x: 30, y: 78, radius: 4, ink: 'paper' },
  { kind: 'circle', x: 62, y: 74, radius: 14, ink: 'ink' },
  { kind: 'circle', x: 62, y: 74, radius: 5, ink: 'paper' },
  { kind: 'circle', x: 88, y: 82, radius: 8, ink: 'ink' },
  { kind: 'circle', x: 88, y: 82, radius: 3, ink: 'paper' },
]

/** The faucet of Water Works: wall plate, elbow, valve and two drops. */
const FAUCET: readonly IconShape[] = [
  { kind: 'rect', x: 86, y: 24, width: 8, height: 34, ink: 'ink' },
  { kind: 'rect', x: 46, y: 32, width: 44, height: 14, ink: 'ink' },
  { kind: 'circle', x: 56, y: 39, radius: 10, ink: 'ink' },
  { kind: 'rect', x: 48, y: 39, width: 16, height: 16, ink: 'ink' },
  { kind: 'rect', x: 43, y: 52, width: 26, height: 8, ink: 'ink' },
  { kind: 'rect', x: 40, y: 59, width: 32, height: 6, ink: 'ink' },
  { kind: 'rect', x: 47, y: 14, width: 6, height: 22, ink: 'ink' },
  { kind: 'rect', x: 34, y: 9, width: 32, height: 7, ink: 'ink' },
  { kind: 'circle', x: 34, y: 12, radius: 5, ink: 'ink' },
  { kind: 'circle', x: 66, y: 12, radius: 5, ink: 'ink' },
  { kind: 'circle', x: 56, y: 72, radius: 5, ink: 'ink' },
  { kind: 'circle', x: 56, y: 85, radius: 3, ink: 'ink' },
]

/** The bulb of the electric company: glass, filament, screw base and rays. */
const BULB: readonly IconShape[] = [
  { kind: 'line', points: [6, 26, 18, 30], width: 4, ink: 'ink' },
  { kind: 'line', points: [2, 42, 16, 42], width: 4, ink: 'ink' },
  { kind: 'line', points: [6, 58, 18, 54], width: 4, ink: 'ink' },
  { kind: 'line', points: [94, 26, 82, 30], width: 4, ink: 'ink' },
  { kind: 'line', points: [98, 42, 84, 42], width: 4, ink: 'ink' },
  { kind: 'line', points: [94, 58, 82, 54], width: 4, ink: 'ink' },
  { kind: 'circle', x: 50, y: 40, radius: 25, ink: 'ink' },
  { kind: 'circle', x: 50, y: 40, radius: 18, ink: 'paper' },
  { kind: 'line', points: [39, 44, 45, 31, 50, 44, 55, 31, 61, 44], width: 3, ink: 'ink' },
  { kind: 'line', points: [50, 44, 50, 56], width: 3, ink: 'ink' },
  { kind: 'rect', x: 40, y: 63, width: 20, height: 6, ink: 'ink' },
  { kind: 'rect', x: 42, y: 71, width: 16, height: 5, ink: 'ink' },
  { kind: 'rect', x: 45, y: 78, width: 10, height: 5, ink: 'ink' },
]

/** The chest of Community Chest: lid, body, straps and lock. */
const CHEST: readonly IconShape[] = [
  { kind: 'rect', x: 12, y: 24, width: 76, height: 28, ink: 'ink' },
  { kind: 'rect', x: 18, y: 30, width: 64, height: 16, ink: 'paper' },
  { kind: 'rect', x: 16, y: 48, width: 68, height: 38, ink: 'ink' },
  { kind: 'rect', x: 22, y: 54, width: 56, height: 26, ink: 'paper' },
  { kind: 'rect', x: 25, y: 48, width: 7, height: 38, ink: 'ink' },
  { kind: 'rect', x: 68, y: 48, width: 7, height: 38, ink: 'ink' },
  { kind: 'rect', x: 43, y: 42, width: 14, height: 18, ink: 'ink' },
  { kind: 'circle', x: 50, y: 49, radius: 3, ink: 'paper' },
  { kind: 'rect', x: 49, y: 52, width: 2, height: 4, ink: 'paper' },
]

/** The question mark of Chance: the printed hook, its stem and the dot. */
const QUESTION: readonly IconShape[] = [
  {
    kind: 'arc',
    x: 50,
    y: 32,
    radius: 18,
    from: 0.8 * Math.PI,
    to: 2.25 * Math.PI,
    width: 13,
    ink: 'accent',
  },
  { kind: 'line', points: [62, 45, 50, 53, 50, 60], width: 13, ink: 'accent' },
  { kind: 'circle', x: 50, y: 77, radius: 8, ink: 'accent' },
]

/** The bill of Income Tax: note, border and the bank's seal. */
const NOTE: readonly IconShape[] = [
  { kind: 'rect', x: 6, y: 30, width: 88, height: 40, ink: 'ink' },
  { kind: 'rect', x: 12, y: 36, width: 76, height: 28, ink: 'paper' },
  { kind: 'circle', x: 50, y: 50, radius: 12, ink: 'ink' },
  { kind: 'circle', x: 50, y: 50, radius: 8, ink: 'paper' },
  { kind: 'text', text: '$', x: 50, y: 50, size: 13, weight: 800, tracking: 0, ink: 'ink' },
  { kind: 'rect', x: 19, y: 43, width: 9, height: 4, ink: 'ink' },
  { kind: 'rect', x: 19, y: 55, width: 9, height: 4, ink: 'ink' },
  { kind: 'rect', x: 72, y: 43, width: 9, height: 4, ink: 'ink' },
  { kind: 'rect', x: 72, y: 55, width: 9, height: 4, ink: 'ink' },
]

/** The ring of Luxury Tax: gold band and a cut gem. */
const RING: readonly IconShape[] = [
  { kind: 'circle', x: 50, y: 62, radius: 24, ink: 'accent' },
  { kind: 'circle', x: 50, y: 62, radius: 15, ink: 'paper' },
  { kind: 'polygon', points: [50, 6, 68, 24, 50, 44, 32, 24], ink: 'accent' },
  { kind: 'line', points: [32, 24, 68, 24], width: 2, ink: 'paper' },
  { kind: 'line', points: [41, 24, 50, 44], width: 2, ink: 'paper' },
  { kind: 'line', points: [59, 24, 50, 44], width: 2, ink: 'paper' },
]

/** The bars of the jail, behind their frame. */
const JAIL: readonly IconShape[] = [
  { kind: 'rect', x: 10, y: 16, width: 80, height: 70, ink: 'ink' },
  { kind: 'rect', x: 18, y: 24, width: 64, height: 54, ink: 'paper' },
  { kind: 'rect', x: 24, y: 24, width: 6, height: 54, ink: 'ink' },
  { kind: 'rect', x: 36, y: 24, width: 6, height: 54, ink: 'ink' },
  { kind: 'rect', x: 48, y: 24, width: 6, height: 54, ink: 'ink' },
  { kind: 'rect', x: 60, y: 24, width: 6, height: 54, ink: 'ink' },
  { kind: 'rect', x: 72, y: 24, width: 6, height: 54, ink: 'ink' },
  { kind: 'rect', x: 18, y: 44, width: 64, height: 5, ink: 'ink' },
]

/** The car of Free Parking: body, cabin, windows, wheels and light. */
const CAR: readonly IconShape[] = [
  { kind: 'rect', x: 4, y: 46, width: 92, height: 24, ink: 'ink' },
  { kind: 'rect', x: 9, y: 50, width: 82, height: 16, ink: 'accent' },
  { kind: 'polygon', points: [26, 50, 34, 28, 66, 28, 74, 50], ink: 'accent' },
  { kind: 'rect', x: 33, y: 32, width: 15, height: 13, ink: 'paper' },
  { kind: 'rect', x: 52, y: 32, width: 15, height: 13, ink: 'paper' },
  { kind: 'rect', x: 47, y: 32, width: 3, height: 13, ink: 'accent' },
  { kind: 'rect', x: 84, y: 53, width: 6, height: 6, ink: 'paper' },
  { kind: 'circle', x: 26, y: 74, radius: 11, ink: 'ink' },
  { kind: 'circle', x: 26, y: 74, radius: 4, ink: 'paper' },
  { kind: 'circle', x: 74, y: 74, radius: 11, ink: 'ink' },
  { kind: 'circle', x: 74, y: 74, radius: 4, ink: 'paper' },
]

/** The officer of Go to Jail, pointing the way to the cells. */
const POLICE: readonly IconShape[] = [
  { kind: 'rect', x: 34, y: 0, width: 32, height: 7, ink: 'ink' },
  { kind: 'rect', x: 26, y: 7, width: 48, height: 7, ink: 'ink' },
  { kind: 'circle', x: 50, y: 24, radius: 11, ink: 'ink' },
  { kind: 'rect', x: 45, y: 33, width: 10, height: 5, ink: 'paper' },
  { kind: 'polygon', points: [36, 38, 64, 38, 72, 74, 28, 74], ink: 'ink' },
  { kind: 'circle', x: 50, y: 48, radius: 2, ink: 'paper' },
  { kind: 'circle', x: 50, y: 57, radius: 2, ink: 'paper' },
  { kind: 'line', points: [63, 42, 89, 29], width: 8, ink: 'ink' },
  { kind: 'circle', x: 91, y: 28, radius: 5, ink: 'ink' },
  { kind: 'line', points: [37, 42, 27, 58], width: 8, ink: 'ink' },
  { kind: 'rect', x: 29, y: 65, width: 42, height: 4, ink: 'paper' },
  { kind: 'rect', x: 34, y: 74, width: 10, height: 22, ink: 'ink' },
  { kind: 'rect', x: 56, y: 74, width: 10, height: 22, ink: 'ink' },
]

/** The arrow of GO: a heavy left-pointing arrow across the face. */
const GO: readonly IconShape[] = [
  { kind: 'polygon', points: [2, 48, 36, 20, 36, 76], ink: 'accent' },
  { kind: 'rect', x: 36, y: 38, width: 62, height: 20, ink: 'accent' },
]

/**
 * Every illustration, back to front.
 *
 * The catalogue is exhaustive over ``CellIcon`` on purpose: adding an icon
 * without drawing it is a compile error, the same guard the token figures use.
 */
export const ICON_SHAPES: Record<CellIcon, readonly IconShape[]> = {
  go: GO,
  train: TRAIN,
  faucet: FAUCET,
  bulb: BULB,
  question: QUESTION,
  chest: CHEST,
  note: NOTE,
  ring: RING,
  jail: JAIL,
  car: CAR,
  police: POLICE,
}

/** The two inks an illustration borrows from the cell it sits on. */
export type IconPalette = { ink: string; paper: string }

/** The colour of one shape, resolving the icon's spot colour. */
function inkOf(icon: CellIcon, ink: IconInk, palette: IconPalette): string {
  if (ink === 'ink') return palette.ink
  if (ink === 'paper') return palette.paper
  return ICON_ACCENTS[icon] ?? palette.ink
}

/** Draw one text shape, letter by letter so the tracking is exact. */
function paintText(
  ctx: CanvasRenderingContext2D,
  shape: IconText,
  colour: string,
): void {
  ctx.font = `${shape.weight} ${shape.size}px system-ui, sans-serif`
  ctx.fillStyle = colour
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const letters = [...shape.text]
  const widths = letters.map((letter) => ctx.measureText(letter).width)
  const total =
    widths.reduce((sum, width) => sum + width, 0) + shape.tracking * (letters.length - 1)
  let x = shape.x - total / 2
  for (let index = 0; index < letters.length; index += 1) {
    ctx.fillText(letters[index], x + widths[index] / 2, shape.y)
    x += widths[index] + shape.tracking
  }
}

/**
 * Paint ``icon`` inside the square of ``size`` whose top-left corner is the
 * current origin.
 *
 * The caller has already moved the context to the illustration's box (and may
 * have turned it for the side of the ring), so this painter only scales the
 * 0..100 data to the box and clips to it: a coordinate outside the box is a bug
 * that must stay inside the illustration instead of landing on the name.
 */
export function paintIcon(
  ctx: CanvasRenderingContext2D,
  icon: CellIcon,
  size: number,
  palette: IconPalette,
): void {
  const scale = size / ICON_BOX
  ctx.save()
  ctx.scale(scale, scale)
  ctx.beginPath()
  ctx.rect(0, 0, ICON_BOX, ICON_BOX)
  ctx.clip()

  for (const shape of ICON_SHAPES[icon]) {
    const colour = inkOf(icon, shape.ink, palette)
    if (shape.kind === 'rect') {
      ctx.fillStyle = colour
      ctx.fillRect(shape.x, shape.y, shape.width, shape.height)
    } else if (shape.kind === 'circle') {
      ctx.fillStyle = colour
      ctx.beginPath()
      ctx.arc(shape.x, shape.y, shape.radius, 0, Math.PI * 2)
      ctx.fill()
    } else if (shape.kind === 'polygon') {
      const [first, second, ...rest] = shape.points
      ctx.fillStyle = colour
      ctx.beginPath()
      ctx.moveTo(first, second)
      for (let index = 0; index < rest.length; index += 2) {
        ctx.lineTo(rest[index], rest[index + 1])
      }
      ctx.closePath()
      ctx.fill()
    } else if (shape.kind === 'line') {
      const [first, second, ...rest] = shape.points
      ctx.strokeStyle = colour
      ctx.lineWidth = shape.width
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.beginPath()
      ctx.moveTo(first, second)
      for (let index = 0; index < rest.length; index += 2) {
        ctx.lineTo(rest[index], rest[index + 1])
      }
      ctx.stroke()
    } else if (shape.kind === 'arc') {
      ctx.strokeStyle = colour
      ctx.lineWidth = shape.width
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.arc(shape.x, shape.y, shape.radius, shape.from, shape.to)
      ctx.stroke()
    } else {
      paintText(ctx, shape, colour)
    }
  }

  ctx.restore()
}
