import type { MatchRendererProps, MatchView } from '../registry'
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
 * A human label for a seat id.
 *
 * ``duelo`` names its seats ``seat-<index>``; every other id is shown as it
 * comes. The own seat is marked so a player can read the score list.
 */
function seatLabel(seatId: string, view: MatchView): string {
  const numbered = /^seat-(\d+)$/.exec(seatId)
  const label = numbered ? `Asiento ${Number(numbered[1]) + 1}` : seatId
  return seatId === view.you ? `${label} (tú)` : label
}

function outcomeMessage(view: MatchView): string {
  if (!view.winner) return 'La partida ha terminado.'
  if (view.winner === view.you) return 'Has ganado la partida.'
  return `Ha ganado ${seatLabel(view.winner, view)}.`
}

/**
 * Render one ``duelo`` match from the server view.
 *
 * The component decides nothing about the game: it does not compare picks, it
 * does not compute a round winner and it never reads an opponent's hidden
 * choice. Every statement it makes is a field of ``view``. The pick buttons
 * are enabled only while the server says this session occupies a seat, has not
 * picked this round, the match is not finished and a version is known.
 */
export function DueloMatch({ match, busy, onPick }: MatchRendererProps) {
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
            <span>{seatLabel(seatId, view)}</span>
            <strong>{score}</strong>
          </li>
        ))}
      </ul>

      {view.finished ? (
        <p className="duelo-outcome" role="status">{outcomeMessage(view)}</p>
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
                <span>{seatLabel(seatId, view)}</span>
                <strong>{pickLabel(pick)}</strong>
              </li>
            ))}
          </ul>
          <p className="duelo-reveal-winner">
            {view.reveal.winner
              ? `Ganó ${seatLabel(view.reveal.winner, view)}.`
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
