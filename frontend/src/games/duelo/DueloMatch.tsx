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

/**
 * The stroke drawing of one pick, in a 48x48 box, shared by the pick cards and
 * the resolved round.
 *
 * Each choice keeps its own silhouette -- a closed fist, a flat hand, two
 * fingers held apart -- because shape is what makes the three plays tellable
 * apart without relying on hue. The drawings ship inline: the panel needs no
 * asset file, and ``stroke="currentColor"`` lets the stylesheet own the colour.
 */
const HAND_SHAPES: Record<string, string[]> = {
  rock: [
    'M14 24a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v6a10 10 0 0 1-10 10 10 10 0 0 1-10-10v-6Z',
    'M19 18v-3',
    'M24 18v-4',
    'M29 18v-3',
  ],
  paper: [
    'M17 26a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v4a7 7 0 0 1-14 0v-4Z',
    'M19.5 21v-9',
    'M24 21v-12',
    'M28.5 21v-10',
    'M31 25l5-4',
  ],
  scissors: [
    'M17 27a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v4a7 7 0 0 1-7 7 7 7 0 0 1-7-7v-4Z',
    'M20 22l-5-12',
    'M28 22l5-12',
  ],
}

/**
 * One pick drawn as a picture.
 *
 * It is always decorative: the wrapper carries ``aria-hidden``, so a screen
 * reader reaches the visible label instead of a picture it cannot describe,
 * and the shape is what a sighted player uses to tell the plays apart.
 */
function HandArt({ pick }: { pick: string }): ReactElement {
  const shapes = HAND_SHAPES[pick] ?? []
  return (
    <svg
      className="duelo-hand"
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      role="presentation"
    >
      {shapes.map((shape) => (
        <path d={shape} key={shape} />
      ))}
    </svg>
  )
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
 * One seat as a card of the arena: who it is, and the score the server reports.
 *
 * The score is the server's number rendered large, never a recomputed one, and
 * the card is highlighted only by comparing the seat id with ``view.you``.
 */
function seatCard(
  seatId: string,
  score: number,
  match: MatchState<DueloView>,
): ReactElement {
  const isYou = seatId === match.view.you
  return (
    <div
      className={isYou ? 'duelo-seat-card duelo-seat-card-you' : 'duelo-seat-card'}
      key={seatId}
    >
      {seatLabel(seatId, match)}
      <span className="duelo-score">{score}</span>
    </div>
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
 * The panel is an arena rather than a table: the seats sit above and below the
 * resolved round, and the scores are the server's numbers in badges. That
 * arrangement is presentation only -- the seats are ordered by ``view.you``
 * and every value still comes from ``view``.
 *
 * It deliberately carries no title of its own. The match screen already prints
 * the game's label as the page heading, so repeating it here would put the same
 * word twice on one screen for no new information.
 *
 * A finish by abandonment is left to the match screen, which renders the
 * runtime-level result; here the outcome line would only repeat it.
 */
export function DueloMatch({ match, busy, onPick }: MatchRendererProps<DueloView>) {
  const { view } = match
  const seated = typeof view.you === 'string' && view.you.length > 0
  const picked = typeof view.your_pick === 'string' && view.your_pick.length > 0
  const canPick = seated && !picked && !view.finished && match.version !== null

  // The own seat answers last, so the arena reads as a duel: the others come
  // first, the viewer's own card closes the list. A spectator has no seat and
  // keeps the server's own order.
  const seatIds = Object.keys(view.scores)
  const orderedSeats = seated
    ? [...seatIds.filter((seatId) => seatId !== view.you), ...seatIds.filter((seatId) => seatId === view.you)]
    : seatIds

  return (
    <section className="duelo-panel">
      <div className="duelo-round-row">
        <span className="duelo-round">{`Ronda ${view.round}`}</span>
      </div>

      <div className="duelo-arena">
        {orderedSeats.map((seatId) => seatCard(seatId, view.scores[seatId], match))}
      </div>

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
          <ul className="duelo-reveal-picks">
            {Object.entries(view.reveal.picks).map(([seatId, pick]) => (
              <li
                className={`duelo-reveal-pick duelo-hand-${pick}${
                  seatId === view.reveal?.winner ? ' duelo-reveal-pick-winner' : ''
                }`}
                key={seatId}
              >
                <span className="duelo-reveal-art" aria-hidden="true">
                  <HandArt pick={pick} />
                </span>
                <strong className="duelo-pick-label">{pickLabel(pick)}</strong>
                <span className="duelo-reveal-seat">{seatLabel(seatId, match)}</span>
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
        <div className="duelo-picks" role="group" aria-label="Elegí tu jugada">
          {PICK_CHOICES.map((choice) => {
            const chosen = view.your_pick === choice
            return (
              <button
                className={`duelo-pick duelo-hand-${choice}${
                  chosen ? ' duelo-pick-chosen' : ''
                }`}
                data-pick={choice}
                aria-pressed={chosen}
                disabled={busy || !canPick}
                key={choice}
                onClick={() => onPick(choice)}
                type="button"
              >
                <span className="duelo-pick-art" aria-hidden="true">
                  <HandArt pick={choice} />
                </span>
                <span className="duelo-pick-label">{PICK_LABELS[choice]}</span>
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}

function pickLabel(value: string | null): string {
  if (!value) return 'Sin elegir'
  return PICK_LABELS[value] ?? value
}
