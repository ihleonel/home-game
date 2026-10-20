import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { spaceAt } from './board'
import { MonopolyBoardViewport } from './MonopolyBoardViewport'
import { visibleSpaces } from './viewport'
import type { QuarterTurns, ViewDirection, ViewWindow } from './viewport'

/** A window that can move in every direction: neither origin is at a border. */
const MIDDLE: ViewWindow = { row: 3, column: 3 }

/**
 * A window over the empty middle of the table: rows 2..8 and columns 2..8 hold
 * no space of the ring, so the visible arc is empty.
 */
const OVER_THE_CENTRE: ViewWindow = { row: 2, column: 2 }

/** A window that crosses GO, so the arc opens in the middle of the circuit. */
const ACROSS_GO: ViewWindow = { row: 5, column: 5 }

/** A window on the top-right corner of the printed board. */
const TOP_RIGHT: ViewWindow = { row: 1, column: 5 }

/** The four pan buttons in the order the component must keep them. */
const PAN_BUTTONS: readonly (readonly [string, ViewDirection])[] = [
  ['Mover la ventana arriba', 'up'],
  ['Mover la ventana abajo', 'down'],
  ['Mover la ventana izquierda', 'left'],
  ['Mover la ventana derecha', 'right'],
]

/** The accessible names of every control, in the order the markup adds them. */
const CONTROL_ORDER = [
  'Girar a la izquierda',
  'Girar a la derecha',
  'Orientación impresa',
  'Mover la ventana arriba',
  'Mover la ventana abajo',
  'Mover la ventana izquierda',
  'Mover la ventana derecha',
  'Centrar en mi ficha',
]

type Props = {
  turns?: QuarterTurns
  window?: ViewWindow
  onRotate?: (step: number) => void
  onCentre?: () => void
  onPan?: (direction: ViewDirection) => void
  overlay?: ReactNode
  children?: ReactNode
}

/** Render the viewport with the defaults a test does not care about. */
function viewport(overrides: Props = {}): ReactElement {
  return MonopolyBoardViewport({
    turns: 0,
    window: MIDDLE,
    onRotate: () => {},
    onCentre: () => {},
    onPan: () => {},
    children: <span>Tablero de prueba</span>,
    ...overrides,
  })
}

/**
 * Collect the rendered host elements of a component tree.
 *
 * The tests run against `react-dom/server` with no DOM, so a click is verified
 * by walking the element tree the viewport returns and invoking the handler
 * React would have attached. The component is a pure function of its props, so
 * it can be invoked directly; it returns host elements only, which is why the
 * walk finds every control.
 */
function hostElements(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    for (const child of node) hostElements(child, found)
    return found
  }
  if (!isValidElement(node)) return found
  const component = node.type
  if (typeof component === 'function') {
    const rendered = (component as (props: unknown) => ReactElement)(node.props)
    hostElements(rendered, found)
    return found
  }
  found.push(node)
  const elementProps = node.props as { children?: ReactNode }
  hostElements(elementProps.children, found)
  return found
}

function buttons(tree: ReactElement): ReactElement[] {
  return hostElements(tree).filter((element) => element.type === 'button')
}

function labelOf(button: ReactElement): string {
  return (button.props as { 'aria-label'?: string })['aria-label'] ?? ''
}

function buttonNamed(tree: ReactElement, name: string): ReactElement {
  const button = buttons(tree).find((candidate) => labelOf(candidate) === name)
  if (button === undefined) throw new Error(`no button named ${name}`)
  return button
}

function disabledOf(button: ReactElement): boolean {
  return (button.props as { disabled?: boolean }).disabled === true
}

function click(button: ReactElement): void {
  ;(button.props as { onClick: () => void }).onClick()
}

/** The frame the stylesheet clips, found by its role rather than by tag. */
function frameOf(tree: ReactElement): ReactElement {
  const frame = hostElements(tree).find(
    (element) => (element.props as { role?: string }).role === 'group',
  )
  if (frame === undefined) throw new Error('the viewport has no frame')
  return frame
}

/** The text of the single status line, read from the static markup. */
function statusText(tree: ReactElement): string {
  const status = hostElements(tree).find(
    (element) => (element.props as { role?: string }).role === 'status',
  )
  if (status === undefined) throw new Error('the viewport has no status line')
  return renderToStaticMarkup(status)
    .replace(/<[^>]+>/g, '')
    .trim()
}

describe('the viewport frame', () => {
  it('is a named group that carries the window origin and the turn count', () => {
    const frame = frameOf(viewport({ turns: 2, window: { row: 4, column: 5 } }))
    const props = frame.props as {
      'aria-label'?: string
      'data-turns'?: number
      style?: Record<string, string>
    }
    // The board already announces itself as a group called "Tablero de
    // Monopoly", so nesting a second group under the same name would make a
    // screen reader read the same heading twice.
    expect(props['aria-label']).toBe('Ventana del tablero de Monopoly')
    expect(props['data-turns']).toBe(2)
    expect(props.style?.['--monopoly-viewport-row']).toBe('4')
    expect(props.style?.['--monopoly-viewport-column']).toBe('5')
  })

  it('exposes the same hooks in the static markup the stylesheet reads', () => {
    const markup = renderToStaticMarkup(
      viewport({ turns: 1, window: { row: 4, column: 5 } }),
    )
    expect(markup).toContain('--monopoly-viewport-row:4')
    expect(markup).toContain('--monopoly-viewport-column:5')
    expect(markup).toContain('data-turns="1"')
  })

  it('draws the board it is given inside the frame', () => {
    const frame = frameOf(viewport())
    const frameProps = frame.props as { children?: ReactNode }
    const inside = renderToStaticMarkup(frameProps.children)
    expect(inside).toContain('Tablero de prueba')
  })
})

describe('the turn controls', () => {
  it('turns one quarter left, one quarter right and back to the printed board', () => {
    for (const turns of [0, 1, 2, 3] as const) {
      const onRotate = vi.fn()
      const tree = viewport({ turns, onRotate })
      click(buttonNamed(tree, 'Girar a la izquierda'))
      expect(onRotate).toHaveBeenLastCalledWith(-1)
      click(buttonNamed(tree, 'Girar a la derecha'))
      expect(onRotate).toHaveBeenLastCalledWith(1)
      click(buttonNamed(tree, 'Orientación impresa'))
      const printed: number = onRotate.mock.calls.at(-1)?.[0] ?? NaN
      expect([turns, printed + turns]).toEqual([turns, 0])
    }
  })

  it('keeps the eight controls in a fixed order', () => {
    expect(buttons(viewport()).map(labelOf)).toEqual(CONTROL_ORDER)
  })
})

describe('the manual pan', () => {
  it('moves the window one cell in each direction', () => {
    for (const [label, direction] of PAN_BUTTONS) {
      const onPan = vi.fn()
      click(buttonNamed(viewport({ onPan }), label))
      expect([label, onPan.mock.calls]).toEqual([label, [[direction]]])
    }
  })

  it('disables exactly the steps that would leave the board', () => {
    const cases: readonly (readonly [ViewWindow, readonly boolean[]])[] = [
      [{ row: 3, column: 3 }, [false, false, false, false]],
      [{ row: 1, column: 5 }, [true, false, false, true]],
      [{ row: 5, column: 1 }, [false, true, true, false]],
      [{ row: 1, column: 1 }, [true, false, true, false]],
      [{ row: 5, column: 5 }, [false, true, false, true]],
    ]
    for (const [window, expected] of cases) {
      const tree = viewport({ window })
      const disabled = PAN_BUTTONS.map(([label]) => disabledOf(buttonNamed(tree, label)))
      expect([window, disabled]).toEqual([window, expected])
    }
  })

  it('centres on the own token on request', () => {
    const onCentre = vi.fn()
    click(buttonNamed(viewport({ onCentre }), 'Centrar en mi ficha'))
    expect(onCentre).toHaveBeenCalledTimes(1)
  })
})

describe('the status line', () => {
  it('reports the orientation and both ends of the visible arc', () => {
    const arc = visibleSpaces(TOP_RIGHT, 0)
    const first = spaceAt(arc[0]).name
    const last = spaceAt(arc[arc.length - 1]).name
    const text = statusText(viewport({ window: TOP_RIGHT, turns: 0 }))
    expect([first, last]).toEqual(['Avenida Illinois', 'Chance'])
    expect(text).toContain('Orientación impresa')
    expect(text).toContain(first)
    expect(text).toContain(last)
  })

  it('reads the arc in circuit order even when it crosses GO', () => {
    const arc = visibleSpaces(ACROSS_GO, 0)
    const first = spaceAt(arc[0]).name
    const last = spaceAt(arc[arc.length - 1]).name
    const text = statusText(viewport({ window: ACROSS_GO, turns: 0 }))
    expect([first, last]).toEqual(['Avenida Pennsylvania', 'Avenida Oriental'])
    expect(text).toContain(first)
    expect(text).toContain(last)
  })

  it('reads the arc through the turn count, not only through the window', () => {
    // The same window holds a different run of spaces once the table is turned,
    // because a turn shifts every space ten places along the circuit (S4).
    const text = statusText(viewport({ window: TOP_RIGHT, turns: 1 }))
    expect(text).toContain('Un cuarto de vuelta')
    expect(text).toContain('Avenida Virginia')
    expect(text).toContain('Avenida Atlantic')
    expect(text).not.toBe(statusText(viewport({ window: TOP_RIGHT, turns: 0 })))
  })

  it('names one label per quarter turn and changes with the turn count', () => {
    const texts = ([0, 1, 2, 3] as const).map((turns) =>
      statusText(viewport({ window: TOP_RIGHT, turns })),
    )
    expect(texts.map((text) => text.split('·')[0]?.trim())).toEqual([
      'Orientación impresa',
      'Un cuarto de vuelta',
      'Media vuelta',
      'Tres cuartos de vuelta',
    ])
    expect(new Set(texts).size).toBe(4)
  })

  it('says the window is over the middle and names no space when nothing is visible', () => {
    expect(visibleSpaces(OVER_THE_CENTRE, 0)).toEqual([])
    const text = statusText(viewport({ window: OVER_THE_CENTRE, turns: 2 }))
    expect(text).toContain('centro de la mesa')
    expect(text).toContain('Media vuelta')
    expect(text).not.toContain('GO')
    expect(text).not.toContain('Avenida')
  })
})

describe('the middle of the table inside the window', () => {
  function overlayOf(tree: ReactElement): ReactElement | undefined {
    return hostElements(tree).find((element) =>
      ((element.props as { className?: string }).className ?? '')
        .split(/\s+/)
        .includes('monopoly-viewport-overlay'),
    )
  }

  it('pins the overlay inside the clipped frame', () => {
    const tree = viewport({ overlay: <span>Mesa de prueba</span> })
    const overlay = overlayOf(tree)
    expect(overlay).toBeDefined()
    // Inside the frame is what makes it stay put while the board pans: the frame
    // is the only thing that moves the board, and this is a child of it.
    expect(overlayOf(frameOf(tree))).toBeDefined()
    expect(renderToStaticMarkup(<>{overlay}</>)).toContain('Mesa de prueba')
  })

  it('clips only its children when no overlay is given', () => {
    expect(overlayOf(viewport({}))).toBeUndefined()
  })
})
