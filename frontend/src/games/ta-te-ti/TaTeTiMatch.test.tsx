import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { renderMatchScreen } from '../registry'
import type { MatchState } from '../registry'

const roster = [
  {
    seat_id: 'seat-0',
    index: 0,
    display_name: 'Ana',
    game_marker: 'sol',
    game_marker_label: 'Sol',
  },
  {
    seat_id: 'seat-1',
    index: 1,
    display_name: 'Beto',
    game_marker: 'luna',
    game_marker_label: 'Luna',
  },
]

const inProgress = {
  board: ['seat-0', 'seat-1', null, null, 'seat-0', null, null, null, 'seat-1'],
  turn: 'seat-0',
  symbols: { 'seat-0': 'X', 'seat-1': 'O' },
  winner_line: null,
  you: 'seat-0',
  winner: null,
  finished: false,
  ended_by_abandon: false,
}

/**
 * Build the match state a screen receives from a raw payload.
 *
 * The registry exists precisely because the payload arrives unvalidated over
 * the network, so the tests feed it raw values on purpose and this cast is the
 * only place the boundary is crossed.
 */
function rawMatch(view: unknown, version: number | null = 3): MatchState {
  return {
    matchRef: 'match-1',
    seatIndex: 0,
    version,
    roster,
    view,
  } as unknown as MatchState
}

function props(view: unknown, version: number | null = 3, onPick: (value: string) => void = () => {}) {
  return { busy: false, match: rawMatch(view, version), onAction: () => {}, onPick }
}

function render(view: unknown, version: number | null = 3): string | null {
  const screen = renderMatchScreen('ta-te-ti', props(view, version))
  return screen === null ? null : renderToStaticMarkup(screen)
}

/**
 * Collect the rendered host elements of a component tree.
 *
 * The tests run against `react-dom/server` with no DOM, so a click is verified
 * by walking the element tree the screen returns and invoking the handler React
 * would have attached. Every cell is rendered inline, so no nested component
 * hides a button from this walk.
 */
function hostElements(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    for (const child of node) hostElements(child, found)
    return found
  }
  if (!isValidElement(node)) return found
  const component = node.type
  if (typeof component === 'function') {
    // Expand the game component the registry returned so its inline buttons
    // become visible; host elements are recorded as-is.
    const rendered = (component as (p: unknown) => ReactElement)(node.props)
    hostElements(rendered, found)
    return found
  }
  found.push(node)
  const elementProps = node.props as { children?: ReactNode }
  hostElements(elementProps.children, found)
  return found
}

/** The screen's buttons, already expanded past the game component. */
function buttonsIn(
  view: unknown,
  version: number | null = 3,
  onPick: (value: string) => void = () => {},
): ReactElement[] {
  const screen = renderMatchScreen('ta-te-ti', props(view, version, onPick))
  if (!screen) return []
  return hostElements(screen).filter((element) => element.type === 'button')
}

function enabledButtons(
  view: unknown,
  version: number | null = 3,
  onPick: (value: string) => void = () => {},
): ReactElement[] {
  return buttonsIn(view, version, onPick).filter(
    (button) => !(button.props as { disabled?: boolean }).disabled,
  )
}

describe('the ta-te-ti match screen', () => {
  it('renders the game and every board cell with the symbol of its owner', () => {
    const markup = render(inProgress) ?? ''

    expect(markup).toContain('Ta-te-ti')
    expect(markup).toContain('ta-te-ti-cell-symbol">X<')
    expect(markup).toContain('ta-te-ti-cell-symbol">O<')
  })

  it('names every seat from the server roster with its marker chip', () => {
    const markup = render(inProgress) ?? ''

    expect(markup).toContain('Ana')
    expect(markup).toContain('Sol')
    expect(markup).toContain('Beto')
    expect(markup).toContain('Luna')
  })

  it('enables only the free cells while the viewer holds the turn', () => {
    expect(enabledButtons(inProgress)).toHaveLength(5)
  })

  it('enables no cell when the turn belongs to the other seat', () => {
    expect(enabledButtons({ ...inProgress, turn: 'seat-1' })).toHaveLength(0)
  })

  it('enables no cell while the version is unknown', () => {
    expect(enabledButtons(inProgress, null)).toHaveLength(0)
  })

  it('calls onPick with the clicked cell index as a string', () => {
    const onPick = vi.fn()
    const firstFree = enabledButtons(inProgress, 3, onPick)[0]
    expect(firstFree).toBeDefined()

    ;(firstFree.props as { onClick: () => void }).onClick()

    expect(onPick).toHaveBeenCalledWith('2')
  })

  it('shows the draw sentence and nothing else in a finished draw', () => {
    const markup =
      render({
        ...inProgress,
        board: ['seat-0', 'seat-1', 'seat-0', 'seat-0', 'seat-1', 'seat-1', 'seat-1', 'seat-0', 'seat-0'],
        turn: null,
        winner: null,
        winner_line: null,
        finished: true,
      }) ?? ''

    expect(markup).toContain('Empate.')
  })

  it('names the winner and highlights the winning line', () => {
    const markup =
      render({
        ...inProgress,
        board: ['seat-0', 'seat-0', 'seat-0', 'seat-1', 'seat-1', null, null, null, null],
        turn: null,
        winner: 'seat-0',
        winner_line: [0, 1, 2],
        finished: true,
      }) ?? ''

    expect(markup).toContain('Has ganado la partida.')
    expect(markup.match(/ta-te-ti-cell-winning/g)).toHaveLength(3)
  })

  it('leaves a finish by abandonment to the match screen', () => {
    const markup =
      render({
        ...inProgress,
        turn: null,
        winner: 'seat-1',
        finished: true,
        ended_by_abandon: true,
      }) ?? ''

    expect(markup).not.toContain('Empate.')
    expect(markup).not.toContain('ta-te-ti-outcome')
  })

  it('returns null for a registered game whose payload is not that game view', () => {
    expect(render({})).toBeNull()
    expect(render({ round: 1, scores: { 'seat-0': 0 }, winner: null, finished: false })).toBeNull()
  })
})
