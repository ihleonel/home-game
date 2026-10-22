/**
 * The two dice on the table (X9 of ``monopoly-3d-table.md``).
 *
 * A throw arrives as a fact -- ``last_roll`` -- and this component is the one
 * that shows it: two cubes fall onto the board, tumble, and come to rest with the
 * numbers the server rolled on top. When the turn moves on they leave, so the
 * next player's throw starts clean.
 *
 * Everything decidable lives in ``dice.ts``: which face carries which number,
 * where the die comes to rest and when a throw is a new throw. What is here is
 * the scene's part -- meshes, materials, and the frame loop that asks for its own
 * frames on a canvas that renders on demand.
 */

import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import { BoxGeometry, Euler, MeshStandardMaterial, Quaternion, Vector3 } from 'three'
import type { Group } from 'three'
import { toTexture } from './canvasTexture'
import {
  DICE_TOTAL_MS,
  DIE_FACES,
  DIE_SIZE,
  diceFall,
  diceState,
  orientationFor,
} from './dice'
import type { DiceView } from './dice'
import { dieTexture } from './textures'
import { usePrefersReducedMotion } from './useReducedMotion'

/**
 * How far a die turns on its way down, in radians, at the start of the fall.
 *
 * Decorative and fixed: the tumble has to end exactly on the rolled face, so it
 * is a rotation that is undone by the time the die lands, not a random spin that
 * would have to be reconciled with the number.
 */
const TUMBLE = 5.2

/** Where each die comes to rest, in the printed middle's own square. */
const DIE_SPOTS: readonly { x: number; z: number }[] = [
  { x: -0.34, z: 1.55 },
  { x: 0.34, z: 1.55 },
]

/** The axis each die tumbles about, so the two do not fall in lockstep. */
const TUMBLE_AXES: readonly { x: number; y: number; z: number }[] = [
  { x: 0.42, y: 0.72, z: 0.55 },
  { x: -0.6, y: 0.5, z: 0.62 },
]

/** The euler the scene sets for a die showing ``value`` on top. */
function eulerFor(value: number): [number, number, number] {
  const orientation = orientationFor(value)
  return [orientation.x, orientation.y, orientation.z]
}

/**
 * Two dice, falling onto the board and staying until the turn ends.
 *
 * Renders nothing while the table has no throw to show, so the middle of the
 * board is the printed board between throws.
 */
export function Dice3D({ turn, roll }: { turn: string | null; roll: readonly number[] | null }) {
  const reduced = usePrefersReducedMotion()
  const [mode, setMode] = useState<'hidden' | 'landed' | 'falling'>('hidden')
  const previous = useRef<DiceView | null>(null)
  const startedAt = useRef(0)
  const invalidate = useThree((state) => state.invalidate)
  const first = useRef<Group>(null)
  const second = useRef<Group>(null)

  // Six materials, one per face, and one cube, shared by both dice: a die is six
  // values and the same six on every die, so painting them once is the whole
  // cost. The geometry is created here rather than declared in the tree because
  // the renderer only disposes what it owns as an object, and a cube per throw
  // would leak a small buffer every time the dice left the table.
  const materials = useMemo(
    () =>
      DIE_FACES.map(
        (value) => new MeshStandardMaterial({ map: toTexture(dieTexture(value), 4), roughness: 0.55 }),
      ),
    [],
  )
  const geometry = useMemo(() => new BoxGeometry(DIE_SIZE, DIE_SIZE, DIE_SIZE), [])
  useEffect(
    () => () => {
      for (const material of materials) {
        material.map?.dispose()
        material.dispose()
      }
      geometry.dispose()
    },
    [geometry, materials],
  )

  // Preallocated: the frame loop must not build garbage sixty times a throw.
  const scratch = useMemo(
    () => ({
      final: new Quaternion(),
      tumble: new Quaternion(),
      euler: new Euler(),
      axis: new Vector3(),
    }),
    [],
  )

  useEffect(() => {
    const next: DiceView = { turn, roll }
    const action = diceState(previous.current, next)
    previous.current = next
    if (action === 'animate' && !reduced) {
      startedAt.current = performance.now()
      setMode('falling')
      invalidate()
      return
    }
    if (action === 'animate' || action === 'landed') {
      setMode('landed')
      return
    }
    if (action === 'hidden') setMode('hidden')
    // Turning the preference on mid-throw stops the tumble where it is and puts
    // the dice down: the request is to see less motion, not to finish this one.
    if (action === 'keep' && reduced && mode === 'falling') setMode('landed')
  }, [turn, roll, reduced, invalidate, mode])

  /** Put one die where the throw has it, mid-fall. */
  const place = (
    node: Group | null,
    value: number | undefined,
    index: number,
    pose: ReturnType<typeof diceFall>,
  ): void => {
    if (node === null || value === undefined) return
    const orientation = orientationFor(value)
    scratch.euler.set(orientation.x, orientation.y, orientation.z)
    scratch.final.setFromEuler(scratch.euler)
    const axis = TUMBLE_AXES[index]
    scratch.axis.set(axis.x, axis.y, axis.z).normalize()
    scratch.tumble.setFromAxisAngle(scratch.axis, (1 - pose.spin) * TUMBLE)
    node.quaternion.copy(scratch.tumble).multiply(scratch.final)
    node.position.y = DIE_SIZE / 2 + pose.lift
  }

  useFrame(() => {
    if (mode !== 'falling' || roll === null) return
    // One clock read and one call per die, and no array: the frame loop must not
    // build garbage, and both dice have to share the throw's own instant.
    const elapsed = performance.now() - startedAt.current
    const pose = diceFall(elapsed)
    place(first.current, roll[0], 0, pose)
    place(second.current, roll[1], 1, pose)
    if (elapsed >= DICE_TOTAL_MS) {
      setMode('landed')
      return
    }
    invalidate()
  })

  if (mode === 'hidden' || roll === null) return null

  return (
    <group>
      {roll.slice(0, DIE_SPOTS.length).map((value, index) => {
        const spot = DIE_SPOTS[index]
        return (
          <group
            key={index}
            position={[spot.x, DIE_SIZE / 2, spot.z]}
            ref={index === 0 ? first : second}
            rotation={eulerFor(value)}
          >
            <mesh castShadow geometry={geometry} material={materials} />
          </group>
        )
      })}
    </group>
  )
}
