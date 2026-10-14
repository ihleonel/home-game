import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { CountdownOverlay } from '../components/CountdownOverlay'
import { ExpulsionVotePanel } from '../components/ExpulsionVotePanel'
import { IdentityForm } from '../components/IdentityForm'
import { Roster } from '../components/Roster'
import { SpectatorActions } from '../components/SpectatorActions'
import { YourRoomActions } from '../components/YourRoomActions'
import { markerLabel, roomSummary, splitRoomParticipants } from '../lib/format'
import { readStoredIdentity } from '../lib/session'
import type { GuestIdentity } from '../lib/session'
import { useCatalog } from '../state/catalogContext'
import { useRoomSession } from '../state/roomSessionContext'

/**
 * The waiting room of a game.
 *
 * It shows the roster, the readiness, the expulsion vote and the countdown.
 * A live match with a renderer moves the player to the game screen; a game
 * that has no renderer keeps its "no disponible" notice here, so a match can
 * never trap a player on a screen this app cannot draw.
 */
export function LobbyPage() {
  const { gameId } = useParams<{ gameId: string }>()
  const { games } = useCatalog()
  const {
    room,
    roomSession,
    activeExpulsionVote,
    currentBallot,
    currentParticipant,
    allReady,
    ownReady,
    busy,
    pendingAction,
    isJoined,
    matchInProgress,
    matchRendererAvailable,
    countdown,
    toggleReady,
    requestPlayerSeat,
    leaveRoom,
    startExpulsionVote,
    castExpulsionBallot,
    createOrJoin,
    setActionError,
  } = useRoomSession()

  const [identity, setIdentity] = useState<GuestIdentity>({
    displayName: '',
    gameMarker: '',
  })
  const [joining, setJoining] = useState(false)

  const activeGame = games.find((game) => game.id === room?.game_id)

  if (!room) return <Navigate to="/" replace />
  if (matchInProgress && matchRendererAvailable) {
    return <Navigate to={`/games/${room.game_id}/match`} replace />
  }
  if (gameId !== room.game_id) return <Navigate to={`/rooms/${room.game_id}`} replace />

  // A spectator may request a seat only while the room still has one and no
  // match has started (S5/S8). The reason mirrors the exact server copy so the
  // disabled button never leaves the spectator guessing.
  const { players, spectators } = splitRoomParticipants(room.participants)
  const seatLimits = room.seat_limits ?? null
  const roomFull = seatLimits !== null && players.length >= seatLimits.max_seats
  const canRequestSeat = !matchInProgress && seatLimits !== null && !roomFull
  const spectatorSeatReason = matchInProgress
    ? 'La partida ya ha comenzado.'
    : roomFull
      ? 'No hay ningún asiento libre en la sala.'
      : null

  function startJoining(): void {
    if (!activeGame) return
    const savedIdentity = readStoredIdentity(activeGame)
    setIdentity(savedIdentity)
    setActionError(null)
    if (savedIdentity.displayName.trim() && savedIdentity.gameMarker) {
      void createOrJoin('join', activeGame, savedIdentity)
    } else {
      setJoining(true)
    }
  }

  async function submitIdentity(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!activeGame) return
    const outcome = await createOrJoin('join', activeGame, identity)
    if (outcome !== 'rejected') setJoining(false)
  }

  async function submitSpectatorIdentity(): Promise<void> {
    if (!activeGame) return
    const outcome = await createOrJoin('join', activeGame, identity, { asSpectator: true })
    if (outcome !== 'rejected') setJoining(false)
  }

  function cancelJoining(): void {
    setJoining(false)
    // Cancelling the draft also dismisses the rejection that opened it, the
    // same way the single identity form did before the split.
    setActionError(null)
  }

  return (
    <>
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
            : roomSummary(players.length, spectators.length)}
        </div>

        <Roster
          busy={busy}
          canStartExpulsionVote={(participant) =>
            !activeExpulsionVote &&
            isJoined &&
            roomSession !== null &&
            // A spectator is never a voter, so offering the action would only
            // produce a rejection: the backend electorate excludes it (S7).
            currentParticipant?.role === 'player' &&
            currentParticipant?.presence === 'online' &&
            participant.role === 'player' &&
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

        {isJoined && !matchRendererAvailable && (
          <section className="match-unavailable" aria-labelledby="match-unavailable-title">
            <h3 id="match-unavailable-title">Vista de partida no disponible</h3>
            <p className="quiet-copy">
              Este juego todavía no tiene una vista de partida en HomeGame.
            </p>
          </section>
        )}

        {isJoined && roomSession ? (
          currentParticipant?.role === 'spectator' ? (
            <>
              <p className="spectator-notice" role="status">
                Estás como espectador.
              </p>
              <SpectatorActions
                busy={busy}
                canRequestSeat={canRequestSeat}
                displayName={roomSession.displayName}
                leavePending={pendingAction === 'leave'}
                markerLabel={markerLabel(activeGame, roomSession.gameMarker)}
                onLeave={() => void leaveRoom()}
                onRequestSeat={() => void requestPlayerSeat()}
                reason={spectatorSeatReason}
                requestPending={pendingAction === 'play'}
              />
            </>
          ) : (
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
          )
        ) : joining && activeGame ? (
          <IdentityForm
            busy={busy}
            game={activeGame}
            identity={identity}
            intent="join"
            onCancel={cancelJoining}
            onChange={setIdentity}
            onSubmit={submitIdentity}
            onSubmitAsSpectator={() => void submitSpectatorIdentity()}
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

      {isJoined && countdown && !matchInProgress && (
        <CountdownOverlay
          remainingSeconds={countdown.remainingSeconds}
          seconds={countdown.seconds}
        />
      )}
    </>
  )
}
