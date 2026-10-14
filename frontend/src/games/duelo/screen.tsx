import { createElement } from 'react'
import type { ReactElement } from 'react'
import type { MatchRendererProps } from '../registry'
import { DueloMatch } from './DueloMatch'
import { parseDueloView } from './view'

/**
 * The ``duelo`` entry of the screen registry.
 *
 * It is the single place where the unvalidated payload becomes a typed
 * ``duelo`` view: the parser either recognizes it, or this returns ``null`` and
 * the caller renders its own notice. No cast and no component ever receives a
 * payload its game did not recognize.
 */
export function renderDueloMatch(props: MatchRendererProps): ReactElement | null {
  const view = parseDueloView(props.match.view)
  if (!view) return null
  return createElement(DueloMatch, { ...props, match: { ...props.match, view } })
}
