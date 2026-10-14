import type { ReactElement } from 'react'
import type { MatchSeatRosterEntry } from '../matchRoster'
import type { MatchRendererProps, MatchState } from '../registry'
import type { DueloView } from './view'
import './duelo.css'

/**
 * Cosmetic Spanish labels for the three choices.
 *
 * The values are the server's own action values; the labels are presentation
 * only and never take part in deciding a round.
 */
const PICK_LABELS: Record<string, string> = {
  rock: 'Piedra',
  paper: 'Papel',
  scissors: 'Tijera',
}

const PICK_CHOICES = ['rock', 'paper', 'scissors']

function pickLabel(value: string | null): string {
  if (!value) return 'Sin elegir'
  return PICK_LABELS[value] ?? value
}

/**
 * One seat named from the server roster.
 *
 * The name and the marker label are the fields the server sent (S4): the
 * client never maps a ``game_marker`` to a label and never crosses the room
 * roster with the match seats. A seat the roster does not name reads
 * ``Jugador``, never a fabricated seat number (S3), and the only comparison
 * allowed is the own-seat ``(tú)`` suffix against ``view.you``.
 */
function seatLabel(seatId: string, match: MatchState<DueloView>): ReactElement {
  const entry = match.roster.find((seat) => seat.seat_id === seatId)
  const name = entry ? entry.display_name : 'Jugador'
  const suffix = seatId === match.view.you ? ' (tú)' : ''
  return (
    <span className="duelo-seat">
      <span className="duelo-seat-name">{`${name}${suffix}`}</span>
      {entry && (
        <span className="marker-chip duelo-seat-marker">{entry.game_marker_label}</span>
      )}
    </span>
  )
}

/**
 * The same seat as plain prose, for sentences: ``display_name (label)``.
 *
 * It uses only the server fields and the neutral ``Jugador`` fallback, so a
 * sentence can never read a seat number either.
 */
function seatProse(
  seatId: string,
  roster: MatchSeatRosterEntry[],
  you: string | undefined,
): string {
  const entry = roster.find((seat) => seat.seat_id === seatId)
  const name = entry
    ? `${entry.display_name} (${entry.game_marker_label})`
    : 'Jugador'
  return seatId === you ? `${name} (tú)` : name
}

function outcomeMessage(view: DueloView, roster: MatchSeatRosterEntry[]): string {
  if (!view.winner) return 'La partida ha terminado.'
  if (view.winner === view.you) return 'Has ganado la partida.'
  return `Ha ganado ${seatProse(view.winner, roster, view.you)}.`
}

/**
 * Render one ``duelo`` match from the server view.
 *
 * The component decides nothing about the game: it does not compare picks, it
 * does not compute a round winner and it never reads an opponent's hidden
 * choice. Every statement it makes is a field of ``view``. The pick buttons
 * are enabled only while the server says this session occupies a seat, has not
 * picked this round, the match is not finished and a version is known.
 *
 * A finish by abandonment is left to the match screen, which renders the
 * runtime-level result; here the outcome line would only repeat it.
 */
export function DueloMatch({ match, busy, onPick }: MatchRendererProps<DueloView>) {
  const { view } = match
  const seated = typeof view.you === 'string' && view.you.length > 0
  const picked = typeof view.your_pick === 'string' && view.your_pick.length > 0
  const canPick = seated && !picked && !view.finished && match.version !== null

  return (
    <section className="duelo-panel" aria-labelledby="duelo-panel-title">
      <div className="duelo-heading">
        <div>
          <p className="eyebrow">Partida en curso</p>
          <h3 id="duelo-panel-title">Duelo</h3>
        </div>
        <span className="duelo-round">Ronda {view.round}</span>
      </div>

      <ul className="duelo-scores">
        {Object.entries(view.scores).map(([seatId, score]) => (
          <li key={seatId}>
            {seatLabel(seatId, match)}
            <strong>{score}</strong>
          </li>
        ))}
      </ul>

      {view.finished ? (
        view.ended_by_abandon ? null : (
          <p className="duelo-outcome" role="status">{outcomeMessage(view, match.roster)}</p>
        )
      ) : seated ? (
        <p className="duelo-progress" role="status">
          {picked ? `Tu jugada: ${pickLabel(view.your_pick ?? null)}.` : 'Todavía no has elegido.'}{' '}
          {view.opponent_has_picked
            ? 'Tu rival ya ha elegido.'
            : 'Tu rival todavía no ha elegido.'}
        </p>
      ) : (
        <p className="duelo-progress" role="status">
          {view.both_picked
            ? 'Los dos jugadores ya han elegido.'
            : 'Todavía quedan jugadas por elegir.'}
        </p>
      )}

      {view.reveal && (
        <div className="duelo-reveal">
          <p className="duelo-reveal-title">
            Última ronda resuelta: {view.reveal.round}
          </p>
          <ul>
            {Object.entries(view.reveal.picks).map(([seatId, pick]) => (
              <li key={seatId}>
                {seatLabel(seatId, match)}
                <strong>{pickLabel(pick)}</strong>
              </li>
            ))}
          </ul>
          <p className="duelo-reveal-winner">
            {view.reveal.winner
              ? `Ganó ${seatProse(view.reveal.winner, match.roster, view.you)}.`
              : 'La ronda terminó en empate.'}
          </p>
        </div>
      )}

      {seated && !view.finished && (
        <div className="duelo-picks">
          {PICK_CHOICES.map((choice) => (
            <button
              className="button button-ready duelo-pick"
              disabled={busy || !canPick}
              key={choice}
              onClick={() => onPick(choice)}
              type="button"
            >
              {PICK_LABELS[choice]}
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
