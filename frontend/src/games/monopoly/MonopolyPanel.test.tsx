import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { MatchSeatRosterEntry } from '../matchRoster'
import type { MatchState } from '../registry'
import { MonopolyPanel, MonopolyPanelLayout } from './MonopolyPanel'
import type { MonopolyTradeDraft } from './MonopolyPanel'
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
    offers: [],
    actions: [],
    you: 'seat-0',
    ...overrides,
  }
}

function matchFor(rawView: MonopolyView): MatchState<MonopolyView> {
  return { matchRef: 'match-1', seatIndex: 0, version: 3, roster, view: rawView }
}

type LayoutProps = Parameters<typeof MonopolyPanelLayout>[0]

/** The draft the negotiation block composes (S11), empty by default. */
function tradeDraft(overrides: Partial<MonopolyTradeDraft> = {}): MonopolyTradeDraft {
  return { receiver: null, give: [], want: [], giveCash: 0, wantCash: 0, ...overrides }
}

type LayoutOptions = {
  busy?: boolean
  onAction?: (name: string, value: string | null) => void
  trade?: MonopolyTradeDraft
  onTradeChange?: (next: MonopolyTradeDraft) => void
}

function layoutProps(rawView: MonopolyView, options: LayoutOptions = {}): LayoutProps {
  return {
    match: matchFor(rawView),
    busy: options.busy ?? false,
    onAction: options.onAction ?? (() => {}),
    selected: null,
    onSelect: () => {},
    trade: options.trade ?? tradeDraft(),
    onTradeChange: options.onTradeChange ?? (() => {}),
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
  options: LayoutOptions = {},
): string {
  return renderToStaticMarkup(<MonopolyPanelLayout {...layoutProps(rawView, options)} />)
}

function actionButtons(
  rawView: MonopolyView,
  options: LayoutOptions = {},
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

/** Every host element carrying ``className``, reached through the pure layout. */
function elementsWithClass(
  rawView: MonopolyView,
  className: string,
  options: LayoutOptions = {},
): ReactElement[] {
  const tree = MonopolyPanelLayout(layoutProps(rawView, options))
  return hostElements(tree).filter((element) => {
    const classes = ((element.props as { className?: string }).className ?? '').split(/\s+/)
    return classes.includes(className)
  })
}

function buttonWithLabel(buttons: ReactElement[], label: string): ReactElement {
  const button = buttons.find((element) => textOf(element) === label)
  if (!button) throw new Error(`no action button labelled ${label}`)
  return button
}

describe('the monopoly player panel', () => {
  it('renders every offered action with the server prompt as its label', () => {
    const actions: MonopolyAction[] = [
      { name: 'roll', prompt: 'Tirá los dados', options: [], freeform: false },
      { name: 'end_turn', prompt: 'Terminá el turno', options: [], freeform: false },
    ]
    const page = panelMarkup(view({ actions }))

    expect(page).toContain('Tirá los dados')
    expect(page).toContain('Terminá el turno')
    expect(actionButtons(view({ actions }))).toHaveLength(2)
  })

  it('submits an offered action without a value as null', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [{ name: 'roll', prompt: 'Tirá los dados', options: [], freeform: false }]
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
        freeform: false,
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
      { name: 'roll', prompt: 'Tirá los dados', options: [], freeform: false },
      { name: 'pay_income_tax', prompt: 'Elegí cómo pagar', options: ['fixed', 'percent'], freeform: false },
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
      { name: 'bid', prompt: 'Pujá', options: ['10', '20', '50'], freeform: false },
      { name: 'pass', prompt: 'Pasá la subasta.', options: [], freeform: false },
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
      { name: 'build', prompt: 'Construí', options: ['1', '3'], freeform: false },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Construí en Avenida Mediterráneo · $50')
    expect(textOf(buttons[1])).toBe('Construí en Avenida Báltica · $50')
  })

  it('draws a sell option as the space name and half the house cost', () => {
    const actions: MonopolyAction[] = [
      { name: 'sell', prompt: 'Vendé', options: ['11', '39'], freeform: false },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Vendé en St. Charles Place · +$50')
    expect(textOf(buttons[1])).toBe('Vendé en Boardwalk · +$100')
  })

  it('prices a build from the level the property already has', () => {
    // One more level costs one house cost whichever side of the hotel line it
    // is on; the label never becomes the property's total development value.
    const actions: MonopolyAction[] = [{ name: 'build', prompt: 'Construí', options: ['1'], freeform: false }]
    const built = view({ actions, buildings: { '1': 4 } })

    expect(textOf(actionButtons(built)[0])).toBe('Construí en Avenida Mediterráneo · $50')
  })

  it('submits the board index the server offered for build and sell', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [
      { name: 'build', prompt: 'Construí', options: ['1'], freeform: false },
      { name: 'sell', prompt: 'Vendé', options: ['3'], freeform: false },
    ]
    const buttons = actionButtons(view({ actions }), { onAction })

    ;(buttons[0].props as { onClick: () => void }).onClick()
    ;(buttons[1].props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('build', '1')
    expect(onAction).toHaveBeenCalledWith('sell', '3')
  })

  it('falls back to the raw option when a build option is not a board index', () => {
    const actions: MonopolyAction[] = [{ name: 'build', prompt: 'Construí', options: ['nope'], freeform: false }]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(1)
    expect(textOf(buttons[0])).toBe('Construí: nope')
  })

  it('draws a mortgage option as the space name and the cash it raises', () => {
    const actions: MonopolyAction[] = [
      { name: 'mortgage', prompt: 'Hipotecá', options: ['1', '5'], freeform: false },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Hipotecá en Avenida Mediterráneo · +$30')
    expect(textOf(buttons[1])).toBe('Hipotecá en Ferrocarril Reading · +$100')
  })

  it('draws an unmortgage option as the space name and the cash it costs', () => {
    const actions: MonopolyAction[] = [
      { name: 'unmortgage', prompt: 'Levantá la hipoteca', options: ['37', '39'], freeform: false },
    ]
    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(2)
    expect(textOf(buttons[0])).toBe('Levantá la hipoteca en Park Place · −$193')
    expect(textOf(buttons[1])).toBe('Levantá la hipoteca en Boardwalk · −$220')
  })

  it('submits the board index the server offered for mortgage and unmortgage', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [
      { name: 'mortgage', prompt: 'Hipotecá', options: ['1'], freeform: false },
      { name: 'unmortgage', prompt: 'Levantá la hipoteca', options: ['39'], freeform: false },
    ]
    const buttons = actionButtons(view({ actions }), { onAction })

    ;(buttons[0].props as { onClick: () => void }).onClick()
    ;(buttons[1].props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('mortgage', '1')
    expect(onAction).toHaveBeenCalledWith('unmortgage', '39')
  })

  it('falls back to the raw option when a mortgage option is not a purchasable index', () => {
    const actions: MonopolyAction[] = [
      { name: 'mortgage', prompt: 'Hipotecá', options: ['nope', '2'], freeform: false },
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
      actions: [{ name: 'pay_debt', prompt: 'Pagá la deuda', options: [], freeform: false }],
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

describe('the monopoly negotiation panel', () => {
  const proposeAction: MonopolyAction = {
    name: 'propose',
    prompt: 'Proponé un trato.',
    options: [],
    freeform: true,
  }
  const offer = {
    id: '1',
    proposer: 'seat-0',
    receiver: 'seat-1',
    give: { properties: [1], cash: 100 },
    want: { properties: [5], cash: 0 },
    valid: true,
  }

  it('skips a freeform action in the generic renderer and keeps the others', () => {
    const actions: MonopolyAction[] = [
      proposeAction,
      { name: 'roll', prompt: 'Tirá los dados', options: [], freeform: false },
    ]

    const buttons = actionButtons(view({ actions }))

    expect(buttons).toHaveLength(1)
    expect(textOf(buttons[0])).toBe('Tirá los dados')
    expect(panelMarkup(view({ actions }))).not.toContain('Proponé un trato.')
  })

  it('shows the negotiation block only when the server offers propose', () => {
    expect(panelMarkup(view())).not.toContain('monopoly-trade')
    expect(panelMarkup(view({ actions: [proposeAction] }))).toContain('monopoly-trade')
  })

  it('offers the other solvent seats as receivers and never the eliminated ones', () => {
    const players = [
      player({ seat: 'seat-0' }),
      player({ seat: 'seat-1' }),
      player({ seat: 'seat-2', eliminated: true }),
    ]
    const page = panelMarkup(view({ actions: [proposeAction], players }), {
      trade: tradeDraft({ receiver: 'seat-1' }),
    })

    expect(page).toContain('monopoly-trade-receiver')
    expect(page).toContain('value="seat-1"')
    expect(page).not.toContain('value="seat-0"')
    expect(page).not.toContain('value="seat-2"')
  })

  it('marks the own properties to give and the chosen receiver properties to ask for', () => {
    const players = [
      player({ seat: 'seat-0', properties: [1, 3] }),
      player({ seat: 'seat-1', properties: [5, 6] }),
    ]
    const raw = view({ actions: [proposeAction], players })
    const trade = tradeDraft({ receiver: 'seat-1', give: [3], want: [5] })

    const give = elementsWithClass(raw, 'monopoly-trade-give-property', { trade })
    const want = elementsWithClass(raw, 'monopoly-trade-want-property', { trade })

    expect(give.map((element) => (element.props as { value?: number }).value)).toEqual([1, 3])
    expect(want.map((element) => (element.props as { value?: number }).value)).toEqual([5, 6])
    expect((give[0].props as { checked?: boolean }).checked).toBe(false)
    expect((give[1].props as { checked?: boolean }).checked).toBe(true)
    expect((want[0].props as { checked?: boolean }).checked).toBe(true)
    expect((want[1].props as { checked?: boolean }).checked).toBe(false)
  })

  it('bounds each cash amount by the cash the view shows', () => {
    const players = [
      player({ seat: 'seat-0', cash: 1500 }),
      player({ seat: 'seat-1', cash: 1200 }),
    ]
    const raw = view({ actions: [proposeAction], players })
    const trade = tradeDraft({ receiver: 'seat-1' })

    const giveCash = elementsWithClass(raw, 'monopoly-trade-give-cash', { trade })
    const wantCash = elementsWithClass(raw, 'monopoly-trade-want-cash', { trade })

    expect((giveCash[0].props as { max?: number }).max).toBe(1500)
    expect((wantCash[0].props as { max?: number }).max).toBe(1200)
  })

  it('composes the trade grammar and submits the full offer through onAction', () => {
    const onAction = vi.fn()
    const trade = tradeDraft({
      receiver: 'seat-1',
      give: [3, 1],
      want: [5],
      giveCash: 100,
      wantCash: 0,
    })
    const send = elementsWithClass(
      view({ actions: [proposeAction] }),
      'monopoly-trade-send',
      { onAction, trade },
    )[0]

    ;(send.props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onAction).toHaveBeenCalledWith('propose', 'to=seat-1;give=1,3;cash=100|want=5;cash=0')
  })

  it('composes empty property lists and zero amounts', () => {
    const onAction = vi.fn()
    const send = elementsWithClass(
      view({ actions: [proposeAction] }),
      'monopoly-trade-send',
      { onAction, trade: tradeDraft({ receiver: 'seat-1' }) },
    )[0]

    ;(send.props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('propose', 'to=seat-1;give=;cash=0|want=;cash=0')
  })

  it('keeps the send button disabled until a receiver is picked', () => {
    const send = elementsWithClass(view({ actions: [proposeAction] }), 'monopoly-trade-send')[
      0
    ]

    expect((send.props as { disabled?: boolean }).disabled).toBe(true)
  })

  it('clears the asked properties when the receiver changes', () => {
    const onTradeChange = vi.fn()
    const trade = tradeDraft({ receiver: 'seat-1', want: [5] })
    const select = elementsWithClass(view({ actions: [proposeAction] }), 'monopoly-trade-receiver', {
      trade,
      onTradeChange,
    })[0]

    ;(select.props as { onChange: (event: { target: { value: string } }) => void }).onChange({
      target: { value: 'seat-2' },
    })

    expect(onTradeChange).toHaveBeenCalledWith({ ...trade, receiver: 'seat-2', want: [] })
  })

  it('lists the open offers with their terms, sides and validity', () => {
    const page = panelMarkup(view({ offers: [offer] }))

    expect(page).toContain('monopoly-offer-list')
    expect(page).toContain('data-valid="true"')
    expect(page).toContain('Ana entrega Avenida Mediterráneo y $100.')
    expect(page).toContain('Ana pide Ferrocarril Reading y $0.')
  })

  it('marks a stale offer as no longer acceptable', () => {
    const page = panelMarkup(view({ offers: [{ ...offer, valid: false }] }))

    expect(page).toContain('data-valid="false"')
    expect(page).toContain('Ya no es aceptable.')
  })

  it('offers accept and reject to the receiver and withdraw to the proposer', () => {
    const actions: MonopolyAction[] = [
      proposeAction,
      { name: 'accept', prompt: 'Aceptá', options: ['1'], freeform: false },
      { name: 'reject', prompt: 'Rechazá', options: ['1'], freeform: false },
      { name: 'withdraw', prompt: 'Retirá', options: ['1'], freeform: false },
    ]

    const asReceiver = panelMarkup(view({ you: 'seat-1', offers: [offer], actions }))
    expect(asReceiver).toContain('monopoly-offer-accept')
    expect(asReceiver).toContain('monopoly-offer-reject')
    expect(asReceiver).not.toContain('monopoly-offer-withdraw')

    const asProposer = panelMarkup(view({ you: 'seat-0', offers: [offer], actions }))
    expect(asProposer).toContain('monopoly-offer-withdraw')
    expect(asProposer).not.toContain('monopoly-offer-accept')
    expect(asProposer).not.toContain('monopoly-offer-reject')

    const asSpectator = panelMarkup(view({ you: undefined, offers: [offer], actions }))
    expect(asSpectator).toContain('monopoly-offer-list')
    expect(asSpectator).not.toContain('monopoly-offer-response')
  })

  it('renders the response actions only in the offer list, never generically', () => {
    const actions: MonopolyAction[] = [
      proposeAction,
      { name: 'accept', prompt: 'Aceptá', options: ['1'], freeform: false },
      { name: 'reject', prompt: 'Rechazá', options: ['1'], freeform: false },
    ]

    expect(actionButtons(view({ you: 'seat-1', offers: [offer], actions }))).toHaveLength(0)
  })

  it('withholds accept from a stale offer even if the server still lists it', () => {
    const actions: MonopolyAction[] = [
      { name: 'accept', prompt: 'Aceptá', options: ['1'], freeform: false },
      { name: 'reject', prompt: 'Rechazá', options: ['1'], freeform: false },
    ]
    const page = panelMarkup(
      view({ you: 'seat-1', offers: [{ ...offer, valid: false }], actions }),
    )

    expect(page).not.toContain('monopoly-offer-accept')
    expect(page).toContain('monopoly-offer-reject')
  })

  it('draws no response button the server did not offer', () => {
    const page = panelMarkup(view({ you: 'seat-1', offers: [offer], actions: [] }))

    expect(page).toContain('monopoly-offer-list')
    expect(page).not.toContain('monopoly-offer-response')
  })

  it('submits the offer id when a response button is pressed', () => {
    const onAction = vi.fn()
    const actions: MonopolyAction[] = [
      { name: 'accept', prompt: 'Aceptá', options: ['1'], freeform: false },
      { name: 'reject', prompt: 'Rechazá', options: ['1'], freeform: false },
      { name: 'withdraw', prompt: 'Retirá', options: ['1'], freeform: false },
    ]
    const raw = view({ you: 'seat-0', offers: [offer], actions })
    const withdraw = elementsWithClass(raw, 'monopoly-offer-withdraw', { onAction })[0]

    ;(withdraw.props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('withdraw', '1')
  })
})
