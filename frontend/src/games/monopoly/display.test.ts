import { describe, expect, it } from 'vitest'
import type { MatchSeatRosterEntry } from '../matchRoster'
import { SEAT_TONES, seatIndexOf, seatTone, signedMoney } from './display'

/** A roster entry needs every public field the server projects (S1). */
function entry(seat: string, index: number, name: string): MatchSeatRosterEntry {
  return {
    seat_id: seat,
    index,
    display_name: name,
    game_marker: 'sombrero',
    game_marker_label: 'Sombrero',
  }
}

const roster: MatchSeatRosterEntry[] = [entry('seat-0', 0, 'Ana'), entry('seat-5', 5, 'Beto')]

describe('the seat tones', () => {
  it('keeps one tone per seat the table can hold and never repeats one inside the range', () => {
    // Monopoly seats at most eight players, so the palette is exactly that:
    // two seats sharing a tone would defeat the whole point of the colour.
    expect(SEAT_TONES).toHaveLength(8)
    expect(new Set(SEAT_TONES).size).toBe(SEAT_TONES.length)
    for (const tone of SEAT_TONES) expect(tone).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('reads the tone from the roster seat index and wraps around the palette', () => {
    expect(seatTone(0)).toBe(SEAT_TONES[0])
    expect(seatTone(1)).toBe(SEAT_TONES[1])
    expect(seatTone(SEAT_TONES.length)).toBe(SEAT_TONES[0])
    expect(seatTone(SEAT_TONES.length + 3)).toBe(SEAT_TONES[3])
  })

  it('never invents a tone for a seat it cannot place', () => {
    // A seat the roster does not name has no index, so there is no colour to
    // paint: the badge still says who owns the space, the tone just stays out.
    expect(seatTone(null)).toBeNull()
    expect(seatTone(undefined)).toBeNull()
    expect(seatTone(-1)).toBeNull()
    expect(seatTone(1.5)).toBeNull()
  })

  it('takes the index from the roster field and never parses it out of the seat id', () => {
    // ``seat-5`` happens to spell its index, but the id is an opaque string:
    // the public identity is the roster's ``index``, and that is what the tone
    // must follow.
    expect(seatIndexOf(roster, 'seat-5')).toBe(5)
    expect(seatIndexOf(roster, 'seat-0')).toBe(0)
    expect(seatIndexOf(roster, 'seat-9')).toBeNull()
  })
})

describe('the signed amount of a change', () => {
  it('prints the sign in front of the money the delta formatter already spells', () => {
    // The digits are ``formatMoney``'s, so a change can never be grouped or
    // abbreviated differently from the balance it moves.
    expect(signedMoney(200)).toBe('+$200')
    expect(signedMoney(1200)).toBe('+$1.200')
    expect(signedMoney(-75)).toBe('−$75')
    expect(signedMoney(-1200)).toBe('−$1.200')
  })

  it('uses the minus sign the panel already prints and never a hyphen', () => {
    // ``formatMoney`` writes ``-$75`` for a negative balance; a *change* is read
    // beside a plus, and the project already spells that sign as U+2212.
    expect(signedMoney(-75)).toContain('\u2212')
    expect(signedMoney(-75)).not.toContain('-')
  })

  it('has no sign for a change of nothing', () => {
    expect(signedMoney(0)).toBe('$0')
  })
})
