import type { ReactNode } from 'react'
import { useCatalog } from '../state/catalogContext'

/**
 * Holds the page until the game catalog is available.
 *
 * Every page resolves a game's label and markers from the catalog, so the
 * loading and the failure state belong to the shell, not to each page.
 */
export function CatalogGate({ children }: { children: ReactNode }) {
  const { isLoading, loadError, reload } = useCatalog()

  if (isLoading) {
    return <p className="loading-message" role="status">Cargando juegos…</p>
  }
  if (loadError) {
    return (
      <section className="empty-state">
        <h2>HomeGame no está disponible</h2>
        <p>{loadError}</p>
        <button className="button button-primary" onClick={reload} type="button">
          Volver a intentarlo
        </button>
      </section>
    )
  }
  return <>{children}</>
}
