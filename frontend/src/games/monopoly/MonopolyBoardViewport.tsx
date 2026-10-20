import type { CSSProperties, ReactNode } from 'react'
import { spaceAt } from './board'
import { canMoveWindow, visibleSpaces } from './viewport'
import type { QuarterTurns, ViewDirection, ViewWindow } from './viewport'

/**
 * The seat's frame around the board (S6, S9, S12 of
 * ``monopoly-seat-viewport.md``).
 *
 * This component knows nothing about the board it frames: it takes whatever it
 * is given as ``children`` and never imports ``MonopolyBoard``, so the panel can
 * pass the board or any future surface. It also knows nothing about pixels. The
 * window is published to the stylesheet as the origin of its top-left cell
 * through two custom properties on the frame, and the turn count through
 * ``data-turns``; the clipping, the translation and the cell size all live in
 * CSS, which is the next task's file.
 *
 * It is a pure function of its props, like the board: the state that moves the
 * window and turns the table lives in the panel, and every button only reports
 * the step it wants. That is what lets the tests render it with no DOM and
 * invoke the handlers by hand.
 */

/**
 * The orientation of the table after each quarter turn (S12).
 *
 * Turns are a re-indexation of the circuit (S4), not a rotation of the markup,
 * so these words name how far the table has been turned from the printed board
 * and never suggest that the text is sideways.
 */
const ORIENTATION_LABELS: Record<QuarterTurns, string> = {
  0: 'Orientación impresa',
  1: 'Un cuarto de vuelta',
  2: 'Media vuelta',
  3: 'Tres cuartos de vuelta',
}

/** The four manual steps of S9, in the order the controls must appear. */
const PAN_STEPS: readonly { direction: ViewDirection; label: string; glyph: string }[] = [
  { direction: 'up', label: 'Mover la ventana arriba', glyph: '↑' },
  { direction: 'down', label: 'Mover la ventana abajo', glyph: '↓' },
  { direction: 'left', label: 'Mover la ventana izquierda', glyph: '←' },
  { direction: 'right', label: 'Mover la ventana derecha', glyph: '→' },
]

/**
 * What the status line says (S12): the orientation and the visible arc.
 *
 * The arc is read as one run of consecutive spaces, opening on the space whose
 * predecessor is hidden, so a window that crosses GO reads "Avenida
 * Pennsylvania a Avenida Oriental" instead of an inverted range. An empty arc
 * means the window sits over the empty middle of the table, and the line says
 * so instead of inventing a first and a last space.
 */
function statusLine(window: ViewWindow, turns: QuarterTurns): string {
  const orientation = ORIENTATION_LABELS[turns]
  const arc = visibleSpaces(window, turns)
  if (arc.length === 0) {
    return `${orientation} · La ventana está sobre el centro de la mesa`
  }
  const first = spaceAt(arc[0]).name
  const last = spaceAt(arc[arc.length - 1]).name
  const span = first === last ? first : `${first} a ${last}`
  return `${orientation} · Tramo visible: ${span}`
}

/** The frame's style: the two hooks the stylesheet turns into a translation. */
function frameStyle(window: ViewWindow): CSSProperties & Record<string, string> {
  return {
    '--monopoly-viewport-row': String(window.row),
    '--monopoly-viewport-column': String(window.column),
  }
}

/**
 * Render the frame, the turn and pan controls and the status line.
 *
 * Turning and panning are reported, never applied here: the panel owns the
 * state. The pan buttons are disabled exactly at the border the step would
 * leave (S9), so the player sees the edge instead of a button that does
 * nothing, and "Orientación impresa" is expressed as a step back from the
 * current turn count, through the same callback as the two step buttons.
 */
export function MonopolyBoardViewport({
  turns,
  window,
  onRotate,
  onCentre,
  onPan,
  overlay,
  children,
}: {
  turns: QuarterTurns
  window: ViewWindow
  onRotate: (step: number) => void
  onCentre: () => void
  onPan: (direction: ViewDirection) => void
  overlay?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="monopoly-viewport">
      <div className="monopoly-viewport-turns">
        <button
          aria-label="Girar a la izquierda"
          className="monopoly-viewport-button monopoly-viewport-turn"
          onClick={() => onRotate(-1)}
          type="button"
        >
          ⟲
        </button>
        <button
          aria-label="Girar a la derecha"
          className="monopoly-viewport-button monopoly-viewport-turn"
          onClick={() => onRotate(1)}
          type="button"
        >
          ⟳
        </button>
        <button
          aria-label="Orientación impresa"
          className="monopoly-viewport-button monopoly-viewport-turn monopoly-viewport-printed"
          onClick={() => onRotate(-turns)}
          type="button"
        >
          Orientación impresa
        </button>
      </div>

      <div
        aria-label="Ventana del tablero de Monopoly"
        className="monopoly-viewport-frame"
        data-turns={turns}
        role="group"
        style={frameStyle(window)}
      >
        {children}
        {/*
          S10: the middle of the table, pinned in the hollow of the ring. A
          seven-cell window can never show the nine-cell centre of the board, and
          the hollow it does show would otherwise be a field of empty paper; the
          block that belongs there stays the centre of what the player sees and
          never scrolls away with the pan.
        */}
        {overlay !== undefined && <div className="monopoly-viewport-overlay">{overlay}</div>}
      </div>

      <div className="monopoly-viewport-pan">
        {PAN_STEPS.map(({ direction, label, glyph }) => (
          <button
            aria-label={label}
            className="monopoly-viewport-button monopoly-viewport-move"
            disabled={!canMoveWindow(window, direction)}
            key={direction}
            onClick={() => onPan(direction)}
            type="button"
          >
            {glyph}
          </button>
        ))}
        <button
          aria-label="Centrar en mi ficha"
          className="monopoly-viewport-button monopoly-viewport-centre"
          onClick={onCentre}
          type="button"
        >
          Centrar en mi ficha
        </button>
      </div>

      <p className="monopoly-viewport-status" role="status">
        {statusLine(window, turns)}
      </p>
    </div>
  )
}
