import type { ReactElement } from 'react'
import type { MatchSeatRosterEntry } from '../matchRoster'
import type { MatchRendererProps, MatchState } from '../registry'
import type { TaTeTiView } from './view'
import './ta-te-ti.css'

/**
 * One seat named from the server roster.
 *
 * The name and the marker label are the fields the server sent (S1/S3): the
 * client never maps a ``game_marker`` to a label and never crosses the room
 * roster with the match seats. A seat the roster does not name reads
 * ``Jugador``, never a fabricated seat number, and the only comparison allowed
 * is the own-seat ``(tú)`` suffix against ``view.you``.
 *
 * The board is X/O by seat (S2), so the ficha on this chip is identity only and
 * never reaches a cell.
 */
function seatLabel(seatId: string, match: MatchState<TaTeTiView>): ReactElement {
  const entry = match.roster.find((seat) => seat.seat_id === seatId)
  const name = entry ? entry.display_name : 'Jugador'
  const suffix = seatId === match.view.you ? ' (tú)' : ''
  return (
    <span className="ta-te-ti-seat">
      <span className="ta-te-ti-seat-name">{`${name}${suffix}`}</span>
      {entry && (
        <span className="marker-chip ta-te-ti-seat-marker">{entry.game_marker_label}</span>
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

function outcomeMessage(view: TaTeTiView, roster: MatchSeatRosterEntry[]): string {
  if (!view.winner) return 'Empate.'
  if (view.winner === view.you) return 'Has ganado la partida.'
  return `Ha ganado ${seatProse(view.winner, roster, view.you)}.`
}

/**
 * Render one ``ta-te-ti`` match from the server view.
 *
 * The component decides nothing about the game: it does not compute a line, it
 * does not decide a turn and it never reads a mark the server did not send.
 * Every statement it makes is a field of ``view``. A cell renders the symbol the
 * server assigned to its owning seat (X for the first seat, O for the second)
 * and is enabled only while the server says this session holds the turn, the
 * cell is free, the match is not finished and a version is known.
 *
 * A finish by abandonment is left to the match screen, which renders the
 * runtime-level result; here the outcome line would only repeat it.
 */
export function TaTeTiMatch({ match, busy, onPick }: MatchRendererProps<TaTeTiView>) {
  const { view } = match
  const seated = typeof view.you === 'string' && view.you.length > 0

  return (
    <section className="ta-te-ti-panel" aria-labelledby="ta-te-ti-panel-title">
      <div className="ta-te-ti-heading">
        <div>
          <p className="eyebrow">Partida en curso</p>
          <h3 id="ta-te-ti-panel-title">Ta-te-ti</h3>
        </div>
        <span className="ta-te-ti-turn">
          {view.turn === null ? 'Sin turno' : 'Un turno en juego'}
        </span>
      </div>

      <ul className="ta-te-ti-players">
        {Object.keys(view.symbols).map((seatId) => (
          <li key={seatId}>
            {seatLabel(seatId, match)}
            <strong className="ta-te-ti-symbol">{view.symbols[seatId]}</strong>
          </li>
        ))}
      </ul>

      <div className="ta-te-ti-board">
        {view.board.map((cell, index) => {
          const winning = view.winner_line?.includes(index) ?? false
          const canPick =
            !busy &&
            seated &&
            view.turn === view.you &&
            cell === null &&
            !view.finished &&
            match.version !== null
          return (
            <button
              aria-label={`Celda ${index}`}
              className={winning ? 'ta-te-ti-cell ta-te-ti-cell-winning' : 'ta-te-ti-cell'}
              disabled={!canPick}
              key={index}
              onClick={() => onPick(String(index))}
              type="button"
            >
              <span className="ta-te-ti-cell-symbol">
                {cell === null ? '' : (view.symbols[cell] ?? '')}
              </span>
            </button>
          )
        })}
      </div>

      {view.finished ? (
        view.ended_by_abandon ? null : (
          <p className="ta-te-ti-outcome" role="status">{outcomeMessage(view, match.roster)}</p>
        )
      ) : (
        <p className="ta-te-ti-progress" role="status">
          {view.turn === null
            ? 'Esperando el próximo turno.'
            : `Turno de ${seatProse(view.turn, match.roster, view.you)}.`}
        </p>
      )}
    </section>
  )
}
