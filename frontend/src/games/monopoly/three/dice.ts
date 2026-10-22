/**
 * The two dice: their faces, the way they fall and when they are on the table
 * (X9 of ``monopoly-3d-table.md``).
 *
 * Deliberately pure and free of ``three``, like ``figures.ts``: the scene turns
 * these numbers into meshes and quaternions, and the DOM-less harness can pin
 * everything that would otherwise be a matter of opinion -- which face carries
 * which number, where the die comes to rest, and when a throw is a new throw.
 *
 * The dice are **decorative**: the throw is the server's fact, published as
 * ``last_roll``, and this module never invents or re-rolls it. What it decides is
 * how the number the server already decided is shown.
 */

import type { Point3 } from './camera'

/** The edge of one die, in cells. A real die is about a third of a space. */
export const DIE_SIZE = 0.42

/**
 * The value printed on each face, in the order ``BoxGeometry`` expects materials:
 * ``+x, -x, +y, -y, +z, -z``.
 *
 * Opposite faces add up to seven, which is what makes a die a die: a die that
 * does not is one a player can feel is wrong even if they cannot say why.
 */
export const DIE_FACES: readonly number[] = [2, 5, 1, 6, 3, 4]

/** The six face normals, in the same order as ``DIE_FACES``. */
const FACE_NORMALS: readonly Point3[] = [
  { x: 1, y: 0, z: 0 },
  { x: -1, y: 0, z: 0 },
  { x: 0, y: 1, z: 0 },
  { x: 0, y: -1, z: 0 },
  { x: 0, y: 0, z: 1 },
  { x: 0, y: 0, z: -1 },
]

/** How high above its resting place a die starts falling, in cells. */
export const DICE_START_HEIGHT = 2.6

/** How long one throw takes from the first frame to the die at rest, in ms. */
export const DICE_TOTAL_MS = 1100

/** Where the fall ends and the first bounce begins, as a fraction of the whole. */
const FALL_END = 0.45
const FIRST_BOUNCE_END = 0.6
const SECOND_BOUNCE_END = 0.7
/** The two bounces' heights, in cells: the second is visibly smaller. */
const FIRST_BOUNCE = 0.22
const SECOND_BOUNCE = 0.09

/** The normal of the face that carries ``value``. */
export function faceNormal(value: number): Point3 {
  const face = DIE_FACES.indexOf(value)
  return FACE_NORMALS[face < 0 ? 2 : face]
}

/** A rotation as the three angles the scene sets on the die. */
export type DieOrientation = { x: number; y: number; z: number }

/**
 * The angles that leave the die with ``value`` on top.
 *
 * Each one is a single turn about one axis -- a quarter for every value except
 * the six, which is a half -- so the order of the angles cannot matter and the
 * test can rebuild the rotation by hand. The alternative, a random resting pose
 * per throw, would show a number that is not the one the server rolled.
 */
export function orientationFor(value: number): DieOrientation {
  if (value === 6) return { x: Math.PI, y: 0, z: 0 }
  if (value === 2) return { x: 0, y: 0, z: Math.PI / 2 }
  if (value === 5) return { x: 0, y: 0, z: -Math.PI / 2 }
  if (value === 3) return { x: -Math.PI / 2, y: 0, z: 0 }
  if (value === 4) return { x: Math.PI / 2, y: 0, z: 0 }
  // One is on top already, and an unknown value falls back to it instead of
  // inventing a face: the scene never asks, but a lie here would be silent.
  return { x: 0, y: 0, z: 0 }
}

/** Where one die is, mid-throw. */
export type DiePose = {
  /** How far above its resting place it is, in cells. Never negative. */
  lift: number
  /** How much of the tumble is done: 0 at the first frame, 1 at rest. */
  spin: number
}

/** A number clamped into ``[0, 1]``. */
function fraction(value: number): number {
  return Math.min(1, Math.max(0, value))
}

/**
 * One die's place in the throw at ``elapsedMs``.
 *
 * A fall, two bounces and a rest, all as arithmetic on the elapsed time: no
 * physics engine, no randomness, so the same throw looks the same on every
 * machine and a capture of it is reproducible. The rest is the last third on
 * purpose -- the number has to be readable for a moment before the turn moves on.
 */
export function diceFall(elapsedMs: number): DiePose {
  const t = fraction(elapsedMs / DICE_TOTAL_MS)
  const spin = 1 - Math.pow(1 - fraction(t / SECOND_BOUNCE_END), 3)
  if (t < FALL_END) {
    const fall = t / FALL_END
    // Accelerating from rest: the square is the shape a falling body has.
    return { lift: DICE_START_HEIGHT * (1 - fall * fall), spin }
  }
  if (t < FIRST_BOUNCE_END) {
    const bounce = (t - FALL_END) / (FIRST_BOUNCE_END - FALL_END)
    return { lift: 4 * FIRST_BOUNCE * bounce * (1 - bounce), spin }
  }
  if (t < SECOND_BOUNCE_END) {
    const bounce = (t - FIRST_BOUNCE_END) / (SECOND_BOUNCE_END - FIRST_BOUNCE_END)
    return { lift: 4 * SECOND_BOUNCE * bounce * (1 - bounce), spin }
  }
  return { lift: 0, spin: 1 }
}

/** What the table says about the throw: whose turn it is and what came up. */
export type DiceView = { turn: string | null; roll: readonly number[] | null }

/**
 * What the dice should do now (X9).
 *
 * ``animate`` a throw that arrives while the player is watching, ``landed`` a
 * throw that was already on the table when the view first arrived (rejoining a
 * match must not replay a roll nobody saw), ``hidden`` when the turn moves on --
 * the dice leave so the next player's throw starts clean -- and ``keep`` when
 * nothing about the throw changed.
 *
 * The seam to remember: two identical throws by the same seat in the same turn
 * look like no change at all, because the view publishes the pair and not a
 * counter of throws. It costs a replay of the tumble, never a wrong number.
 */
export function diceState(
  previous: DiceView | null,
  next: DiceView,
): 'animate' | 'landed' | 'hidden' | 'keep' {
  if (next.roll === null) return previous?.roll === null ? 'keep' : 'hidden'
  if (previous === null) return 'landed'
  if (previous.roll !== null && sameRoll(previous.roll, next.roll)) {
    // The same pair can only be the same throw: the turn decides whether the
    // dice are still that player's or belong to the next one.
    return previous.turn === next.turn ? 'keep' : 'hidden'
  }
  return 'animate'
}

/** Whether two published throws are the same pair. */
function sameRoll(left: readonly number[], right: readonly number[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}
