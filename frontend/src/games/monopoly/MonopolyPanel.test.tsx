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
