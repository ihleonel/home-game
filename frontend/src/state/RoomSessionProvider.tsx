import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, requestJson } from '../api/client'
import { fetchActiveRoom } from '../api/rooms'
import type {
  Game,
  MatchEnvelope,
  MembershipResponse,
  Room,
  RoomEnvelope,
  RoomIntent,
  SeatPresence,
  ServerMessage,
  VoteResponse,
} from '../api/types'
import { MatchPresenceContext, parseSeatPresence } from '../games/matchPresence'
import { parseMatchRoster } from '../games/matchRoster'
import { hasMatchRenderer } from '../games/registry'
import type { MatchState } from '../games/registry'
import { expulsionVoteMessage, splitRoomParticipants } from '../lib/format'
import { mergeMatch, mergeMatchEvent } from '../lib/match'
import { readStoredRoomSession, saveGuestSession } from '../lib/session'
import type { GuestIdentity, RoomSession } from '../lib/session'
import { RoomSessionContext } from './roomSessionContext'
import type { CreateOrJoinOutcome, MatchCountdown, PendingAction } from './roomSessionContext'

/**
 * One stable empty value so a screen without presence does not get a fresh
 * array on every render.
 */
const NO_SEAT_PRESENCE: SeatPresence[] = []

/**
 * Owns the room session, the current match and the single WebSocket.
 *
 * It sits above every page: navigating between the catalog, the waiting room
 * and the game screen must never remount this provider, because remounting it
 * would close the socket and send the participant down the reconnect-grace
 * path mid-match.
 */
export function RoomSessionProvider({ children }: { children: ReactNode }) {
  const membershipRequestPending = useRef(false)
  const leavingRef = useRef(false)
  const [room, setRoom] = useState<Room | null>(null)
  const [roomSession, setRoomSession] = useState<RoomSession | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [voteNotice, setVoteNotice] = useState<string | null>(null)
  const [countdown, setCountdown] = useState<MatchCountdown | null>(null)
  const [countdownNotice, setCountdownNotice] = useState<string | null>(null)
  const [match, setMatch] = useState<MatchState | null>(null)
  // Presence is keyed by match ref so a frame for another match can never
  // annotate the one on screen, and a new match starts with none of the
  // previous one's presence.
  const [matchSeatPresence, setMatchSeatPresence] = useState<{
    matchRef: string
    seats: SeatPresence[]
  } | null>(null)

  const isJoined = roomSession?.gameId === room?.game_id
  const currentParticipant = room?.participants.find(
    (participant) => participant.participant_ref === roomSession?.participantRef,
  )
  const activeExpulsionVote = room?.expulsion_vote ?? null
  const currentBallot = activeExpulsionVote?.ballots.find(
    (ballot) => ballot.participant_ref === roomSession?.participantRef,
  )
  // Only players can be ready: a spectator has no seat to confirm (S3), so
  // counting it here would keep the lobby from ever reporting a fully ready
  // room, exactly as ``lobby_is_ready`` ignores spectators on the server.
  const readyPlayers = splitRoomParticipants(room?.participants ?? []).players
  const allReady = Boolean(
    readyPlayers.length && readyPlayers.every((participant) => participant.is_ready),
  )
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
  const activeMatchPresence =
    activeMatch && matchSeatPresence?.matchRef === activeMatch.matchRef
      ? matchSeatPresence.seats
      : NO_SEAT_PRESENCE

  async function refreshActiveRoom(gameId: string, sessionId?: string): Promise<void> {
    try {
      const activeRoom = await fetchActiveRoom(gameId, sessionId)
      setRoom(activeRoom)
      setRoomSession((current) =>
        current && current.gameId === activeRoom?.game_id ? current : null,
      )
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'No se ha podido actualizar la sala.')
    }
  }

  async function createOrJoin(
    intent: RoomIntent,
    game: Game,
    guestIdentity: GuestIdentity,
    options?: { asSpectator?: boolean },
  ): Promise<CreateOrJoinOutcome> {
    if (membershipRequestPending.current) return 'rejected'
    if (roomSession) {
      setActionError('Sal de la sala actual antes de elegir otro juego.')
      return 'rejected'
    }
    const displayName = guestIdentity.displayName.trim()
    if (!displayName || !guestIdentity.gameMarker) {
      setActionError('Escribe un nombre y elige una ficha para continuar.')
      return 'rejected'
    }

    membershipRequestPending.current = true
    const savedSession = readStoredRoomSession(game.id)
    const requestBody = {
      game_id: game.id,
      display_name: displayName,
      game_marker: guestIdentity.gameMarker,
      ...(savedSession ? { session_id: savedSession.sessionId } : {}),
      // The spectator flag is additive: a caller that does not ask for it
      // sends exactly the same body as before.
      ...(options?.asSpectator ? { as_spectator: true } : {}),
    }

    setPendingAction(intent)
    setActionError(null)
    try {
      const path = intent === 'create' ? '/api/rooms/' : '/api/rooms/join/'
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
      setMatchSeatPresence(null)
      setConnectionError(null)
      setVoteNotice(null)
      return 'joined'
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'No se ha podido procesar la solicitud de sala.')
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        // The room moved under this client. Refreshing it is what also closes
        // the caller's identity draft, exactly as before the split.
        void refreshActiveRoom(game.id)
        return 'conflict'
      }
      return 'rejected'
    } finally {
      membershipRequestPending.current = false
      setPendingAction(null)
    }
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

  async function requestPlayerSeat(): Promise<void> {
    if (!roomSession) return
    setPendingAction('play')
    setActionError(null)
    try {
      const response = await requestJson<RoomEnvelope>('/api/rooms/play/', {
        method: 'POST',
        body: JSON.stringify({ session_id: roomSession.sessionId }),
      })
      // The promotion is authoritative: the server snapshot carries the new
      // role and readiness, so the local session copy is left to the room
      // frames that follow.
      setRoom(response.room)
    } catch (error) {
      setActionError(
        error instanceof Error ? error.message : 'No se ha podido pedir el asiento.',
      )
    } finally {
      setPendingAction(null)
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
      setMatchSeatPresence(null)
      setConnectionError(null)
      setVoteNotice(null)
    } catch (error) {
      leavingRef.current = false
      setActionError(error instanceof Error ? error.message : 'No se ha podido salir de la sala.')
      if (error instanceof ApiError && error.status === 404) {
        setRoomSession(null)
        setRoom(null)
        setMatch(null)
        setMatchSeatPresence(null)
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
          setMatchSeatPresence((current) =>
            current?.matchRef === matchRef ? null : current,
          )
          return
        }
        setActionError(
          error instanceof Error ? error.message : 'No se ha podido sincronizar la partida.',
        )
      }
    },
    [],
  )

  /**
   * Submit one action of the running match.
   *
   * ``name`` is the action the screen was offered and ``value`` the option it
   * chose, or ``null`` for an action that carries no value. The runtime
   * validates both against what the seat was offered, so this function never
   * decides what is legal: it posts what the screen received.
   */
  async function submitAction(name: string, value: string | null): Promise<void> {
    if (!roomSession || !match || match.version === null) return
    const { matchRef, version } = match
    setPendingAction('match')
    setActionError(null)
    try {
      const response = await requestJson<MatchEnvelope>(
        `/api/matches/${encodeURIComponent(matchRef)}/actions/`,
        {
          method: 'POST',
          body: JSON.stringify({
            session_id: roomSession.sessionId,
            action_name: name,
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
      // A stale version means this client composed the action against an older
      // state; any other rejection still leaves the local view unconfirmed.
      // Both are resolved by re-reading the server rather than reconciling
      // locally, so the resync runs for either one.
      await resyncMatch(matchRef, roomSession.sessionId)
    } finally {
      setPendingAction(null)
    }
  }

  /**
   * The single-action games' shorthand: they all name their action ``pick``.
   *
   * Keeping that name in one place is what let the general channel arrive
   * without touching ``duelo`` or ``ta-te-ti``.
   */
  async function submitPick(value: string): Promise<void> {
    await submitAction('pick', value)
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
              // A frame that carries no usable roster projects an explicitly
              // empty one: the screen then falls back to the neutral label
              // rather than naming a seat from a stale list (S3/S5).
              roster: parseMatchRoster(message.roster) ?? [],
              view,
            }))
            const snapshotPresence = parseSeatPresence(message.seats)
            setMatchSeatPresence((current) => {
              if (snapshotPresence === null) {
                // No usable presence in this frame: keep what this match
                // already had, but never carry it over to a new one.
                return current?.matchRef === matchRef ? current : null
              }
              return { matchRef, seats: snapshotPresence }
            })
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
            setMatch((current) =>
              mergeMatchEvent(current, matchRef, version, view, message.roster),
            )
          } else if (
            message.type === 'match.presence' &&
            typeof message.match_ref === 'string'
          ) {
            // Presence only annotates the match already on screen. A frame
            // for another match (or one that arrives before the snapshot) is
            // dropped rather than starting a match from presence alone.
            const matchRef = message.match_ref
            const seats = parseSeatPresence(message.seats)
            if (seats !== null) {
              setMatchSeatPresence((current) =>
                current?.matchRef === matchRef ? { matchRef, seats } : current,
              )
            }
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
  // cancelled, the match opens, or the provider unmounts. The run id guards
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

  return (
    <RoomSessionContext.Provider
      value={{
        room,
        roomSession,
        match,
        countdown,
        countdownNotice,
        voteNotice,
        connectionError,
        actionError,
        busy: pendingAction !== null,
        pendingAction,
        isJoined,
        currentParticipant,
        activeExpulsionVote,
        currentBallot,
        allReady,
        ownReady,
        activeMatch,
        matchInProgress,
        matchRendererAvailable,
        createOrJoin,
        toggleReady,
        requestPlayerSeat,
        leaveRoom,
        startExpulsionVote,
        castExpulsionBallot,
        submitAction,
        submitPick,
        setActionError,
      }}
    >
      <MatchPresenceContext.Provider value={activeMatchPresence}>
        {children}
      </MatchPresenceContext.Provider>
    </RoomSessionContext.Provider>
  )
}
