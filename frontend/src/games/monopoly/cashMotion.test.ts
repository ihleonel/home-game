import { describe, expect, it } from 'vitest'
import {
  CASH_BUDGET_MS,
  CASH_FRAME_MS,
  CASH_FRAMES,
  cashAnnouncement,
  cashDuration,
  planCashMotion,
  rolledValue,
} from './cashMotion'
import type { CashMotion } from './cashMotion'

/** One seat and its money, the way the view reports them. */
function seat(id: string, cash: number): { seat: string; cash: number } {
  return { seat: id, cash }
}

/** A change already planned, so a test can drive the clock itself. */
function motion(from: number, to: number): CashMotion {
  const [planned] = planCashMotion([seat('seat-0', to)], new Map([['seat-0', from]]))
  if (planned === undefined) throw new Error(`no motion planned for ${from} -> ${to}`)
  return planned
}

/** The amount a name is shown with, read from the same roster the panel reads. */
function nameOf(id: string): string {
  return id === 'seat-0' ? 'Ana' : 'Beto'
}

describe('planning the cash motion', () => {
  it('reports one motion per seat whose money moved, in the order the view lists them', () => {
    const planned = planCashMotion(
      [seat('seat-1', 950), seat('seat-0', 1700)],
      new Map([
        ['seat-0', 1500],
        ['seat-1', 1200],
      ]),
    )
    expect(planned).toEqual([
      { seat: 'seat-1', from: 1200, to: 950, delta: -250, trend: 'down' },
      { seat: 'seat-0', from: 1500, to: 1700, delta: 200, trend: 'up' },
    ])
  })

  it('plans nothing for a seat whose money did not move or that the table never saw', () => {
    // The second case is a seat that joined between two views: an amount with no
    // "before" cannot be counted from, and inventing a start would show a change
    // the server never reported.
    expect(
      planCashMotion([seat('seat-0', 1500), seat('seat-9', 1500)], new Map([['seat-0', 1500]])),
    ).toEqual([])
  })

  it('reads the direction from the net change alone', () => {
    expect(motion(1500, 1501).trend).toBe('up')
    expect(motion(1500, 1499).trend).toBe('down')
    expect(motion(1500, 1499).delta).toBe(-1)
  })
})

describe('the rolling count', () => {
  it('spends one frame per unit while the change fits the budget', () => {
    const five = motion(1000, 1005)
    expect(CASH_FRAMES).toBe(72)
    expect(cashDuration(five)).toBeCloseTo(5 * CASH_FRAME_MS)
    // Every frame shows the next unit, which is what "unidad a unidad" means.
    const seen = [0, 1, 2, 3, 4, 5].map((frame) => rolledValue(five, frame * CASH_FRAME_MS))
    expect(seen).toEqual([1000, 1001, 1002, 1003, 1004, 1005])
  })

  it('fits the whole budget before it accelerates', () => {
    expect(cashDuration(motion(1000, 1000 + CASH_FRAMES))).toBe(CASH_BUDGET_MS)
    expect(cashDuration(motion(1000, 1000 + CASH_FRAMES + 1))).toBe(CASH_BUDGET_MS)
  })

  it('accelerates past the frame budget without overshooting, turning back or skipping the end', () => {
    const charge = motion(1500, 200)
    let previous = charge.from
    for (let elapsed = 0; elapsed <= 1400; elapsed += 5) {
      const value = rolledValue(charge, elapsed)
      expect(Number.isInteger(value)).toBe(true)
      expect(value).toBeLessThanOrEqual(previous)
      expect(value).toBeGreaterThanOrEqual(charge.to)
      previous = value
    }
    // It really accelerates: one frame moves several units instead of one.
    expect(
      Math.abs(rolledValue(charge, 2 * CASH_FRAME_MS) - rolledValue(charge, CASH_FRAME_MS)),
    ).toBeGreaterThan(1)
    expect(rolledValue(charge, CASH_BUDGET_MS)).toBe(200)
    expect(rolledValue(charge, 1_000_000)).toBe(200)
  })

  it('starts exactly at the amount the seat had and ends exactly at the one it has', () => {
    const payment = motion(950, 1150)
    expect(rolledValue(payment, 0)).toBe(950)
    expect(rolledValue(payment, -50)).toBe(950)
    expect(rolledValue(payment, cashDuration(payment))).toBe(1150)
  })
})

describe('the announcement of a change', () => {
  it('names the seat and the net amount, once', () => {
    expect(cashAnnouncement([motion(1500, 1700)], nameOf)).toBe('Ana +$200')
    expect(cashAnnouncement([motion(1500, 1425)], nameOf)).toBe('Ana −$75')
  })

  it('announces every seat a single view moved, in one sentence', () => {
    const planned = planCashMotion(
      [seat('seat-0', 1700), seat('seat-1', 1125)],
      new Map([
        ['seat-0', 1500],
        ['seat-1', 1200],
      ]),
    )
    expect(cashAnnouncement(planned, nameOf)).toBe('Ana +$200. Beto −$75')
  })

  it('says nothing when no seat moved money', () => {
    expect(cashAnnouncement([], nameOf)).toBe('')
  })
})
