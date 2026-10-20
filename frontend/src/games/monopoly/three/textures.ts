/**
 * The two textures of the 3D table, painted at runtime from the project's own
 * data (S3 and S5 of ``monopoly-3d-table.md``).
 *
 * S3 forbids binary assets: no image, no downloaded font, no network at run
 * time. So the wood and the forty cells are **drawn on a canvas** from the same
 * tables the 2D board reads -- ``board.ts`` for the names and the kinds,
 * ``deeds.ts`` for the printed prices and rents, ``display.ts`` for the Spanish
 * labels and the money format -- which is what keeps the scene from ever
 * disagreeing with the board beside it.
 *
 * The module is split in three so the DOM-less harness can still test it:
 *
 * 1. a **pure specification** per texture (``spaceTextureSpec``,
 *    ``tableTextureSpec``) returning plain data, which is what the tests pin;
 * 2. a **painter** per texture (``paintSpace``, ``paintTable``) that reads the
 *    specification and a palette and nothing else;
 * 3. two thin conveniences (``spaceTexture``, ``tableTexture``) that make the
 *    offscreen canvas and call the painter. They are the only lines in this
 *    module that touch ``document``, and they are deliberately untested: this
 *    harness is Node with no canvas. The scene is checked by the headless
 *    capture and by the person looking at the board (S12).
 *
 * The wood is generated from a fixed seed with the deterministic generator
 * below, never ``Math.random``: the visual check compares captures between runs,
 * so two calls must produce exactly the same planks, grain and tones.
 */

import type { BoardSide } from '../grid'
import type { ColorGroup, SpaceKind } from '../board'
import { isPurchasable, spaceAt } from '../board'
import { HOTEL_LEVEL, deedFor, levelLabel, purchasePrice, rentForLevel } from '../deeds'
import { GROUP_INITIALS, GROUP_LABELS, KIND_LABELS, formatMoney } from '../display'
import { spaceSide } from '../grid'

/**
 * The canonical hex of each colour group of the printed board.
 *
 * **A seam the project may want to close.** ``board.ts`` publishes the group
 * *key* (``brown``) but no hex, so the only copy of these eight values lives in
 * ``monopoly.css`` as the custom properties ``--monopoly-brown``,
 * ``--monopoly-light-blue``, ``--monopoly-pink``, ``--monopoly-orange``,
 * ``--monopoly-red``, ``--monopoly-yellow``, ``--monopoly-green`` and
 * ``--monopoly-dark-blue``. A canvas cannot read a custom property without a
 * mounted element and a computed style, and TypeScript cannot import a
 * stylesheet, so the values are copied here, once, and this comment is the only
 * warning: repainting a group in CSS now costs two edits. The clean fix is a
 * shared ``groups.ts`` that both the stylesheet and this module read, which is a
 * change to the board's skin and belongs to its own increment.
 */
export const GROUP_COLOURS: Record<ColorGroup, string> = {
  brown: '#955436',
  light_blue: '#aae0fa',
  pink: '#d93a96',
  orange: '#f7941d',
  red: '#ed1b24',
  yellow: '#fef200',
  green: '#1fb25a',
  dark_blue: '#0072bb',
}

/** The four tonal steps a plank can take, darkest first. */
export const WOOD_TONES: readonly string[] = ['#5d3a22', '#6f482a', '#815533', '#94633d']

/** One line of grain crossing a plank, as fractions of the plank's own box. */
export type TableGrainLine = {
  /** Where the line sits across the plank: 0 is its left edge, 1 its right. */
  offset: number
  /** Where the line starts along the plank, 0 at its near edge. */
  start: number
  /** How far the line runs along the plank, as a fraction of its length. */
  length: number
  /** How dark the line paints over its plank, 0 to 1. */
  weight: number
  /** The line's own thickness, as a fraction of the texture size. */
  thickness: number
}

/** One plank of the table, as fractions of the texture width. */
export type TablePlank = {
  /** The plank's left edge, 0 at the texture's left and 1 at its right. */
  start: number
  /** The plank's width, as a fraction of the texture width. */
  width: number
  /** The index of the plank's tone in ``WOOD_TONES``. */
  tone: number
  /** The grain painted on top of the plank, in paint order. */
  grain: readonly TableGrainLine[]
}

/** What the wooden table looks like, as data the painter can follow. */
export type TableTextureSpec = {
  /** The seed the table was generated from, so a capture can be reproduced. */
  seed: number
  /** The planks, left to right; together they tile the whole texture. */
  planks: readonly TablePlank[]
}

/** The seed the table is built from when the caller does not choose one. */
export const TABLE_SEED = 1861

/** How many planks the table is built from. Seven reads as a table, not a floor. */
const PLANK_COUNT = 7

/** How much a plank's width may stray from the even share of the texture. */
const PLANK_WIDTH_JITTER = 0.5

/** The fewest and the most grain lines a plank receives. */
const MIN_GRAIN_LINES = 5
const MAX_GRAIN_LINES = 9

/**
 * A small deterministic pseudo-random generator (a linear congruential one).
 *
 * It is written here instead of borrowed so the table has no dependency and no
 * ``Math.random``: the same seed yields the same sequence in every browser,
 * every Node version and every run, which is what lets two captures be compared.
 */
function seededRandom(seed: number): () => number {
  let state = Math.trunc(seed) >>> 0
  if (state === 0) state = 1
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 4294967296
  }
}

/** Four decimals, so a specification stays readable and comparable. */
function round4(value: number): number {
  return Math.round(value * 10000) / 10000
}

/**
 * The wooden table of the 3D scene (S5), as pure data.
 *
 * Planks are built from jittered widths that are then normalised, so they always
 * tile the texture exactly; each gets a tonal step and a handful of grain lines
 * that stay inside its own box. Two calls with the same seed return the same
 * object, and a different seed returns a different table.
 */
export function tableTextureSpec(seed: number = TABLE_SEED): TableTextureSpec {
  const random = seededRandom(seed)
  const weights = Array.from(
    { length: PLANK_COUNT },
    () => 1 + (random() - 0.5) * PLANK_WIDTH_JITTER,
  )
  const total = weights.reduce((sum, weight) => sum + weight, 0)
  let start = 0
  const planks = weights.map((weight) => {
    const width = weight / total
    const tone = Math.min(WOOD_TONES.length - 1, Math.floor(random() * WOOD_TONES.length))
    const grainCount =
      MIN_GRAIN_LINES + Math.floor(random() * (MAX_GRAIN_LINES - MIN_GRAIN_LINES + 1))
    const grain = Array.from({ length: grainCount }, () => {
      const length = round4(0.25 + random() * 0.75)
      return {
        offset: round4(0.08 + random() * 0.84),
        // Clamped after rounding, so a line can never overrun its plank.
        start: Math.min(round4(random() * (1 - length)), round4(1 - length)),
        length,
        weight: round4(0.12 + random() * 0.5),
        thickness: round4(0.0015 + random() * 0.0025),
      }
    })
    const plank: TablePlank = { start, width, tone, grain }
    start += width
    return plank
  })
  return { seed, planks }
}

/** One line of a street's printed rent schedule. */
export type SpaceRentLine = {
  /** The Spanish name of the level, from ``deeds.ts`` (``1 casa`` … ``Hotel``). */
  label: string
  /** The printed rent, formatted the way the 2D board formats money. */
  amount: string
}

/**
 * The printed rents of a street: the unimproved rent, the rent with the whole
 * colour group held, and one line per built level.
 *
 * The two unimproved lines carry no level label, which is why they are named
 * fields instead of extra lines: ``deeds.ts`` names levels 1 to 5 and nothing
 * else, and a label invented here would be a second spelling of something the
 * board already prints.
 */
export type StreetRents = {
  base: string
  group: string
  built: readonly SpaceRentLine[]
}

/** The colour band of a space that has a group, with its non-colour cues. */
export type SpaceBand = {
  group: ColorGroup
  /** The printed hex of the group, from ``GROUP_COLOURS``. */
  colour: string
  /** The two-letter Spanish initials the 2D board also prints. */
  initials: string
  /** The Spanish group name, for the detail layer (S8). */
  label: string
}

/**
 * Everything one cell must show, as plain data.
 *
 * Every string here is read from ``board.ts``, ``deeds.ts`` or ``display.ts``;
 * nothing is retyped and nothing is computed from the server view, because a
 * cell in this texture shows printed data and never state.
 */
export type SpaceTextureSpec = {
  index: number
  /** The printed name, exactly as ``board.ts`` spells it. */
  name: string
  kind: SpaceKind
  /** The Spanish name of the kind, from ``KIND_LABELS`` (detail layer, S8). */
  kindLabel: string
  /** Which edge of the ring the space sits on, so the band faces the centre. */
  side: BoardSide
  /** The colour band, or ``null`` for a space the printed board leaves plain. */
  band: SpaceBand | null
  /** The printed price, or ``null`` for a space the bank cannot sell. */
  price: string | null
  /** The printed rents of a street, or ``null`` for every other space. */
  rents: StreetRents | null
}

/** The printed rent schedule of a street, straight from its deed. */
function streetRents(index: number): StreetRents {
  const deed = deedFor(index)
  return {
    base: formatMoney(rentForLevel(deed, 0)),
    group: formatMoney(deed.setRent),
    built: [1, 2, 3, 4, HOTEL_LEVEL].map((level) => ({
      label: levelLabel(level),
      amount: formatMoney(rentForLevel(deed, level)),
    })),
  }
}

/**
 * The specification of the cell texture for the space at ``index``.
 *
 * Throws for an index outside the circuit, delegating to ``spaceAt`` so the
 * texture and the board cannot disagree about what a valid space is.
 */
export function spaceTextureSpec(index: number): SpaceTextureSpec {
  const space = spaceAt(index)
  return {
    index: space.index,
    name: space.name,
    kind: space.kind,
    kindLabel: KIND_LABELS[space.kind],
    side: spaceSide(space.index),
    band:
      space.group === null
        ? null
        : {
            group: space.group,
            colour: GROUP_COLOURS[space.group],
            initials: GROUP_INITIALS[space.group],
            label: GROUP_LABELS[space.group],
          },
    price: isPurchasable(space) ? formatMoney(purchasePrice(space.index)) : null,
    rents: space.kind === 'street' ? streetRents(space.index) : null,
  }
}

/**
 * The side of one cell texture, in pixels.
 *
 * 256 is the smallest size at which a name stays a name: at the 30 px face the
 * painter picks for the longest name on the board it fits about ten characters
 * per line, so "Avenida North Carolina" wraps in two and still reads when the
 * near corner fills a third of the screen. Halving it costs nothing in memory
 * and turns the letters into texture; doubling it adds a megabyte per cell for
 * texels nobody can resolve at a twenty-degree camera.
 */
export const CELL_TEXTURE_SIZE = 256

/**
 * The side of the table texture, in pixels.
 *
 * Seven planks across 1024 px are about 146 px each, so a two-pixel grain line
 * and the seam between planks survive mipmapping. The table is a plain surface
 * that sits out of focus behind the board, and 2048 would quadruple its GPU
 * memory for a detail the camera never reaches (S11).
 */
export const TABLE_TEXTURE_SIZE = 1024

/**
 * Ink and paper of one cell, mirroring ``--monopoly-ink``, ``--monopoly-ink-soft``,
 * ``--monopoly-paper`` and ``--monopoly-board-line`` of ``monopoly.css``.
 */
const SPACE_INK = '#241f2e'
const SPACE_INK_SOFT = '#56516a'
const SPACE_PAPER = '#fdfbf4'
const SPACE_LINE = '#2b2733'

/** The dark the table is under the planks, which is what makes the seams read. */
const WOOD_SEAM = '#3a2314'

/** The grain is paint, not geometry: a dark line over the plank's own tone. */
const WOOD_GRAIN = '#2b1a0e'

/** No downloaded font (S3): the stack is whatever the system already has. */
const FONT_STACK = 'system-ui, sans-serif'

type Rect = { x: number; y: number; width: number; height: number }

/**
 * Where the colour band goes: always the edge that faces the board's centre,
 * which is a different physical edge on every side of the ring.
 */
function bandRect(side: BoardSide, size: number, thickness: number): Rect {
  if (side === 'bottom') return { x: 0, y: 0, width: size, height: thickness }
  if (side === 'top') return { x: 0, y: size - thickness, width: size, height: thickness }
  if (side === 'left') return { x: size - thickness, y: 0, width: thickness, height: size }
  return { x: 0, y: 0, width: thickness, height: size }
}

/** The box the text may use, once the band and the padding are taken out. */
function contentRect(side: BoardSide, size: number, pad: number, band: number): Rect {
  const width = size - 2 * pad
  const height = size - 2 * pad
  if (side === 'bottom') return { x: pad, y: band + pad, width, height: height - band }
  if (side === 'top') return { x: pad, y: pad, width, height: height - band }
  if (side === 'left') return { x: pad, y: pad, width: width - band, height }
  return { x: band + pad, y: pad, width: width - band, height }
}

/** Cut a line to fit ``maxWidth``, marking the cut, instead of overrunning. */
function ellipsize(ctx: CanvasRenderingContext2D, line: string, maxWidth: number): string {
  let text = line
  while (text.length > 1 && ctx.measureText(`${text}…`).width > maxWidth) {
    text = text.slice(0, -1)
  }
  return `${text}…`
}

/** Break a name into at most ``maxLines`` lines that fit ``maxWidth``. */
function wrapLines(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  maxLines: number,
): string[] {
  const words = text.split(' ')
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const candidate = current === '' ? word : `${current} ${word}`
    if (current !== '' && ctx.measureText(candidate).width > maxWidth) {
      lines.push(current)
      current = word
    } else {
      current = candidate
    }
  }
  if (current !== '') lines.push(current)
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    kept[maxLines - 1] = ellipsize(ctx, kept[maxLines - 1], maxWidth)
    return kept
  }
  return lines
}

/**
 * Paint a name into a box, shrinking it until it fits.
 *
 * A cell is small and the names are Spanish and long ("Avenida North
 * Carolina"), so the size is derived from the box instead of assumed: the first
 * size from ``preferred`` downwards whose wrapped lines fit the height wins.
 */
function paintWrapped(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  maxHeight: number,
  top: number,
  preferred: number,
  colour: string,
): void {
  const minimum = Math.max(8, Math.round(preferred * 0.55))
  let size = minimum
  let lineHeight = minimum * 1.14
  let lines: string[] = []
  for (let candidate = Math.round(preferred); candidate >= minimum; candidate -= 1) {
    ctx.font = `800 ${candidate}px ${FONT_STACK}`
    const height = candidate * 1.14
    const maxLines = Math.max(1, Math.floor(maxHeight / height))
    const wrapped = wrapLines(ctx, text, maxWidth, maxLines)
    if (wrapped.length * height <= maxHeight) {
      size = candidate
      lineHeight = height
      lines = wrapped
      break
    }
  }
  if (lines.length === 0) {
    ctx.font = `800 ${size}px ${FONT_STACK}`
    lines = wrapLines(ctx, text, maxWidth, Math.max(1, Math.floor(maxHeight / lineHeight)))
  }
  ctx.fillStyle = colour
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const blockHeight = lines.length * lineHeight
  let y = top + (maxHeight - blockHeight) / 2 + lineHeight / 2
  for (const line of lines) {
    ctx.fillText(line, 0, y, maxWidth)
    y += lineHeight
  }
}

/**
 * Draw the face of one cell inside the already-centred, already-rotated box.
 *
 * It paints what a printed cell prints -- the band, the name, the group
 * initials and the price -- and the kind as a caption only where the name is
 * the whole story (GO, the decks, the taxes, the corners). The rents travel in
 * the specification but are not painted here: a printed cell does not carry
 * seven rent lines either, and a 256 px cell cannot. They are read in the
 * centre detail (S8) and in the panel.
 */
function paintCellFace(
  ctx: CanvasRenderingContext2D,
  spec: SpaceTextureSpec,
  box: { width: number; height: number },
  size: number,
): void {
  const caption = spec.band === null && spec.price === null ? spec.kindLabel : null
  const captionHeight = caption === null ? 0 : Math.round(size * 0.1)
  const priceHeight = spec.price === null ? 0 : Math.round(size * 0.14)
  const initialsHeight = spec.band === null ? 0 : Math.round(size * 0.12)
  const nameHeight = Math.max(1, box.height - captionHeight - priceHeight - initialsHeight)
  const top = -box.height / 2

  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'

  if (caption !== null) {
    const px = Math.round(size * 0.055)
    ctx.font = `600 ${px}px ${FONT_STACK}`
    ctx.fillStyle = SPACE_INK_SOFT
    ctx.fillText(caption, 0, top + captionHeight / 2, box.width)
  }

  paintWrapped(
    ctx,
    spec.name,
    box.width,
    nameHeight,
    top + captionHeight,
    size * 0.13,
    SPACE_INK,
  )

  if (spec.band !== null) {
    const px = Math.round(size * 0.06)
    ctx.font = `800 ${px}px ${FONT_STACK}`
    ctx.fillStyle = SPACE_INK_SOFT
    ctx.fillText(
      spec.band.initials,
      0,
      top + captionHeight + nameHeight + initialsHeight / 2,
      box.width,
    )
  }

  if (spec.price !== null) {
    const px = Math.round(size * 0.1)
    ctx.font = `800 ${px}px ${FONT_STACK}`
    ctx.fillStyle = SPACE_INK
    ctx.fillText(
      spec.price,
      0,
      top + captionHeight + nameHeight + initialsHeight + priceHeight / 2,
      box.width,
    )
  }
}

/**
 * Paint one cell of the board (S5).
 *
 * The specification is everything it reads: the painter never asks ``board.ts``
 * again, so a cell cannot be painted from one table and named from another.
 * The only extra input is the palette above, which mirrors the stylesheet.
 */
export function paintSpace(
  ctx: CanvasRenderingContext2D,
  spec: SpaceTextureSpec,
  size: number,
): void {
  ctx.save()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, size, size)
  ctx.fillStyle = SPACE_PAPER
  ctx.fillRect(0, 0, size, size)

  const band = spec.band === null ? 0 : Math.round(size * 0.18)
  if (spec.band !== null) {
    const rect = bandRect(spec.side, size, band)
    ctx.fillStyle = spec.band.colour
    ctx.fillRect(rect.x, rect.y, rect.width, rect.height)
  }

  const pad = Math.round(size * 0.06)
  const content = contentRect(spec.side, size, pad, band)
  const quarterTurn = spec.side === 'left' || spec.side === 'right'

  ctx.translate(content.x + content.width / 2, content.y + content.height / 2)
  if (spec.side === 'right') ctx.rotate(Math.PI / 2)
  if (spec.side === 'left') ctx.rotate(-Math.PI / 2)
  const box = quarterTurn
    ? { width: content.height, height: content.width }
    : { width: content.width, height: content.height }
  paintCellFace(ctx, spec, box, size)
  ctx.restore()

  // The cell's edge, painted last so it stays a crisp rule over the band.
  const border = Math.max(1, Math.round(size * 0.008))
  ctx.save()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.strokeStyle = SPACE_LINE
  ctx.lineWidth = border
  ctx.strokeRect(border / 2, border / 2, size - border, size - border)
  ctx.restore()
}

/**
 * Paint the wooden table (S5).
 *
 * Only the specification and the wood palette: the seams are the dark base
 * showing between planks, the grain is a translucent line over the plank's own
 * tone, and the tones step through ``WOOD_TONES`` by index, so the table is as
 * reproducible as the data that generated it.
 */
export function paintTable(
  ctx: CanvasRenderingContext2D,
  spec: TableTextureSpec,
  size: number,
): void {
  ctx.save()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, size, size)
  ctx.fillStyle = WOOD_SEAM
  ctx.fillRect(0, 0, size, size)

  for (const plank of spec.planks) {
    const left = plank.start * size
    const width = plank.width * size
    ctx.fillStyle = WOOD_TONES[plank.tone]
    ctx.fillRect(left, 0, width, size)

    ctx.fillStyle = WOOD_GRAIN
    for (const line of plank.grain) {
      ctx.globalAlpha = line.weight
      ctx.fillRect(
        left + line.offset * width,
        line.start * size,
        Math.max(1, Math.round(line.thickness * size)),
        line.length * size,
      )
    }
    ctx.globalAlpha = 1
  }
  ctx.restore()
}

/**
 * The finished cell texture of the space at ``index``.
 *
 * One of the two functions in this module that touch ``document``; untested on
 * purpose, because the harness has no DOM. The scene wraps the returned canvas
 * in a ``THREE.CanvasTexture``.
 */
export function spaceTexture(index: number, size: number = CELL_TEXTURE_SIZE): HTMLCanvasElement {
  const spec = spaceTextureSpec(index)
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (ctx === null) throw new Error(`no 2d context for the texture of space ${index}`)
  paintSpace(ctx, spec, size)
  return canvas
}

/**
 * The finished table texture, for the plane the board rests on.
 *
 * The second and last function that touches ``document``; the seed is the
 * module's fixed one, so the table of a capture can be compared with the table
 * of the next run.
 */
export function tableTexture(size: number = TABLE_TEXTURE_SIZE): HTMLCanvasElement {
  const spec = tableTextureSpec()
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (ctx === null) throw new Error('no 2d context for the table texture')
  paintTable(ctx, spec, size)
  return canvas
}
