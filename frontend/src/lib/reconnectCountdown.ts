import { useEffect, useState } from 'react'

type ReconnectCountdown = {
  remainingSeconds: number
}

/**
 * Read a server-sent reconnect window without trusting its shape.
 *
 * Only a whole number greater than or equal to zero survives; a string, a
 * decimal, a negative or a missing value becomes ``null``, so a bad payload
 * costs the countdown, not the screen -- the same guard the match seat parser
 * applies to ``remaining_seconds`` (S8).
 */
export function readRemainingSeconds(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    return null
  }
  return value
}

/**
 * Count a reconnect window down locally, once a second.
 *
 * The server owns the deadline and sends the whole seconds left (S8); the
 * screen only replays it, so the number moves without waiting for a new frame.
 * A new server value re-arms the count during render and a null clears it, so
 * the latest value always wins. Each value arms a fresh countdown object, and a
 * tick carries the object it belongs to as its run id, so a tick left over from
 * a previous value can never decrement a freshly armed one -- the same guard the
 * lobby countdown draws from its run id.
 *
 * It is shared by the match screen (the countdown of the rival's seat) and by
 * the room roster (the countdown of a reconnecting participant), so both
 * surfaces replay the same server value the same way.
 */
export function useReconnectCountdown(remainingSeconds: number | null): number | null {
  const [countdown, setCountdown] = useState<ReconnectCountdown | null>(null)
  const [armedFor, setArmedFor] = useState<number | null>(null)

  if (remainingSeconds !== armedFor) {
    setArmedFor(remainingSeconds)
    setCountdown(typeof remainingSeconds === 'number' ? { remainingSeconds } : null)
  }

  useEffect(() => {
    if (!countdown || countdown.remainingSeconds <= 0) return
    const armed = countdown
    const timeout = window.setTimeout(() => {
      setCountdown((current) =>
        current === armed && current.remainingSeconds > 0
          ? { remainingSeconds: current.remainingSeconds - 1 }
          : current,
      )
    }, 1000)
    return () => window.clearTimeout(timeout)
  }, [countdown])

  return countdown ? countdown.remainingSeconds : null
}
