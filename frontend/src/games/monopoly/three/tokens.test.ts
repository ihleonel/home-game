import { describe, expect, it } from 'vitest'
import type { MatchSeatRosterEntry } from '../../matchRoster'
import type { MatchState } from '../../registry'
import { SEAT_TONES } from '../display'
import { SEATED_TONE_FALLBACK, seatedTokens } from './tokens'
import type { MonopolyPlayer, MonopolyView } from '../view'

function entry(seat: string, index: number, marker: string): MatchSeatRosterEntry {
  return {
    seat_id: seat,
    index,
    display_name: `Jugador ${index}`,
    game_marker: marker,
    game_marker_label: marker,
  }
}

function player(overrides: Partial<MonopolyPlayer> & { seat: string }): MonopolyPlayer {
  return {
    cash: 1500,
    position: 0,
    properties: [],
    in_jail: false,
    jail_turns: 0,
    jail_cards: 0,
    eliminated: false,
    ...overrides,
  }
}

function view(overrides: Partial<MonopolyView> = {}): MonopolyView {
  return {
    finished: false,
    winner: null,
    phase: 'awaiting_roll',
    turn: 'seat-0',
    players: [player({ seat: 'seat-0' })],
    owners: {},
    last_roll: null,
    pending: null,
    decks: null,
    last_card: null,
    buildings: {},
    mortgaged: {},
    bank: null,
    debt: null,
    auction: null,
    offers: [],
    actions: [],
    you: 'seat-0',
    ...overrides,
  }
}

function match(rawView: MonopolyView, roster: MatchSeatRosterEntry[]): MatchState<MonopolyView> {
  return { matchRef: 'match-1', seatIndex: 0, version: 1, roster, view: rawView }
}

describe('the seated tokens of the 3D table', () => {
  it('carries one token per seat still in the match, never for an eliminated seat', () => {
    const rawView = view({
      players: [
        player({ seat: 'seat-0' }),
        player({ seat: 'seat-1', eliminated: true }),
        player({ seat: 'seat-2' }),
      ],
    })

    const tokens = seatedTokens(
      match(rawView, [entry('seat-0', 0, 'perro'), entry('seat-1', 1, 'barco'), entry('seat-2', 2, 'gato')]),
    )

    expect(tokens.map((token) => token.seat)).toEqual(['seat-0', 'seat-2'])
  })

  it('reads the silhouette from the roster marker and the tone from the roster index', () => {
    // The scene must not invent either: the marker is the player's choice in the
    // room, and the tone is the same one the owned spaces and the players list
    // paint, keyed on the roster's own ``index``.
    const rawView = view({
      players: [player({ seat: 'seat-0' }), player({ seat: 'seat-1' })],
    })

    const tokens = seatedTokens(
      match(rawView, [entry('seat-0', 0, 'perro'), entry('seat-1', 1, 'barco')]),
    )

    expect(tokens).toEqual([
      { seat: 'seat-0', figure: 'perro', tone: SEAT_TONES[0] },
      { seat: 'seat-1', figure: 'barco', tone: SEAT_TONES[1] },
    ])
  })

  it('falls back to the neutral counter and to no tone for a seat the roster cannot name', () => {
    const rawView = view({ players: [player({ seat: 'seat-9' })] })

    const tokens = seatedTokens(match(rawView, []))

    expect(tokens).toEqual([
      { seat: 'seat-9', figure: SEATED_TONE_FALLBACK.figure, tone: SEATED_TONE_FALLBACK.tone },
    ])
  })
})
