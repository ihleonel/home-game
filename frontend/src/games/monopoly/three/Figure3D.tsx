/**
 * One piece, as a flat token floating over its cell (S3 and S4 of
 * ``monopoly-flat-figures.md``).
 *
 * The pieces used to be assemblies of primitives -- a cylinder for the hat's
 * crown, cones for the cat's ears -- and at a seat's distance those read as lumps.
 * The scene now prints the classic figures the way the sheet the owner of the look
 * sent prints them: **a chip of paper with the black silhouette on it, always
 * facing the screen**, suspended a little over the cell, breathing slowly, with a
 * soft contact shadow underneath.
 *
 * **Why a billboard and not a disc lying on the board.** The reference is a
 * printed figure seen from the front, and the table can rest at any angle: a
 * painted disc on the cell would turn with the board and show the figures on
 * their side. A sprite always faces the camera, so a figure reads the same from
 * every seat and at every angle -- and the colour of the chip, not the angle, is
 * what tells two pieces on one cell apart.
 *
 * **The chip carries the seat's tone.** Its rim is painted in the tone the 2D
 * board, the owner badge and the players list already use, and a lighter bloom of
 * the same tone glows around it -- the effect the printed chip needs to stay
 * legible on a shared cell, where two seats with the same marker would otherwise
 * be the same picture. ``paintToken`` owns that drawing and ``tokens.ts`` owns
 * which tone each seat gets; this file only places the chip in the scene.
 *
 * **What the bob costs.** Rendering is on demand (S11 of
 * ``monopoly-3d-table.md``), so a continuous animation has to ask for the next
 * frame: with the board tab open the scene renders continuously, and with it
 * closed it does not render at all. That trade is the user's explicit choice
 * (S6 of this increment, Log L2), and ``prefers-reduced-motion`` turns the bob
 * off and leaves the chip still.
 *
 * The shape itself is not decided here: ``figureInk.ts`` owns the silhouette,
 * ``figureTexture.ts`` paints it, and ``figures.ts`` decides which figure a marker
 * gets. This file only places the chip in the scene.
 */

import { useFrame, useThree } from '@react-three/fiber'
import { useRef } from 'react'
import type { Mesh, Sprite } from 'three'
import type { PieceFigure } from './figures'
import { TOKEN_HALO, contactShadowTexture, tokenTexture } from './figureTexture'
import { usePrefersReducedMotion } from './useReducedMotion'

/** The side of the chip, in cells: half a space, so two chips on one cell clear each other. */
const TOKEN_SIZE = 0.5

/**
 * The side of the sprite, in cells.
 *
 * Larger than the chip by the margin the bloom needs: the halo is painted inside
 * the texture, so the sprite carries that margin as transparent pixels and the
 * printed chip stays exactly ``TOKEN_SIZE`` across.
 */
const TOKEN_PLANE = TOKEN_SIZE / (1 - 2 * TOKEN_HALO)

/**
 * How high the middle of the chip floats over the printed surface, in cells.
 *
 * The sprite is centred on this height, so the chip's bottom edge sits about
 * ``TOKEN_HEIGHT - TOKEN_SIZE / 2`` above the cell. That gap is the float, and it
 * is also what keeps the billboard from slicing into the board when it bobs.
 */
const TOKEN_HEIGHT = 0.36

/** How far the chip rises and falls around its height, in cells. */
const TOKEN_BOB = 0.03

/** How fast the chip breathes, in radians per second: one cycle every ~4.8 s. */
const BOB_SPEED = 1.3

/** The side of the contact shadow, in cells, at the bottom of the bob. */
const SHADOW_SIZE = 0.34

/** How far the shadow lies above the printed surface, in cells. */
const SHADOW_LIFT = 0.004

/** How much of its size the shadow loses at the top of the bob. */
const SHADOW_SHRINK = 0.18

/**
 * Where a figure starts its bob, in radians.
 *
 * Derived from the figure's own id so it is stable across re-renders and remounts
 * without a random number or a new prop. Two seats that picked the same marker
 * breathe together, which reads as one cell moving -- the pieces on a shared cell
 * are offset anyway, so the eye does not ask for them to disagree.
 */
function tokenPhase(figure: PieceFigure): number {
  let hash = 0
  for (let index = 0; index < figure.length; index += 1) {
    hash = (hash * 31 + figure.charCodeAt(index)) % 997
  }
  return (hash / 997) * Math.PI * 2
}

/**
 * The chip, its bob and its shadow.
 *
 * Drawn inside the group ``Tokens`` positions and walks, so the chip inherits the
 * walk's lift and the spread of a shared cell and only owns the float above them.
 */
export function Figure3D({ figure, tone }: { figure: PieceFigure; tone: string | null }) {
  const chip = useRef<Sprite>(null)
  const shadow = useRef<Mesh>(null)
  const reduced = usePrefersReducedMotion()
  const invalidate = useThree((state) => state.invalidate)
  const face = tokenTexture(figure, tone)
  const halo = contactShadowTexture()
  const phase = tokenPhase(figure)

  useFrame(() => {
    const node = chip.current
    if (node === null) return
    if (reduced) {
      node.position.y = TOKEN_HEIGHT
      shadow.current?.scale.setScalar(SHADOW_SIZE)
      return
    }
    // ``performance.now`` and not the renderer's clock: r3f resets that clock when
    // the frame loop changes, and every chip would jump to the same phase the
    // moment the board tab is opened again.
    const wave = Math.sin((performance.now() / 1000) * BOB_SPEED + phase)
    node.position.y = TOKEN_HEIGHT + wave * TOKEN_BOB
    // The shadow tightens as the chip rises, which is the whole cue that it floats
    // rather than stands on the cell.
    shadow.current?.scale.setScalar(SHADOW_SIZE * (1 - wave * SHADOW_SHRINK))
    // On demand, a continuous animation has to ask for the next frame itself.
    invalidate()
  })

  return (
    <group>
      <mesh
        ref={shadow}
        position={[0, SHADOW_LIFT, 0]}
        rotation={[-Math.PI / 2, 0, 0]}
        scale={SHADOW_SIZE}
      >
        <planeGeometry args={[1, 1]} />
        <meshBasicMaterial map={halo} transparent depthWrite={false} toneMapped={false} />
      </mesh>
      <sprite
        ref={chip}
        position={[0, TOKEN_HEIGHT, 0]}
        scale={[TOKEN_PLANE, TOKEN_PLANE, 1]}
      >
        <spriteMaterial map={face} transparent depthWrite={false} toneMapped={false} />
      </sprite>
    </group>
  )
}
