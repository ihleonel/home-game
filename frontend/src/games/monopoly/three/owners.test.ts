import { describe, expect, it } from 'vitest'
import type { MatchSeatRosterEntry } from '../../matchRoster'
import type { MatchState } from '../../registry'
import { SEAT_TONES } from '../display'
import type { MonopolyPlayer, MonopolyView } from '../view'
import { ownedCells, ownerSignature } from './owners'

function entry(seat: string, index: number): MatchSeatRosterEntry {
  return {
    seat_id: seat,
    index,
    display_name: `Jugador ${index}`,
    game_marker: 'perro',
    game_marker_label: 'Perro',
  }
}

function player(seat: string): MonopolyPlayer {
  return {
    seat,
    cash: 1500,
    position: 0,
    properties: [],
    in_jail: false,
    jail_turns: 0,
    jail_cards: 0,
    eliminated: false,
  }
}

function view(owners: Record<string, string>): MonopolyView {
  return {
    finished: false,
    winner: null,
    phase: 'awaiting_roll',
    turn: 'seat-0',
    players: [player('seat-0'), player('seat-1')],
    owners,
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
  }
}

function match(owners: Record<string, string>, roster: MatchSeatRosterEntry[]): MatchState<MonopolyView> {
  return { matchRef: 'match-1', seatIndex: 0, version: 1, roster, view: view(owners) }
}

describe('the owned cells of the 3D table', () => {
  it('takes the owner from the view and the ink from the roster index', () => {
    // The two facts live apart on purpose: ownership is the server's
    // ``view.owners``, the colour is the roster entry's ``index``. Neither is
    // derived from the other, and the seat id is never parsed for a tone.
    const board = match({ '1': 'seat-0', '3': 'seat-1' }, [entry('seat-0', 0), entry('seat-1', 1)])

    expect(ownedCells(board)).toEqual([
      { index: 1, ink: SEAT_TONES[0] },
      { index: 3, ink: SEAT_TONES[1] },
    ])
  })

  it('leaves a board nobody bought empty', () => {
    expect(ownedCells(match({}, [entry('seat-0', 0)]))).toEqual([])
  })

  it('marks a cell whose seat the roster cannot name, without inventing an ink', () => {
    // The server says the cell is owned, so the frame is still drawn; the tone
    // is the only thing withheld, and the painter falls back to neutral ink.
    expect(ownedCells(match({ '3': 'seat-9' }, []))).toEqual([{ index: 3, ink: null }])
  })

  it('reads only the spaces the board draws, in board order', () => {
    // ``owners`` arrives as a ``jsonb`` map keyed by index: a key outside the
    // circuit is not a cell of this board and must never paint one.
    const board = match(
      { '21': 'seat-1', '1': 'seat-0', 'nope': 'seat-1', '99': 'seat-0' },
      [entry('seat-0', 0), entry('seat-1', 1)],
    )

    expect(ownedCells(board).map((cell) => cell.index)).toEqual([1, 21])
  })
})

describe('the signature the cell faces are repainted from', () => {
  it('is empty while the bank owns the whole board', () => {
    expect(ownerSignature([])).toBe('')
  })

  it('does not change when the same owners arrive in a fresh view object', () => {
    // The board polls, so the view is a new object on every answer: a signature
    // keyed on object identity would repaint forty faces per poll.
    const roster = [entry('seat-0', 0), entry('seat-1', 1)]
    const owners = { '1': 'seat-0', '3': 'seat-1' }

    const before = ownerSignature(ownedCells(match(owners, roster)))
    const after = ownerSignature(ownedCells(match({ ...owners }, roster)))

    expect(after).toBe(before)
  })

  it('changes when a space is bought and when it changes hands', () => {
    const roster = [entry('seat-0', 0), entry('seat-1', 1)]
    const signatures = [
      ownerSignature(ownedCells(match({}, roster))),
      ownerSignature(ownedCells(match({ '1': 'seat-0' }, roster))),
      ownerSignature(ownedCells(match({ '1': 'seat-1' }, roster))),
    ]

    expect(new Set(signatures).size).toBe(3)
  })
})
