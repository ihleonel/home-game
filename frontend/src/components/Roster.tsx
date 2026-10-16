import type { Game, Participant } from '../api/types'
import { markerLabel, presenceLabel } from '../lib/format'
import { readRemainingSeconds, useReconnectCountdown } from '../lib/reconnectCountdown'

type RosterProps = {
  game: Game | undefined
  participants: Participant[]
}

type RosterPlayerProps = {
  game: Game | undefined
  participant: Participant
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
function RosterPlayer({ game, participant }: RosterPlayerProps) {
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
    </li>
  )
}

/**
 * The room list.
 *
 * No participant action starts the expulsion vote any more (S9/D3): the sweep
 * opens it on its own, so the roster only shows who is in the room.
 */
export function Roster({ game, participants }: RosterProps) {
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
              game={game}
              key={`${participant.joined_at}-${index}`}
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
