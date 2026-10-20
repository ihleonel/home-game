import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { MatchSeatRosterEntry } from '../matchRoster'
import type { MatchState } from '../registry'
import { BOARD } from './board'
import { MonopolyPanel, MonopolyPanelLayout } from './MonopolyPanel'
import type { MonopolyPane, MonopolySeatView, MonopolyTradeDraft } from './MonopolyPanel'
import type { MonopolyAction, MonopolyOffer, MonopolyPlayer, MonopolyView } from './view'
import { cellFor, windowAround } from './viewport'

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
  activeView?: MonopolyPane
  onViewChange?: (next: MonopolyPane) => void
  seatView?: MonopolySeatView | null
  onRotate?: (step: number) => void
  onPan?: (direction: 'up' | 'down' | 'left' | 'right') => void
  onCentre?: () => void
  onSpaceFocus?: (index: number) => void
}

/**
 * The seat view the panel derives for a fixture (S2/S8): ``null`` without an
 * own seat, and otherwise the opening orientation with the window centred on
 * the own token, which is what the panel computes on its first render.
 */
function seatViewFor(rawView: MonopolyView): MonopolySeatView | null {
  if (rawView.you === undefined) return null
  const own = rawView.players.find((entry) => entry.seat === rawView.you) ?? null
  if (own === null) return null
  return { turns: 0, window: windowAround(cellFor(own.position, 0)) }
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
    activeView: options.activeView ?? 'tablero',
    onViewChange: options.onViewChange ?? (() => {}),
    seatView: options.seatView === undefined ? seatViewFor(rawView) : options.seatView,
    onRotate: options.onRotate ?? (() => {}),
    onPan: options.onPan ?? (() => {}),
    onCentre: options.onCentre ?? (() => {}),
    onSpaceFocus: options.onSpaceFocus ?? (() => {}),
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

/** The class names of one host element, split the way the app builds them. */
function classesOf(element: ReactElement): string[] {
  return ((element.props as { className?: string }).className ?? '').split(/\s+/)
}

/**
 * The host elements the player can actually see.
 *
 * It differs from ``hostElements`` in one thing: the walk never enters a subtree
 * that carries ``hidden``, which is what the browser does. That is what lets a
 * test tell "the panel renders this block somewhere" from "the player can reach
 * it in the view that is open".
 */
function visibleElements(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    for (const child of node) visibleElements(child, found)
    return found
  }
  if (!isValidElement(node)) return found
  if ((node.props as { hidden?: boolean }).hidden === true) return found
  const component = node.type
  if (typeof component === 'function') {
    visibleElements((component as (p: unknown) => ReactElement)(node.props), found)
    return found
  }
  found.push(node)
  visibleElements((node.props as { children?: ReactNode }).children, found)
  return found
}

/**
 * The property-card buttons of each wallet card, in the order the cards are
 * drawn (S14).
 *
 * One array per card, so a test can say *which* card holds a button and not just
 * that the button exists somewhere in the panel.
 */
function cardButtonsByCard(rawView: MonopolyView, options: LayoutOptions = {}): string[][] {
  const tree = MonopolyPanelLayout(layoutProps(rawView, options))
  return hostElements(tree)
    .filter((element) => classesOf(element).includes('monopoly-property'))
    .map((card) =>
      hostElements(card)
        .filter((element) => classesOf(element).includes('monopoly-property-action'))
        .map(textOf),
    )
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

/** Every host element carrying ``role``, reached through the pure layout. */
function elementsWithRole(
  rawView: MonopolyView,
  role: string,
  options: LayoutOptions = {},
): ReactElement[] {
  const tree = MonopolyPanelLayout(layoutProps(rawView, options))
  return hostElements(tree).filter(
    (element) => (element.props as { role?: string }).role === role,
  )
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

  it('shows the own seat capital with its label clipped out of sight', () => {
    const page = panelMarkup(view())

    expect(page).toContain('monopoly-own-cash">$1.500<')
    expect(page).toContain('<dt class="monopoly-visually-hidden">Capital</dt>')
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

  it('draws the four property actions on the card of the property they act on', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1, 5] }), player({ seat: 'seat-1' })],
      // All four on the same property is not a legal board position; the fixture
      // offers them together on purpose, because what this test pins is the
      // order a card draws them in and which card takes each one.
      actions: [
        { name: 'build', prompt: 'Construí', options: ['1'], freeform: false },
        { name: 'sell', prompt: 'Vendé', options: ['1'], freeform: false },
        { name: 'mortgage', prompt: 'Hipotecá', options: ['1', '5'], freeform: false },
        { name: 'unmortgage', prompt: 'Levantá la hipoteca', options: ['1'], freeform: false },
      ],
    })

    expect(cardButtonsByCard(seated)).toEqual([
      ['Construí · $50', 'Vendé · +$25', 'Hipotecá · +$30', 'Levantá la hipoteca · −$33'],
      ['Hipotecá · +$100'],
    ])
  })

  it('prices a card build from the level the property already has', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1] }), player({ seat: 'seat-1' })],
      actions: [{ name: 'build', prompt: 'Construí', options: ['1'], freeform: false }],
      buildings: { '1': 4 },
    })

    expect(cardButtonsByCard(seated)).toEqual([['Construí · $50']])
  })

  it('submits the offered index from the card button', () => {
    const onAction = vi.fn()
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1, 5] }), player({ seat: 'seat-1' })],
      actions: [{ name: 'mortgage', prompt: 'Hipotecá', options: ['1', '5'], freeform: false }],
    })
    const buttons = elementsWithClass(seated, 'monopoly-property-action', { onAction })

    ;(buttons[1].props as { onClick: () => void }).onClick()

    expect(onAction).toHaveBeenCalledWith('mortgage', '5')
  })

  it('splits one action between the card and the strip', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1] }), player({ seat: 'seat-1' })],
      actions: [{ name: 'mortgage', prompt: 'Hipotecá', options: ['1', '5'], freeform: false }],
    })

    // The seat owns 1 and not 5, so the card for 1 takes its option and the
    // strip keeps the other one: an option no card can place is never dropped.
    expect(cardButtonsByCard(seated)).toEqual([['Hipotecá · +$30']])
    expect(actionButtons(seated).map(textOf)).toEqual(['Hipotecá en Ferrocarril Reading · +$100'])
  })

  it('leaves a build option that is not a street in the strip', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [5] }), player({ seat: 'seat-1' })],
      actions: [{ name: 'build', prompt: 'Construí', options: ['5'], freeform: false }],
    })

    // Building is a street-only rule, so a railroad's card cannot price the
    // option and it stays a strip button instead of leaving the screen.
    expect(cardButtonsByCard(seated)).toEqual([[]])
    expect(actionButtons(seated).map(textOf)).toEqual(['Construí: 5'])
  })

  it('keeps the turn actions in the strip while the cards take theirs', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1] }), player({ seat: 'seat-1' })],
      actions: [
        { name: 'mortgage', prompt: 'Hipotecá', options: ['1'], freeform: false },
        { name: 'roll', prompt: 'Tirá los dados', options: [], freeform: false },
        { name: 'end_turn', prompt: 'Terminá el turno', options: [], freeform: false },
      ],
    })

    expect(actionButtons(seated).map(textOf)).toEqual(['Tirá los dados', 'Terminá el turno'])
    expect(cardButtonsByCard(seated)).toEqual([['Hipotecá · +$30']])
  })

  it('draws no actions block when every offered action belongs to a card', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1] }), player({ seat: 'seat-1' })],
      actions: [{ name: 'mortgage', prompt: 'Hipotecá', options: ['1'], freeform: false }],
    })
    const page = panelMarkup(seated)

    expect(page).toContain('monopoly-property-actions')
    expect(page).not.toContain('monopoly-actions-block')
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

  it('marks every property group with the hook the wallet paints from', () => {
    const seated = view({
      players: [
        player({ seat: 'seat-0', properties: [1, 5, 12, 39] }),
        player({ seat: 'seat-1' }),
      ],
    })
    const groups = elementsWithClass(seated, 'monopoly-property-group')
    const hookOf = (element: ReactElement) => {
      const props = element.props as { 'data-group'?: string; 'data-kind'?: string }
      return props['data-group'] ?? props['data-kind']
    }

    // In board order: one brown street, a railroad, a utility and a dark blue
    // street, so the four shapes a wallet card can take are all pinned.
    expect(groups.map(hookOf)).toEqual(['brown', 'railroad', 'utility', 'dark_blue'])
  })

  it('gives a street group the colour the board gives its spaces', () => {
    const colours = [
      'brown',
      'light_blue',
      'pink',
      'orange',
      'red',
      'yellow',
      'green',
      'dark_blue',
    ] as const

    for (const colour of colours) {
      const street = BOARD.find((space) => space.group === colour)
      expect(street).toBeDefined()
      const seated = view({
        players: [
          player({ seat: 'seat-0', properties: [street!.index] }),
          player({ seat: 'seat-1' }),
        ],
      })

      expect(
        elementsWithClass(seated, 'monopoly-property-group').map(
          (element) => (element.props as { 'data-group'?: string })['data-group'],
        ),
      ).toEqual([colour])
    }
  })

  it('gives a group with no colour its kind and no colour hook', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [5, 12] }), player({ seat: 'seat-1' })],
    })
    const groups = elementsWithClass(seated, 'monopoly-property-group')
    const page = panelMarkup(seated)

    expect(
      groups.map((element) => (element.props as { 'data-kind'?: string })['data-kind']),
    ).toEqual(['railroad', 'utility'])
    // Exactly one of the two hooks is set, so one rule in the stylesheet can
    // never match a group twice and a group can never wear two colours.
    for (const group of groups) {
      expect((group.props as { 'data-group'?: string })['data-group']).toBeUndefined()
    }
    expect(page).toContain('data-kind="railroad"')
    expect(page).toContain('data-kind="utility"')
    expect(page).not.toContain('data-group="railroad"')
  })

  it('shows the own capital as the money alone, with its label kept for screen readers', () => {
    const seated = view()
    const page = panelMarkup(seated, { activeView: 'cartera' })
    const clipped = elementsWithClass(seated, 'monopoly-visually-hidden', {
      activeView: 'cartera',
    })

    expect(clipped.map(textOf)).toEqual(['Capital'])
    expect(page).toContain('monopoly-own-cash')
  })

  it('does not repeat the own position in the wallet', () => {
    const page = panelMarkup(view(), { activeView: 'cartera' })

    // The space name cannot be asserted against: the board pane prints every
    // name too. The hook and the label are what say the fact was dropped.
    expect(page).not.toContain('monopoly-own-position')
    expect(page).not.toContain('>Posición<')
  })

  it('stays silent about jail while the seat is free, and reports it when it is not', () => {
    const jailed = view({
      players: [
        player({ seat: 'seat-0', in_jail: true, jail_turns: 2 }),
        player({ seat: 'seat-1' }),
      ],
    })

    expect(elementsWithClass(view(), 'monopoly-own-jail', { activeView: 'cartera' })).toHaveLength(
      0,
    )
    expect(panelMarkup(view(), { activeView: 'cartera' })).not.toContain('Sin restricciones')
    expect(
      elementsWithClass(jailed, 'monopoly-own-jail', { activeView: 'cartera' }).map(textOf),
    ).toEqual(['En la cárcel (2 turnos)'])
  })

  it('lists the jail cards only while the seat holds one', () => {
    const holding = view({
      players: [player({ seat: 'seat-0', jail_cards: 1 }), player({ seat: 'seat-1' })],
    })

    expect(
      elementsWithClass(view(), 'monopoly-own-jail-cards', { activeView: 'cartera' }),
    ).toHaveLength(0)
    expect(panelMarkup(holding, { activeView: 'cartera' })).toContain(
      'monopoly-own-jail-cards">1<',
    )
  })

  it('drops the printed-data disclaimer and keeps every rent line qualified', () => {
    const seated = view({
      players: [
        player({ seat: 'seat-0', properties: [1, 3] }),
        player({ seat: 'seat-1' }),
      ],
    })
    const page = panelMarkup(seated, { activeView: 'cartera' })

    expect(page).not.toContain('Datos impresos de la escritura')
    expect(page).not.toContain('monopoly-reference-note')
    expect(page).toContain('Rentas impresas')
  })

  it('keeps the colour group name for screen readers alone', () => {
    const seated = view({
      players: [
        player({ seat: 'seat-0', properties: [1, 3] }),
        player({ seat: 'seat-1' }),
      ],
    })
    const titles = elementsWithClass(seated, 'monopoly-property-group-title', {
      activeView: 'cartera',
    })

    expect(titles).toHaveLength(1)
    expect(classesOf(titles[0])).toContain('monopoly-visually-hidden')
    expect(textOf(titles[0])).toBe('Marrón')
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

/**
 * The view switcher (S1/S2 of ``monopoly-view-switcher.md``).
 *
 * These tests cover the pure layout, which is the whole shell: the wrapper adds
 * nothing but the ``useState`` that holds the pane. They pin the tab list, the
 * one-pane-at-a-time rule, the ARIA wiring and what a keyboard press submits.
 */
describe('the monopoly view switcher', () => {
  const panes = ['tablero', 'cartera', 'mesa'] as const

  function paneOfTab(tab: ReactElement): string {
    return (tab.props as { 'data-pane': string })['data-pane']
  }

  function tabs(options: LayoutOptions = {}): ReactElement[] {
    return elementsWithRole(view(), 'tab', options)
  }

  function panels(options: LayoutOptions = {}): ReactElement[] {
    return elementsWithRole(view(), 'tabpanel', options)
  }

  it('draws the three views as the tabs of one tab list', () => {
    const page = panelMarkup(view())
    const tabLists = elementsWithRole(view(), 'tablist')

    expect(tabLists).toHaveLength(1)
    expect(tabs().map(paneOfTab)).toEqual([...panes])
    expect(page).toContain('monopoly-tab-label">Tablero<')
    expect(page).toContain('monopoly-tab-label">Cartera<')
    expect(page).toContain('monopoly-tab-label">Mesa<')
  })

  it('marks exactly the open view as the selected tab', () => {
    const selected = (activeView: MonopolyPane) =>
      tabs({ activeView }).filter(
        (tab) => (tab.props as { 'aria-selected'?: boolean })['aria-selected'] === true,
      )

    for (const pane of panes) {
      const marked = selected(pane)
      expect(marked).toHaveLength(1)
      expect(paneOfTab(marked[0])).toBe(pane)
    }
  })

  it('leaves exactly the open view reachable with the Tab key', () => {
    const reachable = (activeView: MonopolyPane) =>
      tabs({ activeView })
        .filter((tab) => (tab.props as { tabIndex?: number }).tabIndex === 0)
        .map(paneOfTab)

    for (const pane of panes) {
      expect(reachable(pane)).toEqual([pane])
      expect(tabs({ activeView: pane })).toHaveLength(3)
    }
  })

  it('shows only the open view and keeps the other two out of the way', () => {
    for (const pane of panes) {
      const open = panels({ activeView: pane }).filter(
        (panel) => (panel.props as { hidden?: boolean }).hidden !== true,
      )

      expect(open).toHaveLength(1)
      expect((open[0].props as { id: string }).id).toBe(`monopoly-pane-${pane}`)
      expect(panels({ activeView: pane })).toHaveLength(3)
    }
  })

  it('wires every tab to the panel it opens', () => {
    const page = panelMarkup(view({ you: undefined }), { activeView: 'mesa' })

    for (const pane of panes) {
      const tab = tabs().find((element) => paneOfTab(element) === pane)
      const panel = panels().find(
        (element) => (element.props as { id?: string }).id === `monopoly-pane-${pane}`,
      )

      expect(tab).toBeDefined()
      expect(panel).toBeDefined()
      expect((tab!.props as { id: string }).id).toBe(`monopoly-tab-${pane}`)
      expect((tab!.props as { 'aria-controls': string })['aria-controls']).toBe(
        `monopoly-pane-${pane}`,
      )
      expect((panel!.props as { 'aria-labelledby': string })['aria-labelledby']).toBe(
        `monopoly-tab-${pane}`,
      )
    }

    expect(page).toContain('role="tablist"')
    expect(page).toContain('aria-label="Vistas de la partida"')
  })

  it('submits the view the player picks', () => {
    const onViewChange = vi.fn()
    const mesa = tabs({ onViewChange }).find((tab) => paneOfTab(tab) === 'mesa')

    ;(mesa!.props as { onClick: () => void }).onClick()

    expect(onViewChange).toHaveBeenCalledWith('mesa')
  })

  it('moves between the views with the arrow, home and end keys', () => {
    const onViewChange = vi.fn()
    const preventDefault = vi.fn()
    const tabList = elementsWithRole(view(), 'tablist', {
      activeView: 'cartera',
      onViewChange,
    })[0]
    const press = (key: string) =>
      (
        tabList.props as {
          onKeyDown: (event: { key: string; preventDefault: () => void }) => void
        }
      ).onKeyDown({ key, preventDefault })

    // The four keys move relative to the open view, and the two arrow keys wrap
    // around the ends so the last view never dead-ends.
    press('ArrowRight')
    expect(onViewChange).toHaveBeenLastCalledWith('mesa')
    press('ArrowLeft')
    expect(onViewChange).toHaveBeenLastCalledWith('tablero')
    press('Home')
    expect(onViewChange).toHaveBeenLastCalledWith('tablero')
    press('End')
    expect(onViewChange).toHaveBeenLastCalledWith('mesa')
    expect(preventDefault).toHaveBeenCalledTimes(4)

    press('Enter')
    expect(onViewChange).toHaveBeenCalledTimes(4)
    expect(preventDefault).toHaveBeenCalledTimes(4)
  })

  it('opens on the board view when the match mounts', () => {
    const page = panelMarkup(view())
    const open = panels().filter(
      (panel) => (panel.props as { hidden?: boolean }).hidden !== true,
    )

    expect(open).toHaveLength(1)
    expect((open[0].props as { id: string }).id).toBe('monopoly-pane-tablero')
    expect(page).toContain('id="monopoly-pane-tablero"')
  })

  it('keeps the offered actions reachable from every view', () => {
    const actions: MonopolyAction[] = [
      { name: 'roll', prompt: 'Tirá los dados', options: [], freeform: false },
      { name: 'end_turn', prompt: 'Terminá el turno', options: [], freeform: false },
    ]

    for (const pane of panes) {
      const reachable = visibleElements(
        MonopolyPanelLayout(layoutProps(view({ actions }), { activeView: pane })),
      ).filter((element) => classesOf(element).includes('monopoly-action'))

      expect(reachable.map(textOf)).toEqual(['Tirá los dados', 'Terminá el turno'])
    }
  })

  it('keeps the open debt beside the actions in every view', () => {
    const raising = view({
      phase: 'raising_cash',
      debt: { seat: 'seat-0', creditor: null, amount: 50 },
      actions: [{ name: 'pay_debt', prompt: 'Pagá la deuda', options: [], freeform: false }],
    })

    for (const pane of panes) {
      const classes = visibleElements(
        MonopolyPanelLayout(layoutProps(raising, { activeView: pane })),
      ).map(classesOf)
      const debt = classes.findIndex((names) => names.includes('monopoly-debt'))
      const actions = classes.findIndex((names) => names.includes('monopoly-actions-block'))

      expect(debt).toBeGreaterThan(-1)
      expect(actions).toBeGreaterThan(-1)
      expect(debt).toBeLessThan(actions)
    }
  })

  it('counts the open offers on the table tab', () => {
    const offer = (id: string): MonopolyOffer => ({
      id,
      proposer: 'seat-1',
      receiver: 'seat-0',
      give: { properties: [], cash: 100 },
      want: { properties: [], cash: 0 },
      valid: true,
    })
    const badges = (ids: string[]) => {
      const rendered = elementsWithRole(view({ offers: ids.map(offer) }), 'tab')
      const mesa = rendered.find((tab) => paneOfTab(tab) === 'mesa')
      return hostElements(mesa as ReactNode).filter((element) =>
        classesOf(element).includes('monopoly-tab-badge'),
      )
    }
    // The count is a number, so ``textOf`` (which only reads string children)
    // would read it as empty.
    const badgeText = (element: ReactElement) =>
      String((element.props as { children?: ReactNode }).children)

    expect(badges([])).toEqual([])
    expect(badges(['1']).map(badgeText)).toEqual(['1'])
    expect(badges(['1', '2']).map(badgeText)).toEqual(['2'])
    // The count is decoration: the tab itself carries the same fact in its
    // accessible name, so a screen reader never reads a bare number.
    expect(
      (badges(['1', '2'])[0].props as { 'aria-hidden'?: string })['aria-hidden'],
    ).toBe('true')
  })

  it('names the table tab with the offers waiting in it', () => {
    const offer = (id: string): MonopolyOffer => ({
      id,
      proposer: 'seat-1',
      receiver: 'seat-0',
      give: { properties: [], cash: 100 },
      want: { properties: [], cash: 0 },
      valid: true,
    })
    const label = (rawView: MonopolyView) =>
      (
        elementsWithRole(rawView, 'tab').find((tab) => paneOfTab(tab) === 'mesa')!
          .props as { 'aria-label'?: string }
      )['aria-label']

    expect(label(view({ offers: [] }))).toBeUndefined()
    expect(label(view({ offers: [offer('1')] }))).toBe('Mesa (1 oferta abierta)')
    expect(label(view({ offers: [offer('1'), offer('2')] }))).toBe(
      'Mesa (2 ofertas abiertas)',
    )
  })

  it('counts on the wallet tab the actions waiting on the seat own properties', () => {
    const seated = view({
      players: [player({ seat: 'seat-0', properties: [1, 5] }), player({ seat: 'seat-1' })],
      actions: [{ name: 'mortgage', prompt: 'Hipotecá', options: ['1', '5'], freeform: false }],
    })
    const carteraTab = (rawView: MonopolyView) =>
      elementsWithRole(rawView, 'tab').find((tab) => paneOfTab(tab) === 'cartera')
    const waiting = (rawView: MonopolyView) =>
      (carteraTab(rawView)!.props as { 'aria-label'?: string })['aria-label']

    expect(waiting(view())).toBeUndefined()
    expect(waiting(seated)).toBe('Cartera (2 acciones sobre tus propiedades)')

    const badge = hostElements(carteraTab(seated) as ReactNode).find((element) =>
      classesOf(element).includes('monopoly-tab-badge'),
    )
    expect(String((badge!.props as { children?: ReactNode }).children)).toBe('2')
  })
})

/**
 * The board seen from a seat (S1, S2, S8, S11 of ``monopoly-seat-viewport.md``).
 *
 * The state that turns the table and moves the window lives in the hook
 * wrapper, which this harness cannot invoke, so the *rules* that decide the
 * window are pinned in ``viewport.test.ts`` and what is pinned here is the
 * wiring: who gets the framed board, who gets the whole one, which controls the
 * layout reports and where the middle of the table ends up.
 */
describe('the monopoly seat view', () => {
  it('frames the board for a seat and puts the centre of the table outside the window', () => {
    const rawView = view()
    const frame = elementsWithClass(rawView, 'monopoly-viewport-frame')
    const seatTable = elementsWithClass(rawView, 'monopoly-seat-table')

    expect(frame).toHaveLength(1)
    // The window of the opening seat: centred on its own token, which is on GO.
    expect((frame[0].props as { style: Record<string, string> }).style).toEqual({
      '--monopoly-viewport-row': '5',
      '--monopoly-viewport-column': '5',
    })
    // The middle of the board is empty, and the table's content is in one strip.
    expect(elementsWithClass(rawView, 'monopoly-centre-empty')).toHaveLength(1)
    expect(seatTable).toHaveLength(1)
    const centres = hostElements(seatTable[0]).filter((element) =>
      classesOf(element).includes('monopoly-centre'),
    )
    // One real centre, and it is the strip's: the hole in the board is the
    // element that also carries the empty-surface class.
    expect(centres).toHaveLength(1)
    expect(classesOf(centres[0])).not.toContain('monopoly-centre-empty')
    // Nothing about the match state leaves the screen with the pan: the strip
    // carries the turn it always did.
    expect(renderToStaticMarkup(<>{seatTable[0]}</>)).toContain('Turno de Ana')
  })

  it('leaves the whole board to a spectator, with no window and no controls', () => {
    // ``view.you`` is absent for a spectator, which is how the server projects a
    // public view: no seat, no own token and therefore no window (S2).
    const rawView = view({ you: undefined })
    const markup = panelMarkup(rawView)

    expect(elementsWithClass(rawView, 'monopoly-viewport-frame')).toHaveLength(0)
    expect(elementsWithClass(rawView, 'monopoly-seat-table')).toHaveLength(0)
    expect(elementsWithClass(rawView, 'monopoly-centre-empty')).toHaveLength(0)
    // The centre the spectator reads is the one inside the ring.
    expect(elementsWithClass(rawView, 'monopoly-centre')).toHaveLength(1)
    expect(markup).not.toContain('Girar a la derecha')
    expect(markup).not.toContain('Centrar en mi ficha')
    expect(markup).toContain('Turno de Ana')
  })

  it('passes the turn count to the frame and to the cells the frame holds', () => {
    const rawView = view()
    const frame = elementsWithClass(rawView, 'monopoly-viewport-frame', {
      seatView: { turns: 1, window: { row: 1, column: 1 } },
    })

    expect((frame[0].props as { 'data-turns'?: number })['data-turns']).toBe(1)
    // A quarter turn re-indexes the ring: GO is bottom-left and its band faces
    // the centre from the left side.
    const go = elementsWithClass(rawView, 'monopoly-space', {
      seatView: { turns: 1, window: { row: 1, column: 1 } },
    }).find((element) => (element.props as { 'aria-label'?: string })['aria-label']?.startsWith('GO'))
    expect((go?.props as { style: { gridRow: number; gridColumn: number } }).style).toEqual({
      gridRow: 11,
      gridColumn: 1,
    })
    expect((go?.props as Record<string, string>)['data-side']).toBe('left')
  })

  it('reports the turn, the pan and the centring the player asks for', () => {
    const onRotate = vi.fn()
    const onPan = vi.fn()
    const onCentre = vi.fn()
    const rawView = view()
    const options = { onRotate, onPan, onCentre }
    /** One control of a layout carrying the spies, found by its accessible name. */
    const controlWith = (label: string): ReactElement => {
      const button = elementsWithClass(rawView, 'monopoly-viewport-button', options).find(
        (element) => (element.props as { 'aria-label'?: string })['aria-label'] === label,
      )
      if (!button) throw new Error(`no viewport control named ${label}`)
      return button
    }
    const press = (label: string): void =>
      (controlWith(label).props as { onClick: () => void }).onClick()

    press('Girar a la izquierda')
    press('Girar a la derecha')
    press('Orientación impresa')
    press('Mover la ventana derecha')
    press('Centrar en mi ficha')

    // "Printed orientation" is a step back from the current turn count, so at
    // zero turns it asks for no step at all.
    expect(onRotate.mock.calls).toEqual([[-1], [1], [-0]])
    expect(onPan.mock.calls).toEqual([['right']])
    expect(onCentre).toHaveBeenCalledTimes(1)
  })

  it('reports the space that takes keyboard focus, so the window can follow it', () => {
    const onSpaceFocus = vi.fn()
    const rawView = view()
    const go = elementsWithClass(rawView, 'monopoly-space', { onSpaceFocus }).find((element) =>
      ((element.props as { 'aria-label'?: string })['aria-label'] ?? '').startsWith('GO'),
    )
    expect(go).toBeDefined()
    ;(go?.props as { onFocus: () => void }).onFocus()
    expect(onSpaceFocus.mock.calls).toEqual([[0]])
  })
})
