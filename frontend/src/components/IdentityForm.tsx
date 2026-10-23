import type { FormEvent } from 'react'
import type { Game, RoomIntent } from '../api/types'
import type { GuestIdentity } from '../lib/session'

type IdentityFormProps = {
  game: Game
  intent: RoomIntent
  identity: GuestIdentity
  busy: boolean
  onChange: (identity: GuestIdentity) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  /**
   * Optional explicit spectator entry (S4/S8). The dedicated handler is what
   * makes the second submit action appear: a caller that does not pass it
   * renders exactly the one-action form as before.
   */
  onSubmitAsSpectator?: () => void
  onCancel: () => void
}

export function IdentityForm({
  game,
  intent,
  identity,
  busy,
  onChange,
  onSubmit,
  onSubmitAsSpectator,
  onCancel,
}: IdentityFormProps) {
  const prefix = intent === 'create' ? 'create' : 'join'

  // Both buttons are real submit buttons, so the browser still validates the
  // required fields. The ``value`` tells the two actions apart, letting the
  // spectator path reach its dedicated handler without losing validation.
  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    const submitter = (event.nativeEvent as SubmitEvent).submitter
    if (
      onSubmitAsSpectator &&
      submitter instanceof HTMLButtonElement &&
      submitter.value === 'spectator'
    ) {
      event.preventDefault()
      onSubmitAsSpectator()
      return
    }
    onSubmit(event)
  }

  return (
    <form className="identity-form" onSubmit={handleSubmit}>
      <div className="form-heading">
        <div>
          <p className="eyebrow">Tu ficha</p>
          <h3 id={`identity-form-title-${prefix}`}>{game.label}</h3>
        </div>
        <p className="form-note">Tu ficha te identifica visualmente en esta sala.</p>
      </div>
      <div className="form-fields">
        <label className="form-field" htmlFor={`${prefix}-display-name`}>
          <span>Nombre visible</span>
          <input
            id={`${prefix}-display-name`}
            autoComplete="nickname"
            maxLength={80}
            required
            value={identity.displayName}
            onChange={(event) =>
              onChange({ ...identity, displayName: event.currentTarget.value })
            }
          />
        </label>
        <label className="form-field" htmlFor={`${prefix}-game-marker`}>
          <span>Ficha del juego</span>
          <select
            id={`${prefix}-game-marker`}
            required
            value={identity.gameMarker}
            onChange={(event) =>
              onChange({ ...identity, gameMarker: event.currentTarget.value })
            }
          >
            <option value="" disabled>
              Elige una ficha
            </option>
            {game.markers.map((marker) => (
              <option key={marker.id} value={marker.id}>
                {marker.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {onSubmitAsSpectator && (
        <p className="form-note">
          La plataforma te asigna un nombre y una ficha si entras como espectador.
        </p>
      )}
      <div className="form-actions">
        <button className="button button-primary" disabled={busy} type="submit">
          {busy ? 'Conectando…' : 'Entrar en la sala'}
        </button>
        {onSubmitAsSpectator && (
          <button
            className="button button-quiet"
            disabled={busy}
            // A spectator does not type a ficha: the platform assigns the
            // name and the marker, so this action must not be stopped by the
            // required fields of the player entry.
            formNoValidate
            type="submit"
            value="spectator"
          >
            Entrar como espectador
          </button>
        )}
        <button className="button button-quiet" disabled={busy} onClick={onCancel} type="button">
          Cancelar
        </button>
      </div>
    </form>
  )
}
