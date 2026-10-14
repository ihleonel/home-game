import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { requestJson } from '../api/client'
import type { Game } from '../api/types'
import { CatalogContext } from './catalogContext'

/**
 * Loads the game catalog once per mount and exposes it to every page.
 *
 * The catalog is app-level, not room-level: the waiting room and the game
 * screen both resolve a game's label and markers from it, and navigating
 * between them must not refetch it.
 */
export function CatalogProvider({ children }: { children: ReactNode }) {
  const [games, setGames] = useState<Game[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    let isCurrent = true

    async function loadHomeGame() {
      setIsLoading(true)
      setLoadError(null)
      try {
        const catalog = await requestJson<Game[]>('/api/games/')
        if (!isCurrent) return
        setGames(catalog)
      } catch (error) {
        if (isCurrent) {
          setLoadError(
            error instanceof Error ? error.message : 'No se ha podido cargar HomeGame.',
          )
        }
      } finally {
        if (isCurrent) setIsLoading(false)
      }
    }

    void loadHomeGame()
    return () => {
      isCurrent = false
    }
  }, [loadAttempt])

  return (
    <CatalogContext.Provider
      value={{
        games,
        isLoading,
        loadError,
        reload: () => setLoadAttempt((attempt) => attempt + 1),
      }}
    >
      {children}
    </CatalogContext.Provider>
  )
}
