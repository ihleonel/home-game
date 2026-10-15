type SpectatorActionsProps = {
  displayName: string
  markerLabel: string
  busy: boolean
  canRequestSeat: boolean
  reason: string | null
  requestPending: boolean
  leavePending: boolean
  onRequestSeat: () => void
  onLeave: () => void
}

/**
 * The spectator's controls inside the lobby (S8).
 *
 * It mirrors ``YourRoomActions``: the same identity block and the same button
 * row, but a spectator never sees the ready control. "Quiero jugar" is the
 * explicit promotion request (S5); it is disabled whenever the room cannot
 * grant a seat, and the matching reason is stated as quiet copy instead of
 * leaving the spectator guessing.
 */
export function SpectatorActions({
  displayName,
  markerLabel,
  busy,
  canRequestSeat,
  reason,
  requestPending,
  leavePending,
  onRequestSeat,
  onLeave,
}: SpectatorActionsProps) {
  return (
    <section
      className="your-room-actions spectator-actions"
      aria-labelledby="spectator-status-title"
    >
      <div className="your-identity">
        <p className="eyebrow" id="spectator-status-title">Tu estado en la sala</p>
        <p>
          {displayName}
          <span className="marker-chip your-marker">{markerLabel}</span>
        </p>
        {reason && <p className="quiet-copy spectator-reason">{reason}</p>}
      </div>
      <div className="action-buttons">
        <button
          className="button button-primary"
          disabled={busy || !canRequestSeat}
          onClick={onRequestSeat}
          type="button"
        >
          {requestPending ? 'Pidiendo asiento…' : 'Quiero jugar'}
        </button>
        <button
          className="button button-quiet"
          disabled={busy}
          onClick={onLeave}
          type="button"
        >
          {leavePending ? 'Saliendo…' : 'Salir de la sala'}
        </button>
      </div>
    </section>
  )
}
