import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
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
  round: 2,
  scores: { 'seat-0': 1, 'seat-1': 0 },
  your_pick: null,
  opponent_has_picked: true,
  reveal: {
    round: 1,
    picks: { 'seat-0': 'rock', 'seat-1': 'scissors' },
    winner: 'seat-0',
  },
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
  const screen = renderMatchScreen('duelo', props(view, version))
  return screen === null ? null : renderToStaticMarkup(screen)
}

/**
 * Collect the rendered host elements of a component tree.
 *
 * The tests run against `react-dom/server` with no DOM, so a click is verified
 * by walking the element tree the screen returns and invoking the handler React
 * would have attached.
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
function buttonsIn(view: unknown, version: number | null = 3): ReactElement[] {
  const screen = renderMatchScreen('duelo', props(view, version))
  if (!screen) return []
  return hostElements(screen).filter((element) => element.type === 'button')
}

describe('the duelo match screen', () => {
  it('gives every pick its own shape and its own label, so colour is never the only cue', () => {
    const markup = render(inProgress) ?? ''

    // Each card carries a decorative shape (aria-hidden, so a screen reader is
    // not read a picture) and the visible label that already names the play.
    for (const [pick, label] of [
      ['rock', 'Piedra'],
      ['paper', 'Papel'],
      ['scissors', 'Tijera'],
    ]) {
      expect(markup).toMatch(
        new RegExp(`data-pick="${pick}"[\\s\\S]*?duelo-pick-art[\\s\\S]*?${label}<`),
      )
    }
    expect(markup.match(/duelo-pick-art/g)).toHaveLength(3)
    expect(markup).toContain('aria-hidden="true"')
  })

  it('marks the card the player already played and locks the other two', () => {
    const markup = render({ ...inProgress, your_pick: 'paper' }) ?? ''

    expect(markup.match(/aria-pressed="true"/g)).toHaveLength(1)
    expect(markup).toMatch(/data-pick="paper"[^>]*aria-pressed="true"/)

    const buttons = buttonsIn({ ...inProgress, your_pick: 'paper' })
    expect(buttons).toHaveLength(3)
    expect(buttons.every((button) => (button.props as { disabled?: boolean }).disabled)).toBe(true)
  })

  it('keeps the round label as one contiguous text', () => {
    // ``MatchPage`` asserts this same string on the whole screen, so the label
    // must stay a single text node instead of splitting the number into a chip.
    expect(render(inProgress)).toContain('Ronda 2')
  })

  it('names both seats and offers the three picks to a seated player', () => {
    const markup = render(inProgress) ?? ''

    expect(markup).toContain('Ana')
    expect(markup).toContain('Beto')
    expect(markup).toContain('Sol')
    expect(markup).toContain('Luna')
    expect(markup).toContain('Piedra')
    expect(markup).toContain('Papel')
    expect(markup).toContain('Tijera')
  })
})
