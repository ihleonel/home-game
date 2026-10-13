import { createContext, useContext } from 'react'
import type { Game } from '../api/types'

export type CatalogContextValue = {
  games: Game[]
  isLoading: boolean
  loadError: string | null
  reload: () => void
}

export const CatalogContext = createContext<CatalogContextValue | null>(null)

export function useCatalog(): CatalogContextValue {
  const value = useContext(CatalogContext)
  if (value === null) {
    throw new Error('useCatalog must be used inside a CatalogProvider.')
  }
  return value
}
