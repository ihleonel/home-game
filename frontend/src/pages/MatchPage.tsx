import { Link, Navigate } from 'react-router-dom'
import { AppMessages } from '../components/AppMessages'
import { CatalogGate } from '../components/CatalogGate'
import { useMatchPresence } from '../games/matchPresence'
import { renderMatchScreen } from '../games/registry'
import type { MatchView } from '../games/registry'
import { useCatalog } from '../state/catalogContext'
import { useRoomSession } from '../state/roomSessionContext'

/**
 * The abandonment result in player-facing Spanish.
 *
 * ``winner`` is the seat the game itself declared, so the result is read from
 * the server view and never recomputed here. A spectator has no ``you`` to
 * compare against and gets the neutral sentence.
 */
function abandonmentOutcome(view: MatchView): string {
  if (!view.winner) return 'La partida ha terminado por abandono.'
  if (typeof view.you !== 'string') {
    return 'La partida ha terminado por abandono de uno de los jugadores.'
  }
  return view.winner === view.you
    ? 'Victoria por abandono: tu rival no ha vuelto a conectarse.'
    : 'Derrota por abandono: no has vuelto a conectarte a tiempo.'
}

/**
 * The game screen.
 *
 * It renders outside the site shell, so during a match the only thing on the
 * page is the game itself: no catalog, no roster, no footer. A finished match
 * keeps its result here and offers a client-side link back to the room, so the
 * socket is never torn down by a document navigation.
 *
 * The disconnect notice is a runtime concern, not a game one: it reads the
 * seat presence the provider receives on the match frames (S1/S6) and shows
 * the same sentences for every registered game. The abandonment result is
 * shown here too, from the ``ended_by_abandon`` flag the game sets in its view.
 */
export function MatchPage() {
  const { games } = useCatalog()
  const {
    room,
    roomSession,
    activeMatch,
    matchRendererAvailable,
    busy,
    actionError,
    connectionError,
    voteNotice,
    submitPick,
  } = useRoomSession()
  const seatPresence = useMatchPresence()

  const activeGame = games.find((game) => game.id === room?.game_id)

  if (!roomSession || !room) return <Navigate to="/" replace />
  if (!activeMatch) return <Navigate to={`/rooms/${room.game_id}`} replace />

  const seated = typeof activeMatch.view.you === 'string'
  const rivalLabel = seated ? 'Tu rival' : 'Un jugador'
  const opponentSeats = seatPresence.filter(
    (seat) => !seated || seat.index !== activeMatch.seatIndex,
  )
  const rivalReconnecting = opponentSeats.some((seat) => seat.presence === 'reconnecting')
  const rivalInactive = opponentSeats.some((seat) => seat.presence === 'inactive')
  const matchOngoing = !activeMatch.view.finished

  return (
    <main className="match-screen">
      <header className="match-screen-header">
        <div>
          <p className="eyebrow">Partida en curso</p>
          <h1>{activeGame?.label ?? 'Partida'}</h1>
        </div>
      </header>

      <AppMessages
        actionError={actionError}
        connectionError={connectionError}
        countdownNotice={null}
        voteNotice={voteNotice}
      />

      {matchOngoing && rivalReconnecting && (
        <p className="message message-info" role="status">
          {`${rivalLabel} se ha desconectado. Está dentro de la ventana de reconexión: si no vuelve a tiempo, la partida se resolverá por abandono.`}
        </p>
      )}

      {matchOngoing && rivalInactive && (
        <p className="message message-error" role="alert">
          {`${rivalLabel} no ha vuelto a conectarse. La partida se resolverá por abandono.`}
        </p>
      )}

      {activeMatch.view.finished && activeMatch.view.ended_by_abandon && (
        <p className="message message-info" role="status">
          {abandonmentOutcome(activeMatch.view)}
        </p>
      )}

      <CatalogGate>
        {matchRendererAvailable ? (
          renderMatchScreen(room.game_id, {
            busy,
            match: activeMatch,
            onPick: (value) => void submitPick(value),
          })
        ) : (
          <section className="match-unavailable" aria-labelledby="match-unavailable-title">
            <h3 id="match-unavailable-title">Vista de partida no disponible</h3>
            <p className="quiet-copy">
              Este juego todavía no tiene una vista de partida en HomeGame.
            </p>
          </section>
        )}
      </CatalogGate>

      {activeMatch.view.finished && (
        <div className="match-screen-actions">
          <Link className="button button-primary" to={`/rooms/${room.game_id}`}>
            Volver a la sala
          </Link>
        </div>
      )}
    </main>
  )
}
