type CountdownOverlayProps = {
  seconds: number
  remainingSeconds: number
}

/**
 * The lobby countdown card.
 *
 * ``seconds`` is the stable total and ``remainingSeconds`` the live tick. The
 * sentence is announced from ``seconds`` so assistive tech is not told the
 * whole sentence every second.
 */
export function CountdownOverlay({ seconds, remainingSeconds }: CountdownOverlayProps) {
  return (
    <div className="countdown-overlay">
      <div className="countdown-card">
        <p className="eyebrow">La sala está lista</p>
        <p className="countdown-number" aria-hidden="true">
          {remainingSeconds > 0 ? remainingSeconds : '¡Ya!'}
        </p>
        <p className="countdown-message" role="status" aria-live="polite">
          {remainingSeconds > 0
            ? `La partida comienza en ${seconds} segundos.`
            : 'Iniciando la partida…'}
        </p>
      </div>
    </div>
  )
}
