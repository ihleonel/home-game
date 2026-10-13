import { Outlet } from 'react-router-dom'
import { AppMessages } from '../components/AppMessages'
import { CatalogGate } from '../components/CatalogGate'
import { useRoomSession } from '../state/roomSessionContext'

/**
 * The shell shared by the catalog and the waiting room.
 *
 * The game screen is deliberately not inside it: a match takes the whole
 * viewport and brings its own chrome.
 */
export function SiteLayout() {
  const { actionError, connectionError, voteNotice, countdownNotice } = useRoomSession()

  return (
    <main className="app-shell">
      <header className="site-header">
        <div className="brand-mark" aria-hidden="true">HG</div>
        <div>
          <p className="eyebrow">HomeGame</p>
          <h1>Elige un juego para disfrutar en compañía.</h1>
        </div>
      </header>

      <AppMessages
        actionError={actionError}
        connectionError={connectionError}
        countdownNotice={countdownNotice}
        voteNotice={voteNotice}
      />

      <CatalogGate>
        <Outlet />
      </CatalogGate>

      <footer className="site-footer">Un espacio acogedor para disfrutar de una buena noche de juegos.</footer>
    </main>
  )
}
