import { createElement } from 'react'
import type { ReactElement } from 'react'
import type { MatchRendererProps } from '../registry'
import { TaTeTiMatch } from './TaTeTiMatch'
import { parseTaTeTiView } from './view'

/**
 * The ``ta-te-ti`` entry of the screen registry.
 *
 * It is the single place where the unvalidated payload becomes a typed
 * ``ta-te-ti`` view: the parser either recognizes it, or this returns ``null``
 * and the caller renders its own notice. No cast and no component ever receives
 * a payload its game did not recognize.
 */
export function renderTaTeTiMatch(props: MatchRendererProps): ReactElement | null {
  const view = parseTaTeTiView(props.match.view)
  if (!view) return null
  return createElement(TaTeTiMatch, { ...props, match: { ...props.match, view } })
}
