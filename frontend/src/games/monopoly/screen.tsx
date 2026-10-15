import { createElement } from 'react'
import type { ReactElement } from 'react'
import type { MatchRendererProps } from '../registry'
import { MonopolyPanel } from './MonopolyPanel'
import { parseMonopolyView } from './view'

/**
 * The ``monopoly`` entry of the screen registry.
 *
 * It is the single place where the unvalidated payload becomes a typed
 * ``monopoly`` view: the parser either recognizes it, or this returns ``null``
 * and the caller renders its own notice. No cast and no component ever receives
 * a payload its game did not recognize.
 */
export function renderMonopolyMatch(props: MatchRendererProps): ReactElement | null {
  const view = parseMonopolyView(props.match.view)
  if (!view) return null
  return createElement(MonopolyPanel, { ...props, match: { ...props.match, view } })
}
