/**
 * The face of a flat token, painted at runtime (S3 of
 * ``monopoly-flat-figures.md``).
 *
 * The pieces are no longer built from primitives: each is a **printed chip** -- a
 * rounded square of paper with an ink rim and the figure's black silhouette on
 * it -- and that face is a canvas, exactly like the forty cells and the dice. No
 * binary asset, no downloaded image, nothing to keep in sync with the catalogue:
 * the silhouette comes from ``figureInk.ts`` and the paper and ink are the two
 * constants below, the same pair the outline plan used.
 *
 * Two layers share the face. The **chip** is opaque, which is what makes it read
 * on a yellow, a light-blue or a dark-blue cell: the black silhouette never sits
 * on the cell's own colour. The **contact shadow** is separate and nearly
 * transparent; ``Figure3D`` lays it flat under the chip and sizes it, because a
 * billboard cannot cast a believable shadow into the scene's shadow map.
 *
 * Like ``textures.ts``, the half that touches ``document`` is untested on
 * purpose: this harness is Node with no canvas. The path data it paints is
 * pinned by ``figureInk.test.ts``, and the result is checked by the headless
 * capture and by the person looking at the board (S7).
 */

import { CanvasTexture } from 'three'
import { toTexture } from './canvasTexture'
import type { PieceFigure } from './figures'
import { FIGURE_INK, INK_BOX } from './figureInk'

/**
 * The side of the token's face, in pixels.
 *
 * The face is a couple of dozen pixels tall at the far edge of a board and about
 * forty at the near corner, so 256 is already more texels than a screen asks for;
 * the extra exists so the silhouette's curves stay clean at 2x dpr instead of
 * turning into a staircase.
 */
export const TOKEN_TEXTURE_SIZE = 256

/** The paper of the chip: the same warm white the pieces' bodies used. */
export const TOKEN_PAPER = '#fbf9f3'

/** The ink: the rim, and the silhouette printed inside it. */
export const TOKEN_INK = '#0d0b10'

/**
 * The margin the seat's bloom needs inside the texture, as a fraction of its
 * side.
 *
 * The glow is painted into the same square canvas as the chip, and a shadow that
 * runs past that edge is cut off -- a clipped halo reads as a square, not as
 * light. So the chip keeps a margin, and ``Figure3D`` enlarges the sprite by the
 * same fraction, which leaves the printed chip exactly the size it always was.
 */
export const TOKEN_HALO = 0.08

/** How far the bloom spreads from the rim, as a fraction of the canvas side. */
const GLOW_BLUR = 0.06

/** Anisotropy the chips share with the cells and the dice. */
const ANISOTROPY = 8

/** The silhouette keeps this fraction of the face as margin on every side. */
const INK_INSET = 0.09

/** Corner radius of the chip, as a fraction of its side. */
const CARD_RADIUS = 0.12

/** The rim's width, as a fraction of the chip's side. */
const RIM_WIDTH = 0.016

/** The side of the contact shadow's texture, in pixels. */
const SHADOW_TEXTURE_SIZE = 128

/** One path inside the rounded square, from the four corners and their radius. */
function roundedSquare(
  ctx: CanvasRenderingContext2D,
  left: number,
  top: number,
  side: number,
  radius: number,
): void {
  const right = left + side
  const bottom = top + side
  ctx.beginPath()
  ctx.moveTo(left + radius, top)
  ctx.lineTo(right - radius, top)
  ctx.quadraticCurveTo(right, top, right, top + radius)
  ctx.lineTo(right, bottom - radius)
  ctx.quadraticCurveTo(right, bottom, right - radius, bottom)
  ctx.lineTo(left + radius, bottom)
  ctx.quadraticCurveTo(left, bottom, left, bottom - radius)
  ctx.lineTo(left, top + radius)
  ctx.quadraticCurveTo(left, top, left + radius, top)
  ctx.closePath()
}

/** Every loop of a figure as one path, so a single even-odd fill draws the holes. */
function inkPath(figure: PieceFigure): Path2D {
  const path = new Path2D()
  for (const loop of FIGURE_INK[figure]) {
    path.moveTo(loop[0], loop[1])
    for (let index = 2; index < loop.length; index += 2) {
      path.lineTo(loop[index], loop[index + 1])
    }
    path.closePath()
  }
  return path
}

/**
 * The inks of one chip: the printed paper, the rim and the bloom around it.
 *
 * Without a seat tone the chip is exactly the printed piece the project always
 * shipped: black rim, no glow. With one, the rim takes the seat's tone and the
 * bloom a lighter mix of the same tone, because a dark rim alone reads as ink on
 * white paper and what the eye reads as neon is the bright halo around it.
 */
export type TokenInks = {
  paper: string
  rim: string
  glow: string
  /**
   * How thick the rim is drawn, as a fraction of the canvas side.
   *
   * The printed rim is a hairline (``RIM_WIDTH``) and stays that way for a chip
   * with no tone. A toned chip needs a wider band for a different reason: at the
   * far edge of the table the chip is a couple of dozen pixels across, and a
   * hairline in a dark tone is indistinguishable from the black ink it replaced,
   * which is exactly the "I cannot see the colour" this increment fixes.
   */
  rimWidth: number
}

/**
 * Mix a ``#rrggbb`` colour toward white by ``amount`` (0 keeps it, 1 whitens it).
 *
 * Written out instead of using ``color-mix`` because the chip is a canvas: CSS
 * colour functions do not exist here, and a canvas cannot read a custom property
 * without a mounted element. A spelling this function cannot read is returned
 * unchanged rather than turned into a colour it did not inspect.
 */
export function mixWithWhite(hex: string, amount: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex
  const value = Number.parseInt(hex.slice(1), 16)
  const channels = [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff]
  const mixed = channels.map((channel) => Math.round(channel + (255 - channel) * amount))
  return `#${mixed.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`
}

/** How much wider the rim of a toned chip is, as a fraction of the canvas side. */
const TONED_RIM_WIDTH = 0.04

/** The inks of a chip for a seat tone, or the printed inks when there is none. */
export function tokenInks(tone: string | null): TokenInks {
  if (tone === null) {
    return { paper: TOKEN_PAPER, rim: TOKEN_INK, glow: 'transparent', rimWidth: RIM_WIDTH }
  }
  return { paper: TOKEN_PAPER, rim: tone, glow: mixWithWhite(tone, 0.55), rimWidth: TONED_RIM_WIDTH }
}

/**
 * Paint one token's face: paper, rim, bloom and silhouette.
 *
 * Split from the texture so the drawing is one readable block, and because the
 * canvas is what a visual review looks at when the scene is too slow to trust.
 * The canvas is cleared first: it may be reused, and a stale silhouette under a
 * new one would be a bug that survives every unit test.
 */
export function paintToken(
  ctx: CanvasRenderingContext2D,
  figure: PieceFigure,
  size: number,
  inks: TokenInks = tokenInks(null),
): void {
  ctx.clearRect(0, 0, size, size)
  const margin = size * TOKEN_HALO
  const face = size - 2 * margin
  const rim = Math.max(2, size * inks.rimWidth)
  roundedSquare(ctx, margin + rim / 2, margin + rim / 2, face - rim, face * CARD_RADIUS)
  ctx.fillStyle = inks.paper
  ctx.fill()

  // The bloom comes first, as one stroke of the glow ink carrying a shadow of
  // its own colour: the shadow spreads into the margin and the stroke keeps the
  // halo from looking like a blurry blob with no edge. A tone-less chip strokes
  // with ``transparent``, so this is the printed piece with no glow at all.
  ctx.save()
  ctx.lineWidth = rim
  ctx.strokeStyle = inks.glow
  ctx.shadowColor = inks.glow
  ctx.shadowBlur = size * GLOW_BLUR
  ctx.stroke()
  ctx.restore()

  // The rim itself, crisp, on top of its own glow.
  ctx.lineWidth = rim
  ctx.strokeStyle = inks.rim
  ctx.stroke()

  const inset = margin + face * INK_INSET
  const scale = (face - 2 * face * INK_INSET) / INK_BOX
  ctx.save()
  ctx.translate(inset, inset)
  ctx.scale(scale, scale)
  ctx.fillStyle = TOKEN_INK
  // Even-odd and not the default: every loop after the first is a hole, which is
  // how the belly, the windows and the handle's ring stay paper.
  ctx.fill(inkPath(figure), 'evenodd')
  ctx.restore()
}

/**
 * Paint the contact shadow: a soft radial gradient, dark in the middle.
 *
 * A gradient and not a shadow map: the chip is a billboard, and what the eye
 * reads under a floating object is the penumbra it would cast, not the exact
 * silhouette of a plane the light never sees edge-on.
 */
export function paintContactShadow(ctx: CanvasRenderingContext2D, size: number): void {
  ctx.clearRect(0, 0, size, size)
  const centre = size / 2
  const gradient = ctx.createRadialGradient(centre, centre, size * 0.08, centre, centre, centre)
  gradient.addColorStop(0, 'rgba(13, 11, 16, 0.34)')
  gradient.addColorStop(0.55, 'rgba(13, 11, 16, 0.16)')
  gradient.addColorStop(1, 'rgba(13, 11, 16, 0)')
  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(centre, centre, centre, 0, Math.PI * 2)
  ctx.fill()
}

/**
 * The textures of the chips, one per figure and seat tone.
 *
 * Cached and never disposed, like the forty cell faces: at most one texture per
 * marker *per seat tone* exists in a match (bounded by the eight seats the board
 * holds), they are tiny, and remounting the scene (switching to the board tab and
 * back) must not repaint or re-upload them.
 */
const TOKEN_TEXTURES = new Map<string, CanvasTexture>()

/** The painted face of one figure in one seat tone, ready for a sprite. */
export function tokenTexture(figure: PieceFigure, tone: string | null = null): CanvasTexture {
  const key = `${figure}:${tone ?? 'none'}`
  const cached = TOKEN_TEXTURES.get(key)
  if (cached !== undefined) return cached
  const canvas = document.createElement('canvas')
  canvas.width = TOKEN_TEXTURE_SIZE
  canvas.height = TOKEN_TEXTURE_SIZE
  const ctx = canvas.getContext('2d')
  if (ctx === null) throw new Error(`no 2d context for the token of ${figure}`)
  paintToken(ctx, figure, TOKEN_TEXTURE_SIZE, tokenInks(tone))
  const texture = toTexture(canvas, ANISOTROPY)
  TOKEN_TEXTURES.set(key, texture)
  return texture
}

let contactShadow: CanvasTexture | null = null

/** The one contact shadow every chip shares. */
export function contactShadowTexture(): CanvasTexture {  if (contactShadow !== null) return contactShadow
  const canvas = document.createElement('canvas')
  canvas.width = SHADOW_TEXTURE_SIZE
  canvas.height = SHADOW_TEXTURE_SIZE
  const ctx = canvas.getContext('2d')
  if (ctx === null) throw new Error('no 2d context for the token shadow')
  paintContactShadow(ctx, SHADOW_TEXTURE_SIZE)
  contactShadow = toTexture(canvas, ANISOTROPY)
  return contactShadow
}
