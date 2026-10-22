import { describe, expect, it } from 'vitest'
import { BOARD_SIZE } from '../board'
import {
  JUMP_HOP,
  JUMP_MS,
  WALK_HOP,
  WALK_MAX_STEPS,
  WALK_STEP_MS,
  walkPlan,
  walkPose,
} from './walk'

describe('the walk a throw asks for', () => {
  it('visits every cell between where the piece was and where it lands', () => {
    expect(walkPlan(7, 10)).toEqual({ kind: 'walk', steps: 3, cells: [8, 9, 10] })
    expect(walkPlan(0, 1)).toEqual({ kind: 'walk', steps: 1, cells: [1] })
  })

  it('crosses GO the way the circuit does', () => {
    // The board is a ring: 38 + 3 is 1, and the piece has to pass 39 and 0 on the
    // way instead of walking backwards across the whole board.
    expect(walkPlan(38, 1)).toEqual({ kind: 'walk', steps: 3, cells: [39, 0, 1] })
    expect(walkPlan(39, 0)).toEqual({ kind: 'walk', steps: 1, cells: [0] })
  })

  it('walks the longest throw and jumps anything longer', () => {
    const longest = walkPlan(0, WALK_MAX_STEPS)
    expect(longest?.kind === 'walk' ? longest.steps : null).toBe(WALK_MAX_STEPS)
    // Past the longest throw the move is no longer a distance the dice can
    // explain, so it is a place: one jump, no cells in between.
    expect(walkPlan(0, WALK_MAX_STEPS + 1)).toEqual({ kind: 'jump', to: WALK_MAX_STEPS + 1 })
  })

  it('jumps once to a destination a throw did not reach', () => {
    // Jail, a card, a piece pushed back: the move is to a place, not across a
    // distance, so stepping it cell by cell would be a lie about what happened.
    expect(walkPlan(30, 10)).toEqual({ kind: 'jump', to: 10 })
    expect(walkPlan(10, 7)).toEqual({ kind: 'jump', to: 7 })
    expect(walkPlan(0, 20)).toEqual({ kind: 'jump', to: 20 })
  })

  it('refuses to animate a piece that did not move', () => {
    expect(walkPlan(10, 10)).toBeNull()
  })
})

describe('where the piece is during the walk', () => {
  const plan = walkPlan(7, 10)
  if (plan === null || plan.kind !== 'walk') throw new Error('the walk from 7 to 10 has to exist')

  it('waits at the cell it came from until the walk starts', () => {
    // The dice are still falling while the walk waits, so a negative elapsed --
    // or zero -- has to leave the piece where it was, not at the destination.
    for (const elapsed of [-500, 0]) {
      const pose = walkPose(plan, 7, elapsed)
      expect([elapsed, pose.from, pose.t, pose.lift, pose.done]).toEqual([elapsed, 7, 0, 0, false])
    }
  })

  it('moves one cell at a time, hopping between them', () => {
    const half = walkPose(plan, 7, WALK_STEP_MS / 2)
    expect([half.from, half.to, half.t]).toEqual([7, 8, 0.5])
    expect(half.lift).toBeGreaterThan(0)

    const secondStep = walkPose(plan, 7, WALK_STEP_MS * 1.5)
    expect([secondStep.from, secondStep.to, secondStep.t]).toEqual([8, 9, 0.5])
  })

  it('touches the board between steps, so the hop reads as a hop', () => {
    for (let step = 0; step <= plan.steps; step += 1) {
      expect(walkPose(plan, 7, step * WALK_STEP_MS).lift).toBeCloseTo(0)
    }
    expect(walkPose(plan, 7, WALK_STEP_MS / 2).lift).toBeCloseTo(WALK_HOP)
  })

  it('ends on the cell the throw reached, and never overshoots it', () => {
    const end = walkPose(plan, 7, plan.steps * WALK_STEP_MS)
    expect([end.from, end.to, end.lift, end.done]).toEqual([10, 10, 0, true])
    const later = walkPose(plan, 7, plan.steps * WALK_STEP_MS * 4)
    expect([later.from, later.to, later.done]).toEqual([10, 10, true])
  })

  it('covers the whole ring without skipping a cell', () => {
    // Every throw of the ring, walked to the end: the last cell is always the
    // destination, which is the property that keeps the piece from landing next
    // door to where the server says it is.
    for (let from = 0; from < BOARD_SIZE; from += 1) {
      for (let steps = 1; steps <= WALK_MAX_STEPS; steps += 1) {
        const to = (from + steps) % BOARD_SIZE
        const walk = walkPlan(from, to)
        if (walk === null || walk.kind !== 'walk') throw new Error(`no walk from ${from} to ${to}`)
        expect([from, to, walkPose(walk, from, walk.steps * WALK_STEP_MS).to]).toEqual([from, to, to])
      }
    }
  })
})

describe('the single jump to a place the dice did not reach', () => {
  const jump = walkPlan(30, 10)
  if (jump === null || jump.kind !== 'jump') throw new Error('the jump from 30 to 10 has to exist')

  it('waits where the piece was until the dice are done', () => {
    for (const elapsed of [-400, 0]) {
      const pose = walkPose(jump, 30, elapsed)
      expect([elapsed, pose.from, pose.to, pose.t, pose.done]).toEqual([elapsed, 30, 10, 0, false])
    }
  })

  it('crosses the board in one arc instead of visiting the cells between', () => {
    // The whole point of the jump: at no instant is the piece on a cell it did
    // not occupy. Only the two ends are ever named.
    for (let elapsed = 0; elapsed < JUMP_MS; elapsed += JUMP_MS / 20) {
      const pose = walkPose(jump, 30, elapsed)
      expect([pose.from, pose.to]).toEqual([30, 10])
    }
    expect(walkPose(jump, 30, JUMP_MS / 2).lift).toBeCloseTo(JUMP_HOP)
    expect(walkPose(jump, 30, JUMP_MS / 2).t).toBeCloseTo(0.5)
  })

  it('lands on the destination and stays there', () => {
    const end = walkPose(jump, 30, JUMP_MS)
    expect([end.from, end.to, end.t, end.lift, end.done]).toEqual([10, 10, 1, 0, true])
    expect(walkPose(jump, 30, JUMP_MS * 3).done).toBe(true)
  })
})
