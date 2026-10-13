import type { Game, Participant } from '../api/types'
import { markerLabel, presenceLabel } from '../lib/format'

type RosterProps = {
  game: Game | undefined
  participants: Participant[]
  canStartExpulsionVote: (participant: Participant) => boolean
  busy: boolean
  onStartExpulsionVote: (participantRef: string) => void
}

export function Roster({
  game,
  participants,
  canStartExpulsionVote,
  busy,
  onStartExpulsionVote,
}: RosterProps) {
  return (
    <section className="roster-section" aria-labelledby="roster-title">
      <div className="section-heading">
        <h3 id="roster-title">Jugadores</h3>
        <span>{participants.length}</span>
      </div>
      {participants.length > 0 ? (
        <ul className="roster-list">
          {participants.map((participant, index) => (
            <li className="roster-item" key={`${participant.joined_at}-${index}`}>
              <span className="marker-chip">
                {markerLabel(game, participant.game_marker)}
              </span>
              <span className="player-name">{participant.display_name}</span>
              <span className={participant.is_ready ? 'ready-badge is-ready' : 'ready-badge'}>
                {participant.is_ready ? 'Listo' : 'No está listo'}
              </span>
              <span className={`presence-badge presence-${participant.presence}`}>
                {presenceLabel(participant.presence)}
              </span>
              {canStartExpulsionVote(participant) && (
                <button
                  className="button button-quiet vote-start-button"
                  disabled={busy}
                  onClick={() => onStartExpulsionVote(participant.participant_ref)}
                  type="button"
                >
                  Iniciar votación de expulsión
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="quiet-copy">La sala espera a su primer jugador.</p>
      )}
    </section>
  )
}
