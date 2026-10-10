import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type Marker = { id: string; label: string }
type Game = {
  id: string
  label: string
  description: string
  markers: Marker[]
}
type Participant = {
  display_name: string
  game_marker: string
  is_ready: boolean
  joined_at: string
}
type Room = {
  game_id: string
  status: string
  created_at: string
  updated_at: string
  participants: Participant[]
}
type RoomEnvelope = { room: Room }
type MembershipResponse = RoomEnvelope & { session_id: string }
type RoomIntent = 'create' | 'join'
type GuestIdentity = { displayName: string; gameMarker: string }
type RoomSession = GuestIdentity & {
  gameId: string
  sessionId: string
  isReady: boolean
}
type StoredRoomSession = Pick<RoomSession, 'gameId' | 'sessionId' | 'isReady'>
type PendingAction = RoomIntent | 'ready' | 'leave' | null

const DISPLAY_NAME_KEY = 'homegame:display-name'
const ROOM_SESSION_KEY = 'homegame:room-session'

class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

function getErrorMessage(payload: unknown, statusCode: number): string {
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
  return `The request failed (${statusCode}). Please try again.`
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  const payload: unknown =
    response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) {
    throw new ApiError(response.status, getErrorMessage(payload, response.status))
  }
  return payload as T
}

async function fetchActiveRoom(): Promise<Room | null> {
  try {
    const response = await requestJson<RoomEnvelope>('/api/rooms/active/')
    return response.room
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

function readSessionValue(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function writeSessionValue(key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    // The flow remains usable for this page even when browser storage is unavailable.
  }
}

function markerStorageKey(gameId: string): string {
  return `homegame:marker:${gameId}`
}

function readStoredIdentity(game: Game): GuestIdentity {
  const savedMarker = readSessionValue(markerStorageKey(game.id))
  return {
    displayName: readSessionValue(DISPLAY_NAME_KEY) ?? '',
    gameMarker:
      savedMarker && game.markers.some((marker) => marker.id === savedMarker)
        ? savedMarker
        : '',
  }
}

function readStoredRoomSession(gameId: string): StoredRoomSession | null {
  const savedSession = readSessionValue(ROOM_SESSION_KEY)
  if (!savedSession) return null

  try {
    const session = JSON.parse(savedSession) as Partial<StoredRoomSession>
    if (session.gameId !== gameId || typeof session.sessionId !== 'string') return null
    return {
      gameId,
      sessionId: session.sessionId,
      isReady: session.isReady === true,
    }
  } catch {
    return null
  }
}

function saveGuestSession(session: RoomSession): void {
  writeSessionValue(DISPLAY_NAME_KEY, session.displayName)
  writeSessionValue(markerStorageKey(session.gameId), session.gameMarker)
  writeSessionValue(
    ROOM_SESSION_KEY,
    JSON.stringify({
      gameId: session.gameId,
      sessionId: session.sessionId,
      isReady: session.isReady,
    } satisfies StoredRoomSession),
  )
}

function markerLabel(game: Game | undefined, markerId: string): string {
  return game?.markers.find((marker) => marker.id === markerId)?.label ?? markerId
}

type IdentityFormProps = {
  game: Game
  intent: RoomIntent
  identity: GuestIdentity
  busy: boolean
  onChange: (identity: GuestIdentity) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onCancel: () => void
}

function IdentityForm({
  game,
  intent,
  identity,
  busy,
  onChange,
  onSubmit,
  onCancel,
}: IdentityFormProps) {
  const prefix = intent === 'create' ? 'create' : 'join'

  return (
    <form className="identity-form" onSubmit={onSubmit}>
      <div className="form-heading">
        <div>
          <p className="eyebrow">{intent === 'create' ? 'New room' : 'Join room'}</p>
          <h3>{game.label}</h3>
        </div>
        <p className="form-note">Your game marker is your visual identity in this room.</p>
      </div>
      <div className="form-fields">
        <label className="form-field" htmlFor={`${prefix}-display-name`}>
          <span>Display name</span>
          <input
            id={`${prefix}-display-name`}
            autoComplete="nickname"
            maxLength={80}
            required
            value={identity.displayName}
            onChange={(event) =>
              onChange({ ...identity, displayName: event.currentTarget.value })
            }
          />
        </label>
        <label className="form-field" htmlFor={`${prefix}-game-marker`}>
          <span>Game marker</span>
          <select
            id={`${prefix}-game-marker`}
            required
            value={identity.gameMarker}
            onChange={(event) =>
              onChange({ ...identity, gameMarker: event.currentTarget.value })
            }
          >
            <option value="" disabled>
              Choose a marker
            </option>
            {game.markers.map((marker) => (
              <option key={marker.id} value={marker.id}>
                {marker.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="form-actions">
        <button className="button button-primary" disabled={busy} type="submit">
          {busy ? 'Connecting…' : intent === 'create' ? 'Create room' : 'Join room'}
        </button>
        <button className="button button-quiet" disabled={busy} onClick={onCancel} type="button">
          Cancel
        </button>
      </div>
    </form>
  )
}

function App() {
  const membershipRequestPending = useRef(false)
  const [games, setGames] = useState<Game[]>([])
  const [room, setRoom] = useState<Room | null>(null)
  const [roomSession, setRoomSession] = useState<RoomSession | null>(null)
  const [intent, setIntent] = useState<RoomIntent | null>(null)
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null)
  const [identity, setIdentity] = useState<GuestIdentity>({
    displayName: '',
    gameMarker: '',
  })
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadAttempt, setLoadAttempt] = useState(0)

  const activeGame = games.find((game) => game.id === room?.game_id)
  const selectedGame = games.find((game) => game.id === selectedGameId)
  const isJoined = roomSession?.gameId === room?.game_id
  const allReady = Boolean(room?.participants.length) &&
    room?.participants.every((participant) => participant.is_ready)

  useEffect(() => {
    let isCurrent = true

    async function loadHomeGame() {
      setIsLoading(true)
      setLoadError(null)
      try {
        const [catalog, activeRoom] = await Promise.all([
          requestJson<Game[]>('/api/games/'),
          fetchActiveRoom(),
        ])
        if (!isCurrent) return
        setGames(catalog)
        setRoom(activeRoom)
        setRoomSession((current) =>
          current && current.gameId === activeRoom?.game_id ? current : null,
        )
      } catch (error) {
        if (isCurrent) {
          setLoadError(
            error instanceof Error ? error.message : 'HomeGame could not be loaded.',
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

  async function refreshActiveRoom(): Promise<void> {
    try {
      const activeRoom = await fetchActiveRoom()
      setRoom(activeRoom)
      setRoomSession((current) =>
        current && current.gameId === activeRoom?.game_id ? current : null,
      )
      setIntent(null)
      setSelectedGameId(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The room could not be refreshed.')
    }
  }

  function selectGame(game: Game): void {
    if (membershipRequestPending.current) return
    const savedIdentity = readStoredIdentity(game)
    setIdentity(savedIdentity)
    setActionError(null)
    if (savedIdentity.displayName.trim() && savedIdentity.gameMarker) {
      setSelectedGameId(null)
      setIntent(null)
      void submitMembership('create', game, savedIdentity)
      return
    }
    setSelectedGameId(game.id)
    setIntent('create')
  }

  function startJoining(): void {
    if (!activeGame) return
    const savedIdentity = readStoredIdentity(activeGame)
    setIdentity(savedIdentity)
    setActionError(null)
    if (savedIdentity.displayName.trim() && savedIdentity.gameMarker) {
      void submitMembership('join', activeGame, savedIdentity)
    } else {
      setIntent('join')
    }
  }

  async function submitMembership(
    membershipIntent: RoomIntent,
    game: Game,
    guestIdentity: GuestIdentity,
  ): Promise<void> {
    if (membershipRequestPending.current) return
    const displayName = guestIdentity.displayName.trim()
    if (!displayName || !guestIdentity.gameMarker) {
      setActionError('Enter a display name and choose a game marker to continue.')
      return
    }

    membershipRequestPending.current = true
    const savedSession = readStoredRoomSession(game.id)
    const requestBody = {
      game_id: game.id,
      display_name: displayName,
      game_marker: guestIdentity.gameMarker,
      ...(savedSession ? { session_id: savedSession.sessionId } : {}),
    }

    setPendingAction(membershipIntent)
    setActionError(null)
    try {
      const path = membershipIntent === 'create' ? '/api/rooms/' : '/api/rooms/join/'
      const response = await requestJson<MembershipResponse>(path, {
        method: 'POST',
        body: JSON.stringify(requestBody),
      })
      const reusedSession = savedSession?.sessionId === response.session_id
      const nextSession: RoomSession = {
        gameId: game.id,
        sessionId: response.session_id,
        displayName,
        gameMarker: guestIdentity.gameMarker,
        isReady: reusedSession ? savedSession.isReady : false,
      }

      saveGuestSession(nextSession)
      setRoom(response.room)
      setRoomSession(nextSession)
      setIntent(null)
      setSelectedGameId(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The room request failed.')
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        void refreshActiveRoom()
      }
    } finally {
      membershipRequestPending.current = false
      setPendingAction(null)
    }
  }

  function submitIdentity(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    const game = intent === 'create' ? selectedGame : activeGame
    if (intent && game) void submitMembership(intent, game, identity)
  }

  function cancelIdentity(): void {
    setIntent(null)
    setSelectedGameId(null)
    setActionError(null)
  }

  async function toggleReady(): Promise<void> {
    if (!roomSession) return
    const isReady = !roomSession.isReady
    setPendingAction('ready')
    setActionError(null)
    try {
      const response = await requestJson<RoomEnvelope>('/api/rooms/ready/', {
        method: 'PATCH',
        body: JSON.stringify({ session_id: roomSession.sessionId, is_ready: isReady }),
      })
      const nextSession = { ...roomSession, isReady }
      saveGuestSession(nextSession)
      setRoom(response.room)
      setRoomSession(nextSession)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Readiness could not be updated.')
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        setRoomSession(null)
        void refreshActiveRoom()
      }
    } finally {
      setPendingAction(null)
    }
  }

  async function leaveRoom(): Promise<void> {
    if (!roomSession) return
    setPendingAction('leave')
    setActionError(null)
    try {
      await requestJson<void>('/api/rooms/leave/', {
        method: 'POST',
        body: JSON.stringify({ session_id: roomSession.sessionId }),
      })
      setRoomSession(null)
      await refreshActiveRoom()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The room could not be left.')
      if (error instanceof ApiError && error.status === 404) {
        setRoomSession(null)
        void refreshActiveRoom()
      }
    } finally {
      setPendingAction(null)
    }
  }

  const busy = pendingAction !== null

  return (
    <main className="app-shell">
      <header className="site-header">
        <div className="brand-mark" aria-hidden="true">HG</div>
        <div>
          <p className="eyebrow">HomeGame</p>
          <h1>Pick a game. Play together.</h1>
        </div>
      </header>

      {actionError && <p className="message message-error" role="alert">{actionError}</p>}

      {isLoading ? (
        <p className="loading-message" role="status">Loading games and room…</p>
      ) : loadError ? (
        <section className="empty-state">
          <h2>HomeGame is unavailable</h2>
          <p>{loadError}</p>
          <button
            className="button button-primary"
            onClick={() => setLoadAttempt((attempt) => attempt + 1)}
            type="button"
          >
            Try again
          </button>
        </section>
      ) : room ? (
        <section className="room-panel" aria-labelledby="active-room-title">
          <div className="room-heading">
            <div>
              <p className="eyebrow">Active room</p>
              <h2 id="active-room-title">{activeGame?.label ?? room.game_id}</h2>
              <p className="room-description">
                {activeGame?.description ?? 'Guests are together in the current game room.'}
              </p>
            </div>
            <span className="room-status">Room open</span>
          </div>

          <div className={allReady ? 'ready-summary is-all-ready' : 'ready-summary'} role="status">
            {allReady
              ? 'Everyone in the room is ready.'
              : `${room.participants.length} ${room.participants.length === 1 ? 'guest' : 'guests'} in the room`}
          </div>

          <section className="roster-section" aria-labelledby="roster-title">
            <div className="section-heading">
              <h3 id="roster-title">Players</h3>
              <span>{room.participants.length}</span>
            </div>
            {room.participants.length > 0 ? (
              <ul className="roster-list">
                {room.participants.map((participant, index) => (
                  <li className="roster-item" key={`${participant.joined_at}-${index}`}>
                    <span className="marker-chip">
                      {markerLabel(activeGame, participant.game_marker)}
                    </span>
                    <span className="player-name">{participant.display_name}</span>
                    <span className={participant.is_ready ? 'ready-badge is-ready' : 'ready-badge'}>
                      {participant.is_ready ? 'Ready' : 'Not ready'}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="quiet-copy">The room is waiting for its first guest.</p>
            )}
          </section>

          {isJoined && roomSession ? (
            <section className="your-room-actions" aria-labelledby="your-status-title">
              <div className="your-identity">
                <p className="eyebrow" id="your-status-title">Your room status</p>
                <p>
                  {roomSession.displayName}
                  <span className="marker-chip your-marker">
                    {markerLabel(activeGame, roomSession.gameMarker)}
                  </span>
                </p>
              </div>
              <div className="action-buttons">
                <button
                  aria-pressed={roomSession.isReady}
                  className={roomSession.isReady ? 'button button-ready is-ready' : 'button button-ready'}
                  disabled={busy}
                  onClick={() => void toggleReady()}
                  type="button"
                >
                  {pendingAction === 'ready'
                    ? 'Updating…'
                    : roomSession.isReady
                      ? 'Ready · mark not ready'
                      : 'Mark ready'}
                </button>
                <button
                  className="button button-quiet"
                  disabled={busy}
                  onClick={() => void leaveRoom()}
                  type="button"
                >
                  {pendingAction === 'leave' ? 'Leaving…' : 'Leave room'}
                </button>
              </div>
            </section>
          ) : intent === 'join' && activeGame ? (
            <IdentityForm
              busy={busy}
              game={activeGame}
              identity={identity}
              intent="join"
              onCancel={cancelIdentity}
              onChange={setIdentity}
              onSubmit={submitIdentity}
            />
          ) : (
            <div className="join-actions">
              <p className="quiet-copy">Join the current room to take part in the lobby.</p>
              <button
                className="button button-primary"
                disabled={busy || !activeGame}
                onClick={startJoining}
                type="button"
              >
                Join {activeGame?.label ?? 'this room'}
              </button>
            </div>
          )}
        </section>
      ) : (
        <section className="catalog-section" aria-labelledby="catalog-title">
          <div className="section-intro">
            <p className="eyebrow">Game catalog</p>
            <h2 id="catalog-title">Choose what to play</h2>
            <p>A guest room opens when the first player chooses a game.</p>
          </div>

          {games.length > 0 ? (
            <div className="game-grid">
              {games.map((game) => (
                <article className="game-card" key={game.id}>
                  <div className="game-card-symbol" aria-hidden="true">
                    {game.label.slice(0, 1)}
                  </div>
                  <h3>{game.label}</h3>
                  <p>{game.description}</p>
                  <div className="marker-options" aria-label={`${game.label} markers`}>
                    {game.markers.map((marker) => (
                      <span className="marker-chip" key={marker.id}>{marker.label}</span>
                    ))}
                  </div>
                  <button
                    className="button button-primary"
                    disabled={busy}
                    onClick={() => selectGame(game)}
                    type="button"
                  >
                    Choose game
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <p className="quiet-copy">No games are available right now.</p>
          )}

          {intent === 'create' && selectedGame && (
            <IdentityForm
              busy={busy}
              game={selectedGame}
              identity={identity}
              intent="create"
              onCancel={cancelIdentity}
              onChange={setIdentity}
              onSubmit={submitIdentity}
            />
          )}
        </section>
      )}

      <footer className="site-footer">A small room for a good game night.</footer>
    </main>
  )
}

export default App
