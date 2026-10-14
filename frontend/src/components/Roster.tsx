import type { Game, Participant } from '../api/types'
import { markerLabel, presenceLabel } from '../lib/format'
import { readRemainingSeconds, useReconnectCountdown } from '../lib/reconnectCountdown'

type RosterProps = {
  game: Game | undefined
  participants: Participant[]
  canStartExpulsionVote: (participant: Participant) => boolean
  busy: boolean
  onStartExpulsionVote: (participantRef: string) => void
}

type RosterPlayerProps = {
  game: Game | undefined
  participant: Participant
  canStartExpulsionVote: (participant: Participant) => boolean
  busy: boolean
  onStartExpulsionVote: (participantRef: string) => void
}

/**
 * One player of the room list.
 *
 * It is its own component because the reconnect countdown is a hook: a hook
 * cannot run inside the list's ``map``, and a row that is not counting down
 * must not re-arm the tick of the row next to it. The countdown is armed from
 * the server's ``remaining_seconds`` in the room snapshot and only rendered
 * while there is time left; at zero the badge falls back to the presence the
 * server sent, so it never promises an expulsion at that exact instant (S8).
 */
function RosterPlayer({
  game,
  participant,
  canStartExpulsionVote,
  busy,
  onStartExpulsionVote,
}: RosterPlayerProps) {
  const reconnectSeconds = useReconnectCountdown(
    participant.presence === 'reconnecting'
      ? readRemainingSeconds(participant.remaining_seconds)
      : null,
  )

  return (
    <li className="roster-item">
      <span className="marker-chip">{markerLabel(game, participant.game_marker)}</span>
      <span className="player-name">{participant.display_name}</span>
      {participant.role === 'spectator' ? (
        <span className="spectator-badge">Espectador</span>
      ) : (
        <span className={participant.is_ready ? 'ready-badge is-ready' : 'ready-badge'}>
          {participant.is_ready ? 'Listo' : 'No está listo'}
        </span>
      )}
      <span className={`presence-badge presence-${participant.presence}`}>
        {presenceLabel(participant.presence)}
        {reconnectSeconds !== null && reconnectSeconds > 0 && (
          <span className="presence-countdown" role="timer">
            {`${reconnectSeconds} s`}
          </span>
        )}
      </span>
      {participant.role === 'player' && canStartExpulsionVote(participant) && (
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
  )
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
        <h3 id="roster-title">En la sala</h3>
        <span>{participants.length}</span>
      </div>
      {participants.length > 0 ? (
        <ul className="roster-list">
          {participants.map((participant, index) => (
            <RosterPlayer
              busy={busy}
              canStartExpulsionVote={canStartExpulsionVote}
              game={game}
              key={`${participant.joined_at}-${index}`}
              onStartExpulsionVote={onStartExpulsionVote}
              participant={participant}
            />
          ))}
        </ul>
      ) : (
        <p className="quiet-copy">La sala espera a su primer jugador.</p>
      )}
    </section>
  )
}
