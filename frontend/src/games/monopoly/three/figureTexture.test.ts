import { describe, expect, it } from 'vitest'
import { SEAT_TONES } from '../display'
import { TOKEN_HALO, TOKEN_INK, TOKEN_PAPER, mixWithWhite, tokenInks } from './figureTexture'

/** The perceived brightness of a ``#rrggbb`` colour, 0-255, good enough to order two inks. */
function brightness(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16)
  const r = (value >> 16) & 0xff
  const g = (value >> 8) & 0xff
  const b = value & 0xff
  return 0.299 * r + 0.587 * g + 0.114 * b
}

describe('the inks of a 3D chip', () => {
  it('prints the seat tone on the rim and a lighter bloom of it around the chip', () => {
    // A dark rim alone reads as ink on the white chip; what reads as neon is the
    // bloom, so it must be the same hue and clearly brighter.
    for (const tone of SEAT_TONES) {
      const inks = tokenInks(tone)
      expect(inks.rim).toBe(tone)
      expect(inks.glow).not.toBe(tone)
      expect(brightness(inks.glow)).toBeGreaterThan(brightness(tone))
      expect(inks.paper).toBe(TOKEN_PAPER)
    }
  })

  it('widens the rim when there is a tone, so the colour survives a small chip', () => {
    // A hairline in a dark tone looks exactly like the black ink it replaces on
    // the far edge of the table, which is the bug this increment fixes.
    const printed = tokenInks(null)
    for (const tone of SEAT_TONES) {
      const toned = tokenInks(tone)
      expect(toned.rimWidth).toBeGreaterThan(printed.rimWidth)
      expect(toned.rimWidth).toBeLessThan(0.1)
    }
  })

  it('keeps the printed inks and drops the glow for a seat with no tone', () => {
    const inks = tokenInks(null)

    expect(inks.rim).toBe(TOKEN_INK)
    expect(inks.glow).toBe('transparent')
    expect(inks.paper).toBe(TOKEN_PAPER)
  })

  it('leaves the chip a margin inside the canvas, so the bloom is never clipped', () => {
    // The glow is painted inside the same square texture the chip is drawn in:
    // without a margin the halo would be cut off at the edge of the sprite.
    expect(TOKEN_HALO).toBeGreaterThan(0)
    expect(TOKEN_HALO).toBeLessThan(0.25)
  })

  it('mixes a colour toward white without touching a colour it cannot read', () => {
    expect(mixWithWhite('#000000', 0)).toBe('#000000')
    expect(mixWithWhite('#000000', 1)).toBe('#ffffff')
    expect(mixWithWhite('#ffffff', 0.5)).toBe('#ffffff')
    // Halfway from black is a grey, not a channel-shifted colour.
    expect(mixWithWhite('#000000', 0.5)).toBe('#808080')
    expect(mixWithWhite('#5b2a86', 0.5)).toBe('#ad95c3')
    // An unknown spelling is returned unchanged instead of turning into a colour.
    expect(mixWithWhite('rebeccapurple', 0.5)).toBe('rebeccapurple')
  })
})
