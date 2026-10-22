/**
 * Walking a piece along the ring, one cell at a time (X10 of
 * ``monopoly-3d-table.md``).
 *
 * The server publishes the position a throw *reached*, never the cells it
 * crossed, so the walk is the client's arithmetic on two published facts: where
 * the piece was and where it is. Pure and free of ``three`` like ``dice.ts``, so
 * the shape of the walk -- which cells, in what order, and when it starts -- is
 * pinned by the DOM-less harness instead of judged from a capture.
 *
 * **Two shapes of move, and one thing it refuses.** A forward distance a throw can
 * produce is a **walk**: one cell at a time, hopping between them. Any other move
 * to a place -- jail, a card, a piece pushed back -- is a **jump**: a single arc
 * from where the piece was to where it lands, because those moves go *to* a cell
 * and not across a distance, and stepping them cell by cell would tell the player
 * the dice did something they did not. A piece that did not move is not animated
 * at all.
 */

import { BOARD_SIZE } from '../board'

/** How long one cell takes, in ms. */
export const WALK_STEP_MS = 160

/** The longest throw, which is also the longest walk. */
export const WALK_MAX_STEPS = 12

/** How high above the board the piece rises in the middle of a step, in cells. */
export const WALK_HOP = 0.18

/** How long a single jump takes, in ms. */
export const JUMP_MS = 420

/** How high a jump rises, in cells: over a cell's worth, so it reads as a leap. */
export const JUMP_HOP = 0.9

/**
 * What a piece does to reach the cell the server published.
 *
 * ``walk`` names every cell in order; ``jump`` names only the destination, and
 * that difference is the whole contract: a jump must never be interpolated
 * through cells the piece did not stand on.
 */
export type WalkPlan =
  | { kind: 'walk'; steps: number; cells: number[] }
  | { kind: 'jump'; to: number }

/**
 * The walk from ``from`` to ``to``, or ``null`` when that move is not a throw.
 *
 * The ring is a circuit, so the distance is measured forward and wraps: 38 to 1
 * is three cells, not thirty-seven.
 */
export function walkPlan(from: number, to: number): WalkPlan | null {
  const distance = (((to - from) % BOARD_SIZE) + BOARD_SIZE) % BOARD_SIZE
  if (distance === 0) return null
  if (distance > WALK_MAX_STEPS) return { kind: 'jump', to }
  const cells = Array.from({ length: distance }, (_, index) => (from + index + 1) % BOARD_SIZE)
  return { kind: 'walk', steps: distance, cells }
}

/** A jump leaves and arrives softly instead of snapping into motion. */
function easeInOut(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

/** Where one piece is, part-way through its walk. */
export type WalkPose = {
  /** The cell the piece is leaving. */
  from: number
  /** The cell it is heading to. */
  to: number
  /** How far it is from ``from`` to ``to``, in ``0..1``. */
  t: number
  /** How far it is above the board, in cells. Zero between steps. */
  lift: number
  /** Whether the walk is over: ``from`` and ``to`` are the destination. */
  done: boolean
}

/**
 * One piece's place in its walk at ``elapsedMs``.
 *
 * Negative elapsed is clamped to the first cell on purpose: the walk is asked for
 * while the dice are still falling, so the piece has to wait where it was until
 * the throw is over instead of jumping to the destination and then walking back.
 */
export function walkPose(plan: WalkPlan, start: number, elapsedMs: number): WalkPose {
  const elapsed = Math.max(0, elapsedMs)
  if (plan.kind === 'jump') {
    if (elapsed >= JUMP_MS) {
      return { from: plan.to, to: plan.to, t: 1, lift: 0, done: true }
    }
    const progress = elapsed / JUMP_MS
    return {
      from: start,
      to: plan.to,
      t: easeInOut(progress),
      lift: Math.sin(Math.PI * progress) * JUMP_HOP,
      done: false,
    }
  }
  const last = plan.cells[plan.steps - 1]
  if (elapsed >= plan.steps * WALK_STEP_MS) {
    return { from: last, to: last, t: 1, lift: 0, done: true }
  }
  const step = Math.floor(elapsed / WALK_STEP_MS)
  const local = (elapsed % WALK_STEP_MS) / WALK_STEP_MS
  return {
    from: step === 0 ? start : plan.cells[step - 1],
    to: plan.cells[step],
    t: local,
    lift: Math.sin(Math.PI * local) * WALK_HOP,
    done: false,
  }
}
