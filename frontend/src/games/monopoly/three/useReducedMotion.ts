/**
 * Whether the player asked the system for less motion.
 *
 * Shared by the dice and the pieces: both animate, both are decoration over a
 * fact the screen already states, and both must stop when the preference is on.
 * ``useSyncExternalStore`` and not an effect with state, because the project's
 * lint rule forbids setting state straight from an effect and a media query is
 * exactly an external store: it has a current value and it changes.
 */

import { useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

/** Whether the environment can answer the query at all. */
function canAsk(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (!canAsk()) return () => {}
      const query = window.matchMedia(QUERY)
      query.addEventListener('change', onChange)
      return () => query.removeEventListener('change', onChange)
    },
    () => (canAsk() ? window.matchMedia(QUERY).matches : false),
    () => false,
  )
}
