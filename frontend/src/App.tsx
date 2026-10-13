import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import { SiteLayout } from './app/SiteLayout'
import { CatalogPage } from './pages/CatalogPage'
import { LobbyPage } from './pages/LobbyPage'
import { MatchPage } from './pages/MatchPage'
import { CatalogProvider } from './state/CatalogProvider'
import { RoomSessionProvider } from './state/RoomSessionProvider'

/**
 * App shell: the two providers wrap every route.
 *
 * Both sit above the router's views so navigating between the catalog, the
 * waiting room and the game screen never remounts them and never closes the
 * room socket. Routing stays client-side; no view ever reloads the document.
 */
function App() {
  return (
    <BrowserRouter>
      <CatalogProvider>
        <RoomSessionProvider>
          <Routes>
            <Route element={<SiteLayout />}>
              <Route path="/" element={<CatalogPage />} />
              <Route path="/rooms/:gameId" element={<LobbyPage />} />
            </Route>
            <Route path="/games/:gameId/match" element={<MatchPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </RoomSessionProvider>
      </CatalogProvider>
    </BrowserRouter>
  )
}

export default App
