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
 * 2. a **painter** (``paintSpace``) that reads the
 *    specification and a palette and nothing else;
 * 3. one thin convenience (``spaceTexture``) that makes the
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
 * Ink and paper of one cell, mirroring ``--monopoly-ink``, ``--monopoly-ink-soft``,
 * ``--monopoly-paper`` and ``--monopoly-board-line`` of ``monopoly.css``.
 */
const SPACE_INK = '#241f2e'
const SPACE_INK_SOFT = '#56516a'
const SPACE_PAPER = '#e9efe6'
const SPACE_LINE = '#2b2733'

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
 * How far to turn a cell's text so it reads the way the printed board reads
 * (S5).
 *
 * The rule is one sentence: **the top of the letters points at the middle of the
 * board**, which is also the edge the colour band sits on. A player sits outside
 * their side, so text that points inward is text whose feet are towards them, and
 * that is why the bottom row needs no turn at all, the far row needs half a turn,
 * and the two columns need a quarter each in opposite directions.
 *
 * It is exported and tested because it is the only part of this painter a test
 * can reach: the harness has no canvas, but it can rotate a vector.
 */
export function textRotationFor(side: BoardSide): number {
  if (side === 'top') return Math.PI
  if (side === 'left') return Math.PI / 2
  if (side === 'right') return -Math.PI / 2
  return 0
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
  ctx.rotate(textRotationFor(spec.side))
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

