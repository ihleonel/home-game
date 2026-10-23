import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Game } from '../api/types'
import type { GuestIdentity } from '../lib/session'
import { IdentityForm } from './IdentityForm'

const game: Game = {
  id: 'duelo',
  label: 'Duelo',
  description: 'Piedra, papel o tijera.',
  markers: [{ id: 'sol', label: 'Sol' }],
}

const emptyIdentity: GuestIdentity = { displayName: '', gameMarker: '' }

function render(
  props: {
    identity?: GuestIdentity
    onSubmitAsSpectator?: () => void
  } = {},
): string {
  return renderToStaticMarkup(
    <IdentityForm
      busy={false}
      game={game}
      identity={props.identity ?? emptyIdentity}
      intent="create"
      onCancel={() => {}}
      onChange={() => {}}
      onSubmit={() => {}}
      onSubmitAsSpectator={props.onSubmitAsSpectator ?? (() => {})}
    />,
  )
}

describe('IdentityForm', () => {
  it('lets the spectator action skip the required identity fields', () => {
    const markup = render()

    expect(markup).toContain('value="spectator"')
    // React's static markup prints the camelCase name; HTML parses it
    // case-insensitively as the `formnovalidate` attribute.
    expect(markup.toLowerCase()).toContain('formnovalidate')
    expect(markup).toContain(
      'La plataforma te asigna un nombre y una ficha si entras como espectador.',
    )
  })

  it('renders the ordinary form when no spectator action is offered', () => {
    const markup = renderToStaticMarkup(
      <IdentityForm
        busy={false}
        game={game}
        identity={emptyIdentity}
        intent="join"
        onCancel={() => {}}
        onChange={() => {}}
        onSubmit={() => {}}
      />,
    )

    expect(markup).not.toContain('value="spectator"')
    expect(markup).not.toContain('La plataforma te asigna')
  })
})
