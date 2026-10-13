/**
 * Transport helpers shared by every REST call the app makes.
 *
 * ``ApiError`` carries the HTTP status and the machine-readable ``code`` the
 * backend attaches, so callers can branch on ``stale_version`` without parsing
 * Spanish prose.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.name = 'ApiError'
  }
}

export function getErrorMessage(payload: unknown): string {
  if (typeof payload === 'object' && payload !== null) {
    const values = payload as Record<string, unknown>
    if (typeof values.detail === 'string') return values.detail
    for (const value of Object.values(values)) {
      if (typeof value === 'string') return value
      if (Array.isArray(value)) {
        const message = value.find((entry): entry is string => typeof entry === 'string')
        if (message) return message
      }
    }
  }
  return 'No se ha podido completar la solicitud. Inténtalo de nuevo.'
}

/**
 * Read the machine-readable ``code`` the games API attaches to a rejection.
 *
 * ``stale_version`` is the only value the client acts on differently; every
 * other rejection is shown from its ``detail`` and resynced the same way.
 */
export function getErrorCode(payload: unknown): string | null {
  if (typeof payload === 'object' && payload !== null) {
    const code = (payload as Record<string, unknown>).code
    if (typeof code === 'string') return code
  }
  return null
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  const payload: unknown =
    response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) {
    throw new ApiError(response.status, getErrorMessage(payload), getErrorCode(payload))
  }
  return payload as T
}
