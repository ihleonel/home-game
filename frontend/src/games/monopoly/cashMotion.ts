/**
 * How a seat's money is counted from one published view to the next.
 *
 * The server never sends a delta: ``lib/match.ts`` merges whole views and the
 * version only moves forward, so the only honest way to show a change is to
 * compare the amounts the two views reported. That comparison, and the clock
 * that turns it into a number, live here -- pure functions with no React and no
 * timers -- for two reasons: the counting rule is the part worth testing, and
 * the project's suite renders with ``react-dom/server`` (no jsdom), so nothing
 * that owns a ``requestAnimationFrame`` can be exercised from a test.
 *
 * The counting rule itself (S3 of ``monopoly-capital-bar.md``): money is counted
 * one unit per frame, which is what a player reads as "unidad a unidad", for as
 * long as the whole change fits the budget. Past that it accelerates, because a
 * hundred and twenty-dollar rent painted at one dollar per frame would take two
 * seconds and a twelve-hundred-dollar one twenty -- while sixty frames per
 * second can never show more than seventy-two different values in 1,2 s. The
 * count always starts at the old amount, never turns back, never overshoots and
 * always lands exactly on the new one.
 */

import { signedMoney } from './display'
import type { MonopolyPlayer } from './view'

/** Which way a seat's money moved. */
export type CashTrend = 'up' | 'down'

/** One seat's count, between the amount it had and the amount it has. */
export type CashMotion = {
  seat: string
  from: number
  to: number
  /** ``to - from``: the net change, kept so the announcement need not redo it. */
  delta: number
  trend: CashTrend
}

/** One frame at sixty frames per second, which is the speed of a unit. */
export const CASH_FRAME_MS = 1000 / 60

/** How long a count may last, whatever the amount that moves. */
export const CASH_BUDGET_MS = 1200

/**
 * How many whole units the budget can paint one per frame.
 *
 * Rounded rather than floored: ``1000 / 60`` is not exact, so the division lands
 * a hair under seventy-two, and a change of exactly seventy-two units is the
 * last one that still fits.
 */
export const CASH_FRAMES = Math.round(CASH_BUDGET_MS / CASH_FRAME_MS)

/**
 * Plan one count per seat whose money moved, in the order the view lists them.
 *
 * A seat the previous view did not carry is not planned: an amount with no
 * "before" has nothing to count from, and inventing a start would show a change
 * the server never reported.
 */
export function planCashMotion(
  players: readonly Pick<MonopolyPlayer, 'seat' | 'cash'>[],
  previous: ReadonlyMap<string, number>,
): CashMotion[] {
  const motions: CashMotion[] = []
  for (const player of players) {
    const before = previous.get(player.seat)
    if (before === undefined || before === player.cash) continue
    const delta = player.cash - before
    motions.push({
      seat: player.seat,
      from: before,
      to: player.cash,
      delta,
      trend: delta > 0 ? 'up' : 'down',
    })
  }
  return motions
}

/**
 * How long this count lasts: one frame per unit while it fits, the budget after.
 */
export function cashDuration(motion: CashMotion): number {
  return Math.min(Math.abs(motion.delta) * CASH_FRAME_MS, CASH_BUDGET_MS)
}

/**
 * The amount to show ``elapsedMs`` into the count.
 *
 * Every answer is an integer between ``from`` and ``to`` and the sequence never
 * turns back, so the number on screen is always an amount the seat held or holds
 * on its way there. ``Math.round`` and not ``Math.floor``: the first unit has to
 * appear on the first frame, or a small change would start by standing still.
 */
export function rolledValue(motion: CashMotion, elapsedMs: number): number {  const units = Math.abs(motion.delta)
  if (units === 0) return motion.to
  if (elapsedMs <= 0) return motion.from
  const duration = cashDuration(motion)
  if (elapsedMs >= duration) return motion.to
  const moved = Math.min(Math.round((elapsedMs / duration) * units), units)
  return motion.trend === 'up' ? motion.from + moved : motion.from - moved
}

/**
 * The amount to show for a count, given whether less motion was asked for.
 *
 * The preference never changes *what* is learned, only that it is not counted:
 * a player who asked for less motion gets the new amount at once instead of a
 * number running towards it. Every caller goes through here so the rule lives in
 * one place, and so it can be asserted without a clock.
 */
export function shownAmount(
  motion: CashMotion,
  elapsedMs: number,
  reduced: boolean,
): number {
  return reduced ? motion.to : rolledValue(motion, elapsedMs)
}

/**
 * What a screen reader is told about the changes of one view.
 *
 * The net amount, once, per seat: never the units the count runs through, which
 * a live region would read as a burst of numbers nobody can follow.
 */
export function cashAnnouncement(
  motions: readonly CashMotion[],
  nameOf: (seat: string) => string,
): string {
  return motions.map((motion) => `${nameOf(motion.seat)} ${signedMoney(motion.delta)}`).join('. ')
}
