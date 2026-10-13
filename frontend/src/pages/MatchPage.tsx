import { Link, Navigate } from 'react-router-dom'
import { AppMessages } from '../components/AppMessages'
import { CatalogGate } from '../components/CatalogGate'
import { renderMatchScreen } from '../games/registry'
import { useCatalog } from '../state/catalogContext'
import { useRoomSession } from '../state/roomSessionContext'

/**
 * The game screen.
 *
 * It renders outside the site shell, so during a match the only thing on the
 * page is the game itself: no catalog, no roster, no footer. A finished match
 * keeps its result here and offers a client-side link back to the room, so the
 * socket is never torn down by a document navigation.
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

  const activeGame = games.find((game) => game.id === room?.game_id)

  if (!roomSession || !room) return <Navigate to="/" replace />
  if (!activeMatch) return <Navigate to={`/rooms/${room.game_id}`} replace />

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
