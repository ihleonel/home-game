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
  participant_ref: string
  display_name: string
  game_marker: string
  is_ready: boolean
  presence: 'offline' | 'online' | 'reconnecting' | 'inactive'
  disconnected_at: string | null
  joined_at: string
}
type ExpulsionBallot = {
  participant_ref: string
  display_name: string
  choice: 'yes' | 'no' | null
}
type ExpulsionVote = {
  vote_ref: string
  target_ref: string
  target_display_name: string
  started_by_ref: string
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  resolution_reason: string
  started_at: string
  resolved_at: string | null
  eligible_count: number
  yes_count: number
  no_count: number
  ballots: ExpulsionBallot[]
}
type Room = {
  game_id: string
  status: string
  created_at: string
  updated_at: string
  participants: Participant[]
  expulsion_vote: ExpulsionVote | null
}
type RoomEnvelope = { room: Room }
type MembershipResponse = RoomEnvelope & {
  session_id: string
  participant_ref: string
}
type VoteResponse = RoomEnvelope & { vote: ExpulsionVote }
type RoomIntent = 'create' | 'join'
type GuestIdentity = { displayName: string; gameMarker: string }
type RoomSession = GuestIdentity & {
  gameId: string
  sessionId: string
  participantRef: string
  isReady: boolean
}
type StoredRoomSession = Pick<RoomSession, 'gameId' | 'sessionId' | 'isReady'>
type PendingAction = RoomIntent | 'ready' | 'leave' | 'vote' | null

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

function getErrorMessage(payload: unknown): string {
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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  const payload: unknown =
    response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) {
    throw new ApiError(response.status, getErrorMessage(payload))
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
  return game?.markers.find((marker) => marker.id === markerId)?.label ?? 'Ficha'
}

function presenceLabel(presence: Participant['presence']): string {
  const labels: Record<Participant['presence'], string> = {
    offline: 'Sin conexión',
    online: 'En línea',
    reconnecting: 'Reconectando…',
    inactive: 'Inactivo',
  }
  return labels[presence]
}

function voteChoiceLabel(choice: NonNullable<ExpulsionBallot['choice']>): string {
  return choice === 'yes' ? 'Sí' : 'No'
}

function expulsionVoteMessage(vote: ExpulsionVote): string {
  if (vote.status === 'pending') {
    return `Votación de expulsión: ${vote.yes_count} de ${vote.eligible_count} votos emitidos son favorables.`
  }
  if (vote.status === 'approved') return 'La votación de expulsión ha sido aprobada por unanimidad.'
  if (vote.status === 'rejected') return 'La votación de expulsión ha sido rechazada. El jugador permanece en la sala.'
  if (vote.resolution_reason === 'target_reconnected') {
    return 'La votación se ha cancelado porque el jugador se ha vuelto a conectar.'
  }
  if (vote.resolution_reason === 'target_left') {
    return 'La votación se ha cancelado porque el jugador propuesto ha salido de la sala.'
  }
  if (vote.resolution_reason === 'target_disconnected') {
    return 'La votación se ha cancelado porque ha cambiado la conexión del jugador propuesto.'
  }
  if (vote.resolution_reason === 'eligible_voter_left') {
    return 'La votación se ha cancelado porque un participante con derecho a voto ha salido de la sala.'
  }
  return 'La votación de expulsión se ha cancelado porque un participante con derecho a voto ya no está disponible.'
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
          <p className="eyebrow">{intent === 'create' ? 'Nueva sala' : 'Unirse a la sala'}</p>
          <h3 id={`identity-form-title-${prefix}`}>{game.label}</h3>
        </div>
        <p className="form-note">Tu ficha te identifica visualmente en esta sala.</p>
      </div>
      <div className="form-fields">
        <label className="form-field" htmlFor={`${prefix}-display-name`}>
          <span>Nombre visible</span>
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
          <span>Ficha del juego</span>
          <select
            id={`${prefix}-game-marker`}
            required
            value={identity.gameMarker}
            onChange={(event) =>
              onChange({ ...identity, gameMarker: event.currentTarget.value })
            }
          >
            <option value="" disabled>
              Elige una ficha
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
          {busy ? 'Conectando…' : intent === 'create' ? 'Crear sala' : 'Unirse a la sala'}
        </button>
        <button className="button button-quiet" disabled={busy} onClick={onCancel} type="button">
          Cancelar
        </button>
      </div>
    </form>
  )
}

function App() {
  const membershipRequestPending = useRef(false)
  const leavingRef = useRef(false)
  const identityDialogRef = useRef<HTMLDialogElement>(null)
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
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [voteNotice, setVoteNotice] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadAttempt, setLoadAttempt] = useState(0)

  const activeGame = games.find((game) => game.id === room?.game_id)
  const selectedGame = games.find((game) => game.id === selectedGameId)
  const isJoined = roomSession?.gameId === room?.game_id
  const currentParticipant = room?.participants.find(
    (participant) => participant.participant_ref === roomSession?.participantRef,
  )
  const activeExpulsionVote = room?.expulsion_vote ?? null
  const currentBallot = activeExpulsionVote?.ballots.find(
    (ballot) => ballot.participant_ref === roomSession?.participantRef,
  )
  const allReady = Boolean(room?.participants.length) &&
    room?.participants.every((participant) => participant.is_ready)

  useEffect(() => {
    const dialog = identityDialogRef.current
    if (intent === 'create' && selectedGame && dialog && !dialog.open) {
      dialog.showModal()
    }
  }, [intent, selectedGame])

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
      setActionError(error instanceof Error ? error.message : 'No se ha podido actualizar la sala.')
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
      setActionError('Escribe un nombre y elige una ficha para continuar.')
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
        participantRef: response.participant_ref,
        displayName,
        gameMarker: guestIdentity.gameMarker,
        isReady: reusedSession ? savedSession.isReady : false,
      }

      saveGuestSession(nextSession)
      leavingRef.current = false
      setRoom(response.room)
      setRoomSession(nextSession)
      setConnectionError(null)
      setVoteNotice(null)
      setIntent(null)
      setSelectedGameId(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'No se ha podido procesar la solicitud de sala.')
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
      setActionError(error instanceof Error ? error.message : 'No se ha podido actualizar tu estado de preparación.')
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
    leavingRef.current = true
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
      leavingRef.current = false
      setActionError(error instanceof Error ? error.message : 'No se ha podido salir de la sala.')
      if (error instanceof ApiError && error.status === 404) {
        setRoomSession(null)
        void refreshActiveRoom()
      }
    } finally {
      setPendingAction(null)
    }
  }

  async function startExpulsionVote(targetRef: string): Promise<void> {
    if (!roomSession) return
    setPendingAction('vote')
    setActionError(null)
    try {
      const response = await requestJson<VoteResponse>('/api/rooms/expulsion-votes/', {
        method: 'POST',
        body: JSON.stringify({
          session_id: roomSession.sessionId,
          target_ref: targetRef,
        }),
      })
      setRoom(response.room)
      setVoteNotice(expulsionVoteMessage(response.vote))
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'No se ha podido iniciar la votación.')
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        void refreshActiveRoom()
      }
    } finally {
      setPendingAction(null)
    }
  }

  async function castExpulsionBallot(
    voteRef: string,
    choice: 'yes' | 'no',
  ): Promise<void> {
    if (!roomSession) return
    setPendingAction('vote')
    setActionError(null)
    try {
      const response = await requestJson<VoteResponse>(
        `/api/rooms/expulsion-votes/${encodeURIComponent(voteRef)}/ballots/`,
        {
          method: 'POST',
          body: JSON.stringify({ session_id: roomSession.sessionId, choice }),
        },
      )
      setRoom(response.room)
      setVoteNotice(expulsionVoteMessage(response.vote))
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'No se ha podido registrar tu voto.')
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        void refreshActiveRoom()
      }
    } finally {
      setPendingAction(null)
    }
  }

  const sessionGameId = roomSession?.gameId ?? null
  const sessionId = roomSession?.sessionId ?? null
  const sessionDisplayName = roomSession?.displayName ?? null
  const sessionGameMarker = roomSession?.gameMarker ?? null

  useEffect(() => {
    if (!sessionGameId || !sessionId || !sessionDisplayName || !sessionGameMarker) return
    const gameId = sessionGameId
    const guestSessionId = sessionId
    const displayName = sessionDisplayName
    const gameMarker = sessionGameMarker
    leavingRef.current = false

    let cancelled = false
    let currentSocket: WebSocket | null = null
    let reconnectTimer: number | null = null
    let stableTimer: number | null = null
    let reconnectAttempts = 0
    const maxReconnectAttempts = 5

    function scheduleReconnect(): void {
      if (cancelled || leavingRef.current) return
      if (reconnectAttempts >= maxReconnectAttempts) {
        setConnectionError('No se ha podido restablecer la conexión. Sal de la sala y vuelve a entrar para intentarlo de nuevo.')
        return
      }
      const delay = Math.min(1000 * 2 ** reconnectAttempts, 8000)
      reconnectAttempts += 1
      reconnectTimer = window.setTimeout(() => void connect(true), delay)
    }

    async function connect(reconnecting: boolean): Promise<void> {
      if (cancelled || leavingRef.current) return

      if (reconnecting) {
        try {
          const response = await requestJson<MembershipResponse>('/api/rooms/join/', {
            method: 'POST',
            body: JSON.stringify({
              game_id: gameId,
              session_id: guestSessionId,
              display_name: displayName,
              game_marker: gameMarker,
            }),
          })
          if (cancelled || leavingRef.current) return

          const savedSession = readStoredRoomSession(gameId)
          const nextSession: RoomSession = {
            gameId,
            sessionId: response.session_id,
            participantRef: response.participant_ref,
            displayName,
            gameMarker,
            isReady:
              response.session_id === guestSessionId ? (savedSession?.isReady ?? false) : false,
          }
          saveGuestSession(nextSession)
          setRoom(response.room)
          setVoteNotice(
            response.room.expulsion_vote
              ? expulsionVoteMessage(response.room.expulsion_vote)
              : null,
          )
          if (response.session_id !== guestSessionId) {
            setRoomSession((current) =>
              current?.sessionId === guestSessionId ? nextSession : current,
            )
            return
          }
          setRoomSession((current) =>
            current?.sessionId === guestSessionId ? nextSession : current,
          )
        } catch (error) {
          if (cancelled || leavingRef.current) return
          if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
            setRoomSession((current) =>
              current?.sessionId === guestSessionId ? null : current,
            )
            setConnectionError(error.message)
            void fetchActiveRoom().then(setRoom).catch(() => undefined)
            return
          }
          scheduleReconnect()
          return
        }
      }

      if (cancelled || leavingRef.current) return
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const socketUrl = `${protocol}//${window.location.host}/ws/rooms/active/?session_id=${encodeURIComponent(guestSessionId)}`

      try {
        const socket = new WebSocket(socketUrl)
        currentSocket = socket

        socket.onopen = () => {
          setConnectionError(null)
          stableTimer = window.setTimeout(() => {
            reconnectAttempts = 0
          }, 10000)
        }

        socket.onmessage = (messageEvent) => {
          try {
            const message = JSON.parse(String(messageEvent.data)) as RoomEnvelope & {
              type?: string
              vote?: ExpulsionVote
            }
            if (
              message.room.game_id === gameId &&
              Array.isArray(message.room.participants)
            ) {
              setRoom(message.room)
            }
            if (message.vote) setVoteNotice(expulsionVoteMessage(message.vote))
          } catch {
            setConnectionError('No se ha podido leer una actualización de la sala.')
          }
        }

        socket.onerror = () => socket.close()
        socket.onclose = (closeEvent) => {
          if (currentSocket === socket) currentSocket = null
          if (stableTimer !== null) {
            window.clearTimeout(stableTimer)
            stableTimer = null
          }
          if (cancelled || leavingRef.current) return
          if (closeEvent.code === 4001) {
            setRoomSession((current) =>
              current?.sessionId === guestSessionId ? null : current,
            )
            return
          }
          scheduleReconnect()
        }
      } catch {
        scheduleReconnect()
      }
    }

    void connect(false)
    return () => {
      cancelled = true
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      if (stableTimer !== null) window.clearTimeout(stableTimer)
      if (currentSocket !== null) {
        currentSocket.onopen = null
        currentSocket.onmessage = null
        currentSocket.onerror = null
        currentSocket.onclose = null
        currentSocket.close(1000, 'Room session ended')
      }
    }
  }, [sessionDisplayName, sessionGameId, sessionGameMarker, sessionId])

  const busy = pendingAction !== null

  return (
    <main className="app-shell">
      <header className="site-header">
        <div className="brand-mark" aria-hidden="true">HG</div>
        <div>
          <p className="eyebrow">HomeGame</p>
          <h1>Elige un juego para disfrutar en compañía.</h1>
        </div>
      </header>

      {actionError && <p className="message message-error" role="alert">{actionError}</p>}
      {connectionError && <p className="message message-error" role="status">{connectionError}</p>}
      {voteNotice && <p className="message message-info" role="status">{voteNotice}</p>}

      {isLoading ? (
        <p className="loading-message" role="status">Cargando juegos y sala…</p>
      ) : loadError ? (
        <section className="empty-state">
          <h2>HomeGame no está disponible</h2>
          <p>{loadError}</p>
          <button
            className="button button-primary"
            onClick={() => setLoadAttempt((attempt) => attempt + 1)}
            type="button"
          >
            Volver a intentarlo
          </button>
        </section>
      ) : room ? (
        <section className="room-panel" aria-labelledby="active-room-title">
          <div className="room-heading">
            <div>
              <p className="eyebrow">Sala activa</p>
              <h2 id="active-room-title">{activeGame?.label ?? 'Sala de juego'}</h2>
              <p className="room-description">
                {activeGame?.description ?? 'Los jugadores están en la sala de la partida actual.'}
              </p>
            </div>
            <span className="room-status">Sala abierta</span>
          </div>

          <div className={allReady ? 'ready-summary is-all-ready' : 'ready-summary'} role="status">
            {allReady
              ? 'Todos los jugadores de la sala están listos.'
              : `${room.participants.length} ${room.participants.length === 1 ? 'jugador' : 'jugadores'} en la sala`}
          </div>

          <section className="roster-section" aria-labelledby="roster-title">
            <div className="section-heading">
              <h3 id="roster-title">Jugadores</h3>
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
                      {participant.is_ready ? 'Listo' : 'No está listo'}
                    </span>
                    <span className={`presence-badge presence-${participant.presence}`}>
                      {presenceLabel(participant.presence)}
                    </span>
                    {!activeExpulsionVote &&
                      isJoined &&
                      roomSession &&
                      currentParticipant?.presence === 'online' &&
                      participant.presence === 'inactive' &&
                      participant.participant_ref !== roomSession.participantRef && (
                        <button
                          className="button button-quiet vote-start-button"
                          disabled={busy}
                          onClick={() => void startExpulsionVote(participant.participant_ref)}
                          type="button"
                        >
                          Iniciar votación de expulsión
                        </button>
                      )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="quiet-copy">La sala espera a su primer jugador.</p>
            )}
          </section>

          {activeExpulsionVote && (
            <section className="vote-panel" aria-labelledby="vote-title">
              <div className="vote-heading">
                <div>
                  <p className="eyebrow">Votación unánime de expulsión</p>
                  <h3 id="vote-title">{activeExpulsionVote.target_display_name}</h3>
                </div>
                <span className="vote-count">
                  {activeExpulsionVote.yes_count} / {activeExpulsionVote.eligible_count} a favor
                </span>
              </div>
              <ul className="vote-ballots">
                {activeExpulsionVote.ballots.map((ballot) => (
                  <li key={ballot.participant_ref}>
                    <span>{ballot.display_name}</span>
                    <strong>{ballot.choice ? `Voto: ${voteChoiceLabel(ballot.choice)}` : 'Pendiente de voto'}</strong>
                  </li>
                ))}
              </ul>
              {roomSession?.participantRef === activeExpulsionVote.target_ref ? (
                <p className="quiet-copy">Eres la persona propuesta para la expulsión y no puedes votar.</p>
              ) : currentBallot?.choice ? (
                <p className="quiet-copy">Has votado: {voteChoiceLabel(currentBallot.choice)}.</p>
              ) : currentBallot && currentParticipant?.presence === 'online' ? (
                <div className="vote-actions">
                  <button
                    className="button button-primary"
                    disabled={busy}
                    onClick={() => void castExpulsionBallot(activeExpulsionVote.vote_ref, 'yes')}
                    type="button"
                  >
                    Votar a favor
                  </button>
                  <button
                    className="button button-quiet"
                    disabled={busy}
                    onClick={() => void castExpulsionBallot(activeExpulsionVote.vote_ref, 'no')}
                    type="button"
                  >
                    Votar en contra
                  </button>
                </div>
              ) : (
                <p className="quiet-copy">Solo pueden votar los participantes que estaban conectados cuando comenzó la votación.</p>
              )}
            </section>
          )}

          {isJoined && roomSession ? (
            <section className="your-room-actions" aria-labelledby="your-status-title">
              <div className="your-identity">
                <p className="eyebrow" id="your-status-title">Tu estado en la sala</p>
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
                    ? 'Actualizando…'
                    : roomSession.isReady
                      ? 'Marcar como no listo'
                      : 'Marcar como listo'}
                </button>
                <button
                  className="button button-quiet"
                  disabled={busy}
                  onClick={() => void leaveRoom()}
                  type="button"
                >
                  {pendingAction === 'leave' ? 'Saliendo…' : 'Salir de la sala'}
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
              <p className="quiet-copy">Únete a la sala actual para participar.</p>
              <button
                className="button button-primary"
                disabled={busy || !activeGame}
                onClick={startJoining}
                type="button"
              >
                Entrar en la sala
              </button>
            </div>
          )}
        </section>
      ) : (
        <section className="catalog-section" aria-labelledby="catalog-title">
          <div className="section-intro">
            <p className="eyebrow">Catálogo de juegos</p>
            <h2 id="catalog-title">Elige a qué jugar</h2>
            <p>La sala se abre cuando el primer jugador elige un juego.</p>
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
                  <div className="marker-options" aria-label={`Fichas de ${game.label}`}>
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
                    Elegir juego
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <p className="quiet-copy">No hay juegos disponibles en este momento.</p>
          )}

        </section>
      )}

      {intent === 'create' && selectedGame && (
        <dialog
          aria-labelledby="identity-form-title-create"
          className="identity-dialog"
          onCancel={(event) => {
            event.preventDefault()
            identityDialogRef.current?.close()
            cancelIdentity()
          }}
          ref={identityDialogRef}
        >
          <IdentityForm
            busy={busy}
            game={selectedGame}
            identity={identity}
            intent="create"
            onCancel={() => {
              identityDialogRef.current?.close()
              cancelIdentity()
            }}
            onChange={setIdentity}
            onSubmit={submitIdentity}
          />
        </dialog>
      )}

      <footer className="site-footer">Un espacio acogedor para disfrutar de una buena noche de juegos.</footer>
    </main>
  )
}

export default App
