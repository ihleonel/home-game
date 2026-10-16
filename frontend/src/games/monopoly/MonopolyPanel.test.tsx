import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { MatchSeatRosterEntry } from '../matchRoster'
import type { MatchState } from '../registry'
import { MonopolyPanel, MonopolyPanelLayout } from './MonopolyPanel'
import type { MonopolyAction, MonopolyPlayer, MonopolyView } from './view'

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
    players: [player({ seat: 'seat-0' }), player({ seat: 'seat-1', cash: 1200, position: 5 })],
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
    actions: [],
    you: 'seat-0',
    ...overrides,
  }
}

function matchFor(rawView: MonopolyView): MatchState<MonopolyView> {
  return { matchRef: 'match-1', seatIndex: 0, version: 3, roster, view: rawView }
}

type LayoutProps = Parameters<typeof MonopolyPanelLayout>[0]

function layoutProps(
  rawView: MonopolyView,
  options: {
    busy?: boolean
    onAction?: (name: string, value: string | null) => void
  } = {},
): LayoutProps {
  return {
    match: matchFor(rawView),
    busy: options.busy ?? false,
    onAction: options.onAction ?? (() => {}),
    selected: null,
    onSelect: () => {},
  }
}

/**
 * Collect the rendered host elements of a component tree.
 *
 * The panel's stateful wrapper cannot be invoked directly (it calls
 * ``useState``), so the click tests go through the pure layout it renders. The
 * walk is the same one the other game suites use: expand function components by
 * calling them, record host elements as-is.
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

function panelMarkup(
  rawView: MonopolyView,
  options: { busy?: boolean } = {},
): string {
  return renderToStaticMarkup(<MonopolyPanelLayout {...layoutProps(rawView, options)} />)
}

function actionButtons(
  rawView: MonopolyView,
  options: {
    busy?: boolean
    onAction?: (name: string, value: string | null) => void
  } = {},
): ReactElement[] {
  const tree = MonopolyPanelLayout(layoutProps(rawView, options))
  return hostElements(tree).filter((element) => {
    if (element.type !== 'button') return false
    const className = (element.props as { className?: string }).className ?? ''
    return className.includes('monopoly-action')
  })
}

function textOf(button: ReactElement): string {
  const children = (button.props as { children?: ReactNode }).children
  return typeof children === 'string' ? children : ''
}

function buttonWithLabel(buttons: ReactElement[], label: string): ReactElement {
  const button = buttons.find((element) => textOf(element) === label)
  if (!button) throw new Error(`no action button labelled ${label}`)
  return button
}

describe('the monopoly player panel', () => {
  it('renders every offered action with the server prompt as its label', () => {
    const actions: MonopolyAction[] = [
      { name: 'roll', prompt: 'Tirá los dados', options: [] },
      { name: 'end_turn', prompt: 'Terminá el turno', options: [] },
    ]
    const page = panelMarkup(view({ actions }))

    expect(page).toContain('Tirá los dados')
    expect(page).toContain('Terminá el turno')
    expect(actionButtons(view({ actions }))).toHaveLength(2)
  })

  it('submits an offered action without a value as null', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [{ name: 'roll', prompt: 'Tirá los dados', options: [] }]
    const button = buttonWithLabel(actionButtons(view({ actions }), { onAction }), 'Tirá los dados')

    ;(button.props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onAction).toHaveBeenCalledWith('roll', null)
  })

  it('renders one button per option and submits the option the server offered', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [
      {
        name: 'pay_income_tax',
        prompt: 'Elegí cómo pagar',
        options: ['fixed', 'percent'],
      },
    ]
    const buttons = actionButtons(view({ actions }), { onAction })

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Elegí cómo pagar: fixed')
    expect(textOf(buttons[1])).toBe('Elegí cómo pagar: percent')

    ;(buttons[1].props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('pay_income_tax', 'percent')
  })

  it('renders no action button when the server offered none', () => {
    const page = panelMarkup(view())
    const away = view({ you: undefined })

    expect(actionButtons(view())).toHaveLength(0)
    expect(actionButtons(away)).toHaveLength(0)
    expect(page).not.toContain('monopoly-actions-block')
  })

  it('disables every action button while the match is busy', () => {
    const actions: MonopolyAction[] = [
      { name: 'roll', prompt: 'Tirá los dados', options: [] },
      { name: 'pay_income_tax', prompt: 'Elegí cómo pagar', options: ['fixed', 'percent'] },
    ]
    const buttons = actionButtons(view({ actions }), { busy: true })

    expect(buttons).toHaveLength(3)
    expect(
      buttons.every((button) => (button.props as { disabled?: boolean }).disabled === true),
    ).toBe(true)
  })

  it('shows the own seat capital and position', () => {
    const page = panelMarkup(view())

    expect(page).toContain('monopoly-own-cash">$1.500<')
    expect(page).toContain('monopoly-own-position">GO<')
  })

  it('shows how many jail cards the own seat holds', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', jail_cards: 2 }), player({ seat: 'seat-1' })],
    })
    const page = panelMarkup(seated)

    expect(page).toContain('Cartas de «Salí de la cárcel gratis»')
    expect(page).toContain('monopoly-own-jail-cards">2<')
  })

  it('shows the cards left in each deck when the server reports them', () => {
    const page = panelMarkup(view({ decks: { chance: 14, community_chest: 9 } }))

    expect(page).toContain('monopoly-deck-count">14<')
    expect(page).toContain('monopoly-deck-count">9<')
  })

  it('shows no deck count when the view carries no deck information', () => {
    expect(panelMarkup(view({ decks: null }))).not.toContain('monopoly-deck-count')
  })

  it('shows the auction space, the high bid, its holder and who is still to bid', () => {
    const page = panelMarkup(
      view({
        auction: { space: 3, high_bid: 70, high_bidder: 'seat-1', waiting_for: ['seat-0'] },
      }),
    )

    expect(page).toContain('monopoly-auction-space">Avenida Báltica<')
    expect(page).toContain('monopoly-auction-bid">$70<')
    expect(page).toContain('monopoly-auction-bidder">Beto<')
    expect(page).toContain('Esperando la puja de Ana.')
  })

  it('says there are no bids yet when nobody has bid', () => {
    const page = panelMarkup(
      view({
        auction: { space: 3, high_bid: 0, high_bidder: null, waiting_for: ['seat-0', 'seat-1'] },
      }),
    )

    expect(page).toContain('Todavía no hay pujas.')
    expect(page).not.toContain('monopoly-auction-bidder')
  })

  it('shows the bidder as the viewer when it is the viewer own seat', () => {
    const page = panelMarkup(
      view({
        auction: { space: 3, high_bid: 70, high_bidder: 'seat-0', waiting_for: ['seat-1'] },
      }),
    )

    expect(page).toContain('monopoly-auction-bidder">Ana (tú)<')
  })

  it('renders no auction block when there is no auction', () => {
    const page = panelMarkup(view({ auction: null }))

    expect(page).not.toContain('monopoly-auction')
    expect(page).not.toContain('Subasta')
  })

  it('renders the server bid options and the pass without adding an auction control', () => {
    const actions: MonopolyAction[] = [
      { name: 'bid', prompt: 'Pujá', options: ['10', '20', '50'] },
      { name: 'pass', prompt: 'Pasá la subasta.', options: [] },
    ]
    const open = view({
      auction: { space: 3, high_bid: 0, high_bidder: null, waiting_for: ['seat-0', 'seat-1'] },
      actions,
    })
    const buttons = actionButtons(open)

    expect(buttons).toHaveLength(4)
    expect(textOf(buttonWithLabel(buttons, 'Pujá: 10'))).toBe('Pujá: 10')
    expect(textOf(buttonWithLabel(buttons, 'Pujá: 20'))).toBe('Pujá: 20')
    expect(textOf(buttonWithLabel(buttons, 'Pujá: 50'))).toBe('Pujá: 50')
    expect(textOf(buttonWithLabel(buttons, 'Pasá la subasta.'))).toBe('Pasá la subasta.')
  })

  it('draws a build option as the space name and the price of one more level', () => {
    const actions: MonopolyAction[] = [
      { name: 'build', prompt: 'Construí', options: ['1', '3'] },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Construí en Avenida Mediterráneo · $50')
    expect(textOf(buttons[1])).toBe('Construí en Avenida Báltica · $50')
  })

  it('draws a sell option as the space name and half the house cost', () => {
    const actions: MonopolyAction[] = [
      { name: 'sell', prompt: 'Vendé', options: ['11', '39'] },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Vendé en St. Charles Place · +$50')
    expect(textOf(buttons[1])).toBe('Vendé en Boardwalk · +$100')
  })

  it('prices a build from the level the property already has', () => {
    // One more level costs one house cost whichever side of the hotel line it
    // is on; the label never becomes the property's total development value.
    const actions: MonopolyAction[] = [{ name: 'build', prompt: 'Construí', options: ['1'] }]
    const built = view({ actions, buildings: { '1': 4 } })

    expect(textOf(actionButtons(built)[0])).toBe('Construí en Avenida Mediterráneo · $50')
  })

  it('submits the board index the server offered for build and sell', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [
      { name: 'build', prompt: 'Construí', options: ['1'] },
      { name: 'sell', prompt: 'Vendé', options: ['3'] },
    ]
    const buttons = actionButtons(view({ actions }), { onAction })

    ;(buttons[0].props as { onClick: () => void }).onClick()
    ;(buttons[1].props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('build', '1')
    expect(onAction).toHaveBeenCalledWith('sell', '3')
  })

  it('falls back to the raw option when a build option is not a board index', () => {
    const actions: MonopolyAction[] = [{ name: 'build', prompt: 'Construí', options: ['nope'] }]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(1)
    expect(textOf(buttons[0])).toBe('Construí: nope')
  })

  it('draws a mortgage option as the space name and the cash it raises', () => {
    const actions: MonopolyAction[] = [
      { name: 'mortgage', prompt: 'Hipotecá', options: ['1', '5'] },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Hipotecá en Avenida Mediterráneo · +$30')
    expect(textOf(buttons[1])).toBe('Hipotecá en Ferrocarril Reading · +$100')
  })

  it('draws an unmortgage option as the space name and the cash it costs', () => {
    const actions: MonopolyAction[] = [
      { name: 'unmortgage', prompt: 'Levantá la hipoteca', options: ['37', '39'] },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Levantá la hipoteca en Park Place · −$193')
    expect(textOf(buttons[1])).toBe('Levantá la hipoteca en Boardwalk · −$220')
  })

  it('submits the board index the server offered for mortgage and unmortgage', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [
      { name: 'mortgage', prompt: 'Hipotecá', options: ['1'] },
      { name: 'unmortgage', prompt: 'Levantá la hipoteca', options: ['39'] },
    ]
    const buttons = actionButtons(view({ actions }), { onAction })

    ;(buttons[0].props as { onClick: () => void }).onClick()
    ;(buttons[1].props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('mortgage', '1')
    expect(onAction).toHaveBeenCalledWith('unmortgage', '39')
  })

  it('falls back to the raw option when a mortgage option is not a purchasable index', () => {
    const actions: MonopolyAction[] = [
      { name: 'mortgage', prompt: 'Hipotecá', options: ['nope', '2'] },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(textOf(buttons[0])).toBe('Hipotecá: nope')
    expect(textOf(buttons[1])).toBe('Hipotecá: 2')
  })

  it('shows the development level of each built own property', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1, 3, 6] }), player({ seat: 'seat-1' })],
      buildings: { '1': 2, '3': 5 },
    })
    const page = panelMarkup(seated)

    expect(page).toContain('2 casas')
    expect(page).toContain('Hotel')
    // Only the two built properties get a level; the third stays bare.
    expect(page.match(/monopoly-property-level/g)).toHaveLength(2)
  })

  it('shows a mortgaged badge on a mortgaged own property', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1, 3] }), player({ seat: 'seat-1' })],
      mortgaged: { '1': true },
    })
    const page = panelMarkup(seated)

    expect(page).toContain('monopoly-property-mortgaged')
    expect(page).toContain('Hipotecada')
    // Only the mortgaged property wears the badge; its sister stays bare.
    expect(page.match(/monopoly-property-mortgaged/g)).toHaveLength(1)
  })

  it('shows the open debt with the amount and the player creditor', () => {
    const raising = view({
      phase: 'raising_cash',
      debt: { seat: 'seat-0', creditor: 'seat-1', amount: 420 },
    })
    const page = panelMarkup(raising)

    expect(page).toContain('monopoly-debt')
    // The creditor reads as its display name, the way the auction and the
    // roster already name every seat, never as a raw seat id.
    expect(page).toContain('Deuda: $420 con Beto')
  })

  it('shows a debt to the bank as owing the bank', () => {
    const raising = view({
      phase: 'raising_cash',
      debt: { seat: 'seat-0', creditor: null, amount: 50 },
    })

    expect(panelMarkup(raising)).toContain('Deuda: $50 con el banco')
  })

  it('shows no debt block outside the raising cash phase', () => {
    const owed = view({ debt: { seat: 'seat-0', creditor: null, amount: 50 } })

    expect(panelMarkup(owed)).not.toContain('monopoly-debt')
  })

  it('shows no debt block when the raising cash phase carries no debt record', () => {
    expect(panelMarkup(view({ phase: 'raising_cash', debt: null }))).not.toContain('monopoly-debt')
  })

  it('places the debt block above the actions so the pay button has context', () => {
    const raising = view({
      phase: 'raising_cash',
      debt: { seat: 'seat-0', creditor: null, amount: 50 },
      actions: [{ name: 'pay_debt', prompt: 'Pagá la deuda', options: [] }],
    })
    const page = panelMarkup(raising)

    expect(page.indexOf('monopoly-debt')).toBeGreaterThan(-1)
    expect(page.indexOf('monopoly-debt')).toBeLessThan(page.indexOf('monopoly-actions-block'))
  })

  it('shows the bank block with the houses and hotels left in the box', () => {
    const page = panelMarkup(view({ bank: { houses: 29, hotels: 12 } }))

    expect(page).toContain('monopoly-bank')
    expect(page).toContain('monopoly-bank-houses">29<')
    expect(page).toContain('monopoly-bank-hotels">12<')
  })

  it('omits the bank block when the view carries no bank', () => {
    const page = panelMarkup(view({ bank: null }))

    expect(page).not.toContain('monopoly-bank')
    expect(page).not.toContain('>Banco<')
  })

  it('groups the own properties by colour with their printed data', () => {
    const seated = view({
      players: [
        player({ seat: 'seat-0', properties: [1, 3] }),
        player({ seat: 'seat-1' }),
      ],
    })
    const page = panelMarkup(seated)

    expect(page).toMatch(/monopoly-property-group-title[^>]*>Marrón</)
    expect(page).toContain('Avenida Mediterráneo')
    expect(page).toContain('Avenida Báltica')
    expect(page).toContain('Rentas impresas')
  })

  it('lists every seat with its roster name and the own-seat suffix', () => {
    const page = panelMarkup(view())

    expect(page).toContain('monopoly-player-name">Ana (tú)<')
    expect(page).toContain('monopoly-player-name">Beto<')
  })

  it('says the viewer is a spectator when the view carries no seat', () => {
    const page = panelMarkup(view({ you: undefined }))

    expect(page).toContain('Estás como espectador.')
    expect(page).not.toContain('monopoly-own-cash')
  })

  it('shows the winner line for a normal finish and nothing for an abandonment', () => {
    const won = view({ finished: true, winner: 'seat-1' })
    const abandoned = view({ finished: true, winner: 'seat-1', ended_by_abandon: true })

    expect(panelMarkup(won)).toContain('Ha ganado Beto.')
    expect(panelMarkup(abandoned)).not.toContain('Ha ganado Beto.')
  })

  it('renders the layout through its stateful wrapper', () => {
    const page = renderToStaticMarkup(
      <MonopolyPanel
        match={matchFor(view())}
        busy={false}
        onAction={() => {}}
        onPick={() => {}}
      />,
    )

    expect(page).toContain('monopoly-board')
    expect(page).toContain('Tu situación')
  })
})
