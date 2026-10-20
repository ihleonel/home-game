import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { MatchSeatRosterEntry } from '../matchRoster'
import type { MatchState } from '../registry'
import { spaceArea, spaceSide } from './grid'
import { MonopolyBoard } from './MonopolyBoard'
import { MonopolyTableCentre } from './MonopolyTableCentre'
import type { QuarterTurns } from './viewport'
import type { MonopolyPlayer, MonopolyView } from './view'

const roster: MatchSeatRosterEntry[] = [
  {
    seat_id: 'seat-0',
    index: 0,
    display_name: 'Ana',
    game_marker: 'sombrero',
    game_marker_label: 'Sombrero',
  },
  {
    seat_id: 'seat-1',
    index: 1,
    display_name: 'Beto',
    game_marker: 'perro',
    game_marker_label: 'Perro',
  },
]

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
    players: [player({ seat: 'seat-0' }), player({ seat: 'seat-1' })],
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

function matchFor(rawView: MonopolyView): MatchState<MonopolyView> {
  return { matchRef: 'match-1', seatIndex: 0, version: 3, roster, view: rawView }
}

/**
 * Collect the rendered host elements of a component tree.
 *
 * The tests run against `react-dom/server` with no DOM, so a click is verified
 * by walking the element tree the board returns and invoking the handler React
 * would have attached. The board is a pure function of its props, so it can be
 * invoked directly; its inline helpers return host elements and no nested
 * component hides a button from this walk.
 */
function hostElements(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    for (const child of node) hostElements(child, found)
    return found
  }
  if (!isValidElement(node)) return found
  const component = node.type
  if (typeof component === 'function') {
    const rendered = (component as (p: unknown) => ReactElement)(node.props)
    hostElements(rendered, found)
    return found
  }
  found.push(node)
  const elementProps = node.props as { children?: ReactNode }
  hostElements(elementProps.children, found)
  return found
}

/**
 * The seat-view props of the board (S13): all optional, so a test that passes
 * none of them renders the printed board of today.
 */
type SeatViewProps = {
  turns?: QuarterTurns
  centre?: 'board' | 'none'
  onFocus?: (index: number) => void
}

function boardElement(
  rawView: MonopolyView,
  selected: number | null,
  onSelect: (index: number) => void,
  extra: SeatViewProps,
): ReactElement {
  return MonopolyBoard({ match: matchFor(rawView), selected, onSelect, ...extra })
}

function buttonElements(
  rawView: MonopolyView,
  selected: number | null = null,
  onSelect: (index: number) => void = () => {},
  extra: SeatViewProps = {},
): ReactElement[] {
  const tree = boardElement(rawView, selected, onSelect, extra)
  return hostElements(tree).filter((element) => element.type === 'button')
}

function markup(
  rawView: MonopolyView,
  selected: number | null = null,
  extra: SeatViewProps = {},
): string {
  return renderToStaticMarkup(boardElement(rawView, selected, () => {}, extra))
}

/** The static markup of one rendered host element, so a test can pin its contents. */
function elementMarkup(element: ReactElement): string {
  return renderToStaticMarkup(element)
}

function labelOf(button: ReactElement): string {
  return (button.props as { 'aria-label'?: string })['aria-label'] ?? ''
}

/** The grid cell a space button was placed in. */
function placementOf(button: ReactElement): { row: number; column: number } {
  const style = (button.props as { style: { gridRow: number; gridColumn: number } }).style
  return { row: style.gridRow, column: style.gridColumn }
}

/** The side of the ring a space button reports to the stylesheet. */
function sideOf(button: ReactElement): string {
  return (button.props as Record<string, string>)['data-side']
}

/** The space button whose accessible name starts with ``name``. */
function spaceButton(buttons: ReactElement[], name: string): ReactElement {
  const button = buttons.find((element) => labelOf(element).startsWith(name))
  if (!button) throw new Error(`no space button for ${name}`)
  return button
}

describe('the monopoly board', () => {
  it('tells the stylesheet which side of the ring each space is on', () => {
    // Ten spaces per side, corners included in the edge they open: this is the
    // hook the skin uses to face the colour band inward and rotate the names.
    const page = markup(view())

    for (const side of ['bottom', 'left', 'top', 'right']) {
      expect(page.match(new RegExp(`data-side="${side}"`, 'g'))).toHaveLength(10)
    }
  })
  it('renders one button per board space', () => {
    expect(buttonElements(view())).toHaveLength(40)
  })

  it('names a purchasable space with its kind and its printed price', () => {
    const label = labelOf(spaceButton(buttonElements(view()), 'Avenida Mediterráneo'))

    expect(label).toContain('Calle')
    expect(label).toContain('Precio $60')
  })

  it('names the owner of an owned space and falls back to Jugador for an unknown seat', () => {
    const owned = view({ owners: { '1': 'seat-0', '3': 'seat-9' } })
    const buttons = buttonElements(owned)

    expect(labelOf(spaceButton(buttons, 'Avenida Mediterráneo'))).toContain('Dueño Ana')
    expect(labelOf(spaceButton(buttons, 'Avenida Báltica'))).toContain('Dueño Jugador')
    expect(markup(owned)).toMatch(/monopoly-space-owner[^>]*>Jugador</)
  })

  it('draws one token per seat still in the match and none for an eliminated seat', () => {
    const drawn = view({
      players: [
        player({ seat: 'seat-0', position: 5 }),
        player({ seat: 'seat-1', position: 5, eliminated: true }),
      ],
    })
    const page = markup(drawn)

    expect(page.match(/monopoly-token-initial/g)).toHaveLength(1)
    expect(page).toContain('>A</span>')
    expect(page).not.toContain('>B</span>')
  })

  it('marks the viewer token and leaves a jailed seat visibly marked', () => {
    const drawn = view({
      players: [
        player({ seat: 'seat-0', position: 5 }),
        player({ seat: 'seat-1', position: 10, in_jail: true, jail_turns: 1 }),
      ],
    })
    const page = markup(drawn)

    expect(page).toContain('monopoly-token-you')
    expect(page).toContain('(tú)')
    expect(page).toContain('En la cárcel')
    expect(page).toContain('monopoly-token-jailed')
  })

  it('renders the last throw and the turn', () => {
    const page = markup(view({ last_roll: [3, 5] }))

    expect(page).toContain('Turno de Ana')
    expect(page).toContain('Última tirada: 3 y 5')
  })

  it('renders the drawn card with its deck in Spanish and the copy verbatim', () => {
    const page = markup(
      view({
        last_card: {
          deck: 'chance',
          id: 'chance-01',
          title: 'Avanzá hasta Boardwalk.',
        },
      }),
    )

    expect(page).toContain('monopoly-card')
    expect(page).toContain('Suerte: Avanzá hasta Boardwalk.')
    expect(page).toContain('Avanzá hasta Boardwalk.')
  })

  it('names the community chest deck in Spanish', () => {
    const page = markup(
      view({
        last_card: {
          deck: 'community_chest',
          id: 'community_chest-02',
          title: 'Error bancario a tu favor: cobrá $200.',
        },
      }),
    )

    expect(page).toContain('Caja de comunidad: Error bancario a tu favor: cobrá $200.')
  })

  it('renders no drawn card once nothing has been turned up', () => {
    expect(markup(view({ last_card: null }))).not.toContain('monopoly-card')
  })

  it('marks the space under auction with a class, an attribute and an accessible name', () => {
    const auctioned = view({
      auction: { space: 3, high_bid: 0, high_bidder: null, waiting_for: [] },
    })
    const buttons = buttonElements(auctioned)
    const button = spaceButton(buttons, 'Avenida Báltica')

    expect((button.props as { className: string }).className).toContain('monopoly-space-auction')
    expect((button.props as Record<string, unknown>)['data-auction']).toBe('true')
    expect(labelOf(button)).toContain('En subasta')
    expect(
      (spaceButton(buttons, 'Avenida Mediterráneo').props as Record<string, unknown>)[
        'data-auction'
      ],
    ).toBeUndefined()
  })

  it('names the space under auction in the centre', () => {
    const page = markup(
      view({
        auction: { space: 3, high_bid: 70, high_bidder: 'seat-1', waiting_for: ['seat-0'] },
      }),
    )

    expect(page).toContain('monopoly-auction')
    expect(page).toContain('Subasta de Avenida Báltica')
  })

  it('renders no auction mark or line when there is no auction', () => {
    const page = markup(view({ auction: null }))

    expect(page).not.toContain('monopoly-space-auction')
    expect(page).not.toContain('data-auction')
    expect(page).not.toContain('Subasta de')
  })

  it('marks a mortgaged space with a class, an attribute and an accessible name', () => {
    const mortgaged = view({ mortgaged: { '1': true, '39': true } })
    const buttons = buttonElements(mortgaged)
    const button = spaceButton(buttons, 'Avenida Mediterráneo')

    expect((button.props as { className: string }).className).toContain('monopoly-space-mortgaged')
    expect((button.props as Record<string, unknown>)['data-mortgaged']).toBe('true')
    expect(labelOf(button)).toContain('Hipotecada')
    expect(
      (spaceButton(buttons, 'Avenida Báltica').props as Record<string, unknown>)[
        'data-mortgaged'
      ],
    ).toBeUndefined()
  })

  it('keeps the printed price in a mortgaged space so the stylesheet can strike it', () => {
    // The strike-through is pure CSS: the markup hook is the mortgaged class on
    // the button, and the price element is still there for the rule to reach.
    const mortgaged = view({ mortgaged: { '39': true } })

    expect(elementMarkup(spaceButton(buttonElements(mortgaged), 'Boardwalk'))).toMatch(
      /monopoly-space-price[^>]*>\$400</,
    )
  })

  it('marks a band-less mortgaged space so the stripe has a surface', () => {
    // A railroad and a utility have no colour band in this skin, so the
    // stylesheet lays the stripe on the cell's own band strip. The hook it
    // selects on is the missing data-group, which is exactly what only a
    // band-less purchasable space lacks.
    const mortgaged = view({ mortgaged: { '5': true, '12': true } })
    const buttons = buttonElements(mortgaged)

    for (const name of ['Ferrocarril Reading', 'Compañía Eléctrica']) {
      const button = spaceButton(buttons, name)
      expect((button.props as Record<string, unknown>)['data-mortgaged']).toBe('true')
      expect((button.props as Record<string, unknown>)['data-group']).toBeUndefined()
      expect((button.props as { className: string }).className).toContain(
        'monopoly-space-mortgaged',
      )
    }
  })

  it('shows the mortgage value and the lift cost in the selected space detail', () => {
    const mortgaged = view({ mortgaged: { '39': true } })
    const selected = markup(mortgaged, 39)

    expect(selected).toContain('monopoly-detail-mortgaged')
    expect(selected).toContain('Hipotecada')
    expect(selected).toContain('$200')
    expect(selected).toContain('$220')
  })

  it('adds no mortgage detail to an unmortgaged space', () => {
    const mortgaged = view({ mortgaged: { '39': true } })

    expect(markup(mortgaged, 37)).not.toContain('monopoly-detail-mortgaged')
    expect(markup(view(), 39)).not.toContain('monopoly-detail-mortgaged')
  })

  it('shows the selected space detail with its printed rents and nothing when nothing is selected', () => {
    const selected = markup(view(), 1)

    expect(selected).toContain('monopoly-detail')
    expect(selected).toContain('Renta base')
    expect(selected).toContain('$2')
    expect(selected).toContain('Marrón')
    expect(selected).toContain('Dueño: Sin dueño')

    expect(markup(view(), null)).not.toContain('monopoly-detail')
  })

  it('announces the selected space with aria-pressed', () => {
    const pressed = buttonElements(view(), 1).filter(
      (button) => (button.props as { 'aria-pressed'?: boolean })['aria-pressed'] === true,
    )

    expect(pressed).toHaveLength(1)
    expect(labelOf(pressed[0])).toContain('Avenida Mediterráneo')
  })

  it('prints the purchase price on a purchasable space and none on a non-purchasable one', () => {
    // The printed board carries the price under every street name (S4); a
    // corner, a tax or a card space is not for sale and prints no price.
    const buttons = buttonElements(view())

    expect(elementMarkup(spaceButton(buttons, 'Avenida Mediterráneo'))).toMatch(
      /monopoly-space-price[^>]*>\$60</,
    )
    expect(elementMarkup(spaceButton(buttons, 'GO'))).not.toContain('monopoly-space-price')
    expect(elementMarkup(spaceButton(buttons, 'Chance'))).not.toContain('monopoly-space-price')
  })

  it('paints a built street as houses or a hotel and leaves an unbuilt one bare', () => {
    const built = view({ buildings: { '1': 3, '3': 5 } })
    const buttons = buttonElements(built)

    const mediterraneo = elementMarkup(spaceButton(buttons, 'Avenida Mediterráneo'))
    const baltica = elementMarkup(spaceButton(buttons, 'Avenida Báltica'))
    const oriental = elementMarkup(spaceButton(buttons, 'Avenida Oriental'))

    expect(mediterraneo).toContain('monopoly-space-buildings')
    expect(mediterraneo.match(/monopoly-space-house/g)).toHaveLength(3)
    expect(mediterraneo).not.toContain('monopoly-space-hotel')
    expect(baltica).toContain('monopoly-space-buildings')
    expect(baltica).toContain('monopoly-space-hotel')
    expect(baltica.match(/monopoly-space-house/g)).toBeNull()
    expect(oriental).not.toContain('monopoly-space-buildings')
  })

  it('announces the development level in the accessible name', () => {
    const built = view({ buildings: { '1': 1, '6': 2, '39': 5 } })
    const buttons = buttonElements(built)

    expect(labelOf(spaceButton(buttons, 'Avenida Mediterráneo'))).toContain('1 casa')
    expect(labelOf(spaceButton(buttons, 'Avenida Oriental'))).toContain('2 casas')
    expect(labelOf(spaceButton(buttons, 'Boardwalk'))).toContain('Hotel')
    // An unbuilt space announces no level at all.
    expect(labelOf(spaceButton(buttons, 'Avenida Báltica'))).not.toMatch(/casa|Hotel/)
  })

  it('adds the buildings line to the selected space detail and none for an unbuilt space', () => {
    const built = view({ buildings: { '1': 2 } })

    const selected = markup(built, 1)

    expect(selected).toContain('monopoly-detail-buildings')
    expect(selected).toContain('Edificios: 2 casas')
    expect(markup(built, 3)).not.toContain('monopoly-detail-buildings')
  })

  it('reads the level only from the view and never derives it from the owner map', () => {
    // The whole brown group is owned, so a client that derived development from
    // ownership would paint something; without ``buildings`` there is none.
    const owned = view({ owners: { '1': 'seat-0', '3': 'seat-0' } })

    expect(markup(owned)).not.toContain('monopoly-space-buildings')
  })

  it('keeps the group initials, the owner badge and the tokens as accessible markup', () => {
    // Colour is never the only cue (S9): the skin may make these discreet, but
    // the markup still carries the two-letter group, the owner's name and the
    // seat tokens next to the name and the price.
    const withOwner = view({
      owners: { '1': 'seat-0' },
      players: [
        player({ seat: 'seat-0', position: 1 }),
        player({ seat: 'seat-1', position: 1, eliminated: true }),
      ],
    })
    const page = markup(withOwner)

    expect(page).toMatch(/monopoly-space-group[^>]*>MA</)
    expect(page).toMatch(/monopoly-space-owner[^>]*>Ana</)
    expect(page).toContain('monopoly-space-tokens')
    expect(page.match(/monopoly-token-initial/g)).toHaveLength(1)
  })

  it('keeps every corner name in the markup', () => {
    // The corners get CSS character (S5); their names stay legible and the
    // accessible name keeps reading them.
    const page = markup(view())

    expect(page).toContain('>GO<')
    expect(page).toContain('Cárcel / Solo visitando')
    expect(page).toContain('Free Parking')
    expect(page).toContain('Go to Jail')
  })

  it('shows the game name band and the two deck piles in the centre', () => {
    const page = markup(view({ decks: { chance: 14, community_chest: 9 } }))

    expect(page).toMatch(/monopoly-brand-name[^>]*>Monopoly</)
    expect(page).toContain('monopoly-centre-band')
    expect(page).toContain('monopoly-pile-count">14<')
    expect(page).toContain('monopoly-pile-count">9<')
  })

  it('shows no deck pile markup when the view reports no deck counts', () => {
    expect(markup(view({ decks: null }))).not.toContain('monopoly-pile')
  })

  it('reports a tap with the space index and never calls an action', () => {
    const onSelect = vi.fn()
    const buttons = buttonElements(view(), null, onSelect)

    ;(spaceButton(buttons, 'Avenida Báltica').props as { onClick: () => void }).onClick()

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(3)
  })

  it('renders the same board for a spectator with no seat and no actions', () => {
    const spectator = view({ you: undefined })
    const page = markup(spectator)

    expect(buttonElements(spectator)).toHaveLength(40)
    expect(page.match(/monopoly-token-initial/g)).toHaveLength(2)
  })
})

describe('the board seen from a seat', () => {
  it('renders the printed board, centre included, when no seat view is passed', () => {
    const printed = view()
    const buttons = buttonElements(printed)
    const page = markup(printed)

    expect(buttons).toHaveLength(40)
    expect(placementOf(spaceButton(buttons, 'GO'))).toEqual({ row: 11, column: 11 })
    expect(placementOf(spaceButton(buttons, 'Avenida Mediterráneo'))).toEqual({
      row: 11,
      column: 10,
    })
    expect(sideOf(spaceButton(buttons, 'GO'))).toBe('bottom')
    // S13: with no props every one of the forty cells keeps the printed
    // geometry -- the buttons are emitted in circuit order, like BOARD.
    buttons.forEach((button, index) => {
      expect([index, placementOf(button)]).toEqual([index, spaceArea(index)])
      expect([index, sideOf(button)]).toEqual([index, spaceSide(index)])
    })
    expect(page).toContain('class="monopoly-centre"')
    expect(page).toContain('monopoly-brand-name')
    expect(page).not.toContain('monopoly-centre-empty')
  })

  it('moves GO to the bottom-left on a quarter turn and turns its band side with it', () => {
    // S4: the turn is a shift of the circuit, so the cell and the side of the
    // ring travel together and the band keeps facing the centre.
    const buttons = buttonElements(view(), null, () => {}, { turns: 1 })
    const page = markup(view(), null, { turns: 1 })

    expect(placementOf(spaceButton(buttons, 'GO'))).toEqual({ row: 11, column: 1 })
    expect(sideOf(spaceButton(buttons, 'GO'))).toBe('left')
    expect(sideOf(spaceButton(buttons, 'Avenida Mediterráneo'))).toBe('left')
    expect(page.match(/data-side="left"/g)).toHaveLength(10)
    // A re-indexing rotates nothing: no label ever ends up sideways.
    expect(page.toLowerCase()).not.toContain('transform')
    expect(page.toLowerCase()).not.toContain('rotate')
  })

  it('keeps all forty spaces on the perimeter in distinct cells at every turn', () => {
    let previous: string[] = []
    for (const turns of [0, 1, 2, 3] as const) {
      const buttons = buttonElements(view(), null, () => {}, { turns })
      expect(buttons).toHaveLength(40)
      const cells = buttons.map((button) => {
        const { row, column } = placementOf(button)
        const onPerimeter = row === 1 || row === 11 || column === 1 || column === 11
        // The 9x9 middle is the centre of the table, never a space (S10).
        expect([turns, row, column, onPerimeter]).toEqual([turns, row, column, true])
        return `${row}:${column}`
      })
      expect([turns, new Set(cells).size]).toEqual([turns, 40])
      expect(cells).not.toEqual(previous)
      previous = cells
    }
  })

  it('empties the middle of the board when the seat view asks for no centre', () => {
    const drawn = view({
      decks: { chance: 14, community_chest: 9 },
      last_roll: [3, 5],
      last_card: { deck: 'chance', id: 'chance-01', title: 'Avanzá hasta Boardwalk.' },
      auction: { space: 3, high_bid: 70, high_bidder: 'seat-1', waiting_for: ['seat-0'] },
    })
    const page = markup(drawn, 1, { centre: 'none' })

    expect(buttonElements(drawn, 1, () => {}, { centre: 'none' })).toHaveLength(40)
    for (const element of [
      'monopoly-brand-name',
      'monopoly-piles',
      'monopoly-turn',
      'monopoly-roll',
      'monopoly-card',
      'monopoly-auction-line',
      'monopoly-detail',
    ]) {
      expect([element, page.includes(element)]).toEqual([element, false])
    }
    expect(page).not.toContain('Turno de Ana')
    expect(page).toContain('class="monopoly-centre monopoly-centre-empty"')
  })

  it('reports the index of every space that takes focus and never calls it on a tap', () => {
    const onFocus = vi.fn()
    const onSelect = vi.fn()
    const buttons = buttonElements(view(), null, onSelect, { onFocus })

    for (const button of buttons) {
      expect(typeof (button.props as { onFocus?: unknown }).onFocus).toBe('function')
    }

    const baltica = spaceButton(buttons, 'Avenida Báltica')
    ;(baltica.props as { onFocus: () => void }).onFocus()

    expect(onFocus).toHaveBeenCalledTimes(1)
    expect(onFocus).toHaveBeenCalledWith(3)

    ;(baltica.props as { onClick: () => void }).onClick()

    expect(onSelect).toHaveBeenCalledWith(3)
    expect(onFocus).toHaveBeenCalledTimes(1)
  })

  it('renders the brand, the turn and the selected detail on its own', () => {
    // S10: one source for the two placements, so the strip under the window can
    // hold exactly the block the whole board holds in its 9x9.
    const page = renderToStaticMarkup(
      <MonopolyTableCentre
        match={matchFor(view({ decks: { chance: 14, community_chest: 9 } }))}
        selected={1}
      />,
    )

    expect(page).toMatch(/monopoly-brand-name[^>]*>Monopoly</)
    expect(page).toContain('monopoly-pile-count">14<')
    expect(page).toContain('Turno de Ana')
    expect(page).toContain('monopoly-detail')
    expect(page).toContain('Avenida Mediterráneo')
  })
})
