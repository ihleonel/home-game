type YourRoomActionsProps = {
  displayName: string
  markerLabel: string
  ownReady: boolean
  busy: boolean
  readyPending: boolean
  leavePending: boolean
  onToggleReady: () => void
  onLeave: () => void
}

export function YourRoomActions({
  displayName,
  markerLabel,
  ownReady,
  busy,
  readyPending,
  leavePending,
  onToggleReady,
  onLeave,
}: YourRoomActionsProps) {
  return (
    <section className="your-room-actions" aria-labelledby="your-status-title">
      <div className="your-identity">
        <p className="eyebrow" id="your-status-title">Tu estado en la sala</p>
        <p>
          {displayName}
          <span className="marker-chip your-marker">{markerLabel}</span>
        </p>
      </div>
      <div className="action-buttons">
        <button
          aria-pressed={ownReady}
          className={ownReady ? 'button button-ready is-ready' : 'button button-ready'}
          disabled={busy}
          onClick={onToggleReady}
          type="button"
        >
          {readyPending
            ? 'Actualizando…'
            : ownReady
              ? 'Marcar como no listo'
              : 'Marcar como listo'}
        </button>
        <button
          className="button button-quiet"
          disabled={busy || ownReady}
          onClick={onLeave}
          type="button"
        >
          {leavePending ? 'Saliendo…' : 'Salir de la sala'}
        </button>
      </div>
    </section>
  )
}
