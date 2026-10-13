import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { ApiError, requestJson } from './api/client'
import { fetchActiveRoom } from './api/rooms'
import type {
  Game,
  MatchEnvelope,
  MembershipResponse,
  Room,
  RoomEnvelope,
  RoomIntent,
  ServerMessage,
  VoteResponse,
} from './api/types'
import { AppMessages } from './components/AppMessages'
import { CountdownOverlay } from './components/CountdownOverlay'
import { ExpulsionVotePanel } from './components/ExpulsionVotePanel'
import { GameCatalog } from './components/GameCatalog'
import { IdentityForm } from './components/IdentityForm'
import { Roster } from './components/Roster'
import { YourRoomActions } from './components/YourRoomActions'
import { hasMatchRenderer, renderMatchScreen } from './games/registry'
import type { MatchState } from './games/registry'
import { expulsionVoteMessage, markerLabel } from './lib/format'
import { mergeMatch, mergeMatchEvent } from './lib/match'
import { readStoredIdentity, readStoredRoomSession, saveGuestSession } from './lib/session'
import type { GuestIdentity, RoomSession } from './lib/session'

type PendingAction = RoomIntent | 'ready' | 'leave' | 'vote' | 'pick' | null

/**
 * The shared lobby countdown this client is currently ticking.
 *
 * ``runId`` identifies the run this state belongs to, so a tick scheduled by
 * an older run can never decrement a newer one. The live sentence is announced
 * from ``seconds`` (the stable total), never from the decrementing
 * ``remainingSeconds``, so assistive tech is not told the whole sentence every
 * second.
 */
type MatchCountdown = {
  runId: number
  seconds: number
  remainingSeconds: number
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
  const [countdown, setCountdown] = useState<MatchCountdown | null>(null)
  const [countdownNotice, setCountdownNotice] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [match, setMatch] = useState<MatchState | null>(null)

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
  // Readiness is rendered from the room snapshot, not from this session's
  // stored copy: the backend resets every participant when a match finishes,
  // and that server state is what re-enables leaving the lobby.
  const ownReady = currentParticipant
    ? currentParticipant.is_ready
    : roomSession?.isReady ?? false
  // A session without a room has no match, so a previous match cannot leak
  // into a later room while its state is still in memory.
  const activeMatch = roomSession ? match : null
  const matchInProgress = Boolean(activeMatch && !activeMatch.view.finished)
  const matchRendererAvailable = room ? hasMatchRenderer(room.game_id) : false

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

  async function refreshActiveRoom(gameId: string, sessionId?: string): Promise<void> {
    try {
      const activeRoom = await fetchActiveRoom(gameId, sessionId)
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
    if (roomSession) {
      setActionError('Sal de la sala actual antes de elegir otro juego.')
      return
    }
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
    if (roomSession) {
      setActionError('Sal de la sala actual antes de elegir otro juego.')
      return
    }
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
      setMatch(null)
      setConnectionError(null)
      setVoteNotice(null)
      setIntent(null)
      setSelectedGameId(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'No se ha podido procesar la solicitud de sala.')
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        void refreshActiveRoom(game.id)
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
    const isReady = !ownReady
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
        void refreshActiveRoom(roomSession.gameId, roomSession.sessionId)
      }
    } finally {
      setPendingAction(null)
    }
  }

  async function resyncRoomReadiness(session: RoomSession): Promise<void> {
    try {
      const activeRoom = await fetchActiveRoom(session.gameId, session.sessionId)
      if (!activeRoom) return
      setRoom(activeRoom)
      const participant = activeRoom.participants.find(
        (entry) => entry.participant_ref === session.participantRef,
      )
      if (!participant || participant.is_ready === session.isReady) return
      const nextSession = { ...session, isReady: participant.is_ready }
      saveGuestSession(nextSession)
      setRoomSession((current) =>
        current?.sessionId === session.sessionId ? nextSession : current,
      )
    } catch {
      // Keep the current session; the action error already explains the rejection.
    }
  }

  async function leaveRoom(): Promise<void> {
    if (!roomSession) return
    if (ownReady) return
    leavingRef.current = true
    setPendingAction('leave')
    setActionError(null)
    try {
      await requestJson<void>('/api/rooms/leave/', {
        method: 'POST',
        body: JSON.stringify({ session_id: roomSession.sessionId }),
      })
      setRoomSession(null)
      setRoom(null)
      setMatch(null)
      setConnectionError(null)
      setVoteNotice(null)
    } catch (error) {
      leavingRef.current = false
      setActionError(error instanceof Error ? error.message : 'No se ha podido salir de la sala.')
      if (error instanceof ApiError && error.status === 404) {
        setRoomSession(null)
        setRoom(null)
        setMatch(null)
        setConnectionError(null)
        setVoteNotice(null)
      } else if (error instanceof ApiError && error.status === 409) {
        await resyncRoomReadiness(roomSession)
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
        void refreshActiveRoom(roomSession.gameId)
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
        void refreshActiveRoom(roomSession.gameId)
      }
    } finally {
      setPendingAction(null)
    }
  }

  const resyncMatch = useCallback(
    async (matchRef: string, sessionId: string): Promise<void> => {
      try {
        const response = await requestJson<MatchEnvelope>(
          `/api/matches/${encodeURIComponent(matchRef)}/?session_id=${encodeURIComponent(sessionId)}`,
        )
        setMatch((current) => mergeMatch(current, response))
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          setMatch((current) => (current?.matchRef === matchRef ? null : current))
          return
        }
        setActionError(
          error instanceof Error ? error.message : 'No se ha podido sincronizar la partida.',
        )
      }
    },
    [],
  )

  async function submitPick(value: string): Promise<void> {
    if (!roomSession || !match || match.version === null) return
    const { matchRef, version } = match
    setPendingAction('pick')
    setActionError(null)
    try {
      const response = await requestJson<MatchEnvelope>(
        `/api/matches/${encodeURIComponent(matchRef)}/actions/`,
        {
          method: 'POST',
          body: JSON.stringify({
            session_id: roomSession.sessionId,
            action_name: 'pick',
            action_value: value,
            expected_version: version,
          }),
        },
      )
      setMatch((current) => mergeMatch(current, response))
    } catch (error) {
      const stale = error instanceof ApiError && error.code === 'stale_version'
      setActionError(
        stale
          ? 'La partida cambió. Se ha sincronizado de nuevo el estado.'
          : error instanceof Error
            ? error.message
            : 'No se ha podido registrar tu jugada.',
      )
      // A stale version means this client composed the pick against an older
      // state; any other rejection still leaves the local view unconfirmed.
      // Both are resolved by re-reading the server rather than reconciling
      // locally, so the resync runs for either one.
      await resyncMatch(matchRef, roomSession.sessionId)
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
            void fetchActiveRoom(gameId, guestSessionId).then(setRoom).catch(() => undefined)
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
          if (leavingRef.current) return
          let message: ServerMessage
          try {
            message = JSON.parse(String(messageEvent.data)) as ServerMessage
          } catch {
            setConnectionError('No se ha podido leer una actualización de la sala.')
            return
          }
          if (
            message.room &&
            message.room.game_id === gameId &&
            Array.isArray(message.room.participants)
          ) {
            setRoom(message.room)
          }
          if (message.vote) setVoteNotice(expulsionVoteMessage(message.vote))
          const countdownFrame = message.countdown
          if (
            message.type === 'match_countdown' &&
            countdownFrame &&
            typeof countdownFrame.seconds === 'number' &&
            typeof countdownFrame.remaining_seconds === 'number'
          ) {
            setCountdown({
              runId: Date.now(),
              seconds: countdownFrame.seconds,
              remainingSeconds: countdownFrame.remaining_seconds,
            })
            setCountdownNotice(null)
          } else if (message.type === 'match_countdown_cancelled') {
            setCountdown(null)
            setCountdownNotice(
              countdownFrame?.reason === 'start_failed'
                ? 'La partida no ha podido comenzar. Vuelve a marcar que estás listo para intentarlo de nuevo.'
                : 'La cuenta regresiva se ha cancelado porque la sala ha cambiado.',
            )
          }
          if (
            message.type === 'match.snapshot' &&
            typeof message.match_ref === 'string' &&
            message.view
          ) {
            const matchRef = message.match_ref
            const view = message.view
            const seatIndex =
              typeof message.seat_index === 'number' ? message.seat_index : null
            setCountdown(null)
            setMatch((current) => ({
              matchRef,
              seatIndex,
              version: current && current.matchRef === matchRef ? current.version : null,
              view,
            }))
            // The snapshot names the match and carries its view, but no
            // version. One resync read fills the version in; this is the
            // reload resume path, not a second way to discover a match.
            void resyncMatch(matchRef, guestSessionId)
          } else if (
            message.type === 'match.event' &&
            typeof message.match_ref === 'string' &&
            message.view
          ) {
            const matchRef = message.match_ref
            const view = message.view
            const version =
              typeof message.version === 'number' ? message.version : null
            setCountdown(null)
            setMatch((current) => mergeMatchEvent(current, matchRef, version, view))
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
  }, [resyncMatch, sessionDisplayName, sessionGameId, sessionGameMarker, sessionId])

  // Tick locally from the received remaining seconds. Each tick schedules the
  // next one and the cleanup clears it, so the countdown stops the moment it is
  // cancelled, the match opens, or the component unmounts. The run id guards
  // against a stale tick decrementing a freshly armed run.
  useEffect(() => {
    if (!countdown || countdown.remainingSeconds <= 0) return
    const timeout = window.setTimeout(() => {
      setCountdown((current) =>
        current && current.runId === countdown.runId && current.remainingSeconds > 0
          ? { ...current, remainingSeconds: current.remainingSeconds - 1 }
          : current,
      )
    }, 1000)
    return () => window.clearTimeout(timeout)
  }, [countdown])

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

      <AppMessages
        actionError={actionError}
        connectionError={connectionError}
        countdownNotice={countdownNotice}
        voteNotice={voteNotice}
      />

      {isLoading ? (
        <p className="loading-message" role="status">Cargando juegos…</p>
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
      ) : (
        <>
      {room && (
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

          <Roster
            busy={busy}
            canStartExpulsionVote={(participant) =>
              !activeExpulsionVote &&
              isJoined &&
              roomSession !== null &&
              currentParticipant?.presence === 'online' &&
              participant.presence === 'inactive' &&
              participant.participant_ref !== roomSession.participantRef}
            game={activeGame}
            onStartExpulsionVote={(participantRef) => void startExpulsionVote(participantRef)}
            participants={room.participants}
          />

          {activeExpulsionVote && (
            <ExpulsionVotePanel
              busy={busy}
              canVote={Boolean(currentBallot) && currentParticipant?.presence === 'online'}
              isTarget={roomSession?.participantRef === activeExpulsionVote.target_ref}
              onCast={(choice) => void castExpulsionBallot(activeExpulsionVote.vote_ref, choice)}
              ownBallot={currentBallot}
              vote={activeExpulsionVote}
            />
          )}

          {isJoined && (matchRendererAvailable ? (
            activeMatch
              ? renderMatchScreen(room.game_id, {
                  busy,
                  match: activeMatch,
                  onPick: (value: string) => void submitPick(value),
                })
              : null
          ) : (
            <section className="match-unavailable" aria-labelledby="match-unavailable-title">
              <h3 id="match-unavailable-title">Vista de partida no disponible</h3>
              <p className="quiet-copy">
                Este juego todavía no tiene una vista de partida en HomeGame.
              </p>
            </section>
          ))}

          {isJoined && roomSession ? (
            <YourRoomActions
              busy={busy}
              displayName={roomSession.displayName}
              leavePending={pendingAction === 'leave'}
              markerLabel={markerLabel(activeGame, roomSession.gameMarker)}
              onLeave={() => void leaveRoom()}
              onToggleReady={() => void toggleReady()}
              ownReady={ownReady}
              readyPending={pendingAction === 'ready'}
            />
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
      )}
        {!room && (
          <GameCatalog
            busy={busy}
            games={games}
            hasSession={Boolean(roomSession)}
            onSelectGame={selectGame}
          />
        )}
        </>
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

      {isJoined && countdown && !matchInProgress && (
        <CountdownOverlay
          remainingSeconds={countdown.remainingSeconds}
          seconds={countdown.seconds}
        />
      )}

      <footer className="site-footer">Un espacio acogedor para disfrutar de una buena noche de juegos.</footer>
    </main>
  )
}

export default App
