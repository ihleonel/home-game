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
  onCancel: () => void
}

export function IdentityForm({
  game,
  intent,
  identity,
  busy,
  onChange,
  onSubmit,
  onCancel,
}: IdentityFormProps) {
  const prefix = intent === 'create' ? 'create' : 'join'

  return (
    <form className="identity-form" onSubmit={onSubmit}>
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
      <div className="form-actions">
        <button className="button button-primary" disabled={busy} type="submit">
          {busy ? 'Conectando…' : 'Entrar en la sala'}
        </button>
        <button className="button button-quiet" disabled={busy} onClick={onCancel} type="button">
          Cancelar
        </button>
      </div>
    </form>
  )
}
