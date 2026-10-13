import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import type { Game, RoomIntent } from './api/types'
import { AppMessages } from './components/AppMessages'
import { CountdownOverlay } from './components/CountdownOverlay'
import { ExpulsionVotePanel } from './components/ExpulsionVotePanel'
import { GameCatalog } from './components/GameCatalog'
import { IdentityForm } from './components/IdentityForm'
import { Roster } from './components/Roster'
import { YourRoomActions } from './components/YourRoomActions'
import { renderMatchScreen } from './games/registry'
import { markerLabel } from './lib/format'
import { readStoredIdentity } from './lib/session'
import type { GuestIdentity } from './lib/session'
import { CatalogProvider } from './state/CatalogProvider'
import { useCatalog } from './state/catalogContext'
import { RoomSessionProvider } from './state/RoomSessionProvider'
import { useRoomSession } from './state/roomSessionContext'

/**
 * The single view the app renders today.
 *
 * The catalog and the room session come from the providers above; only the
 * identity form's own intent and draft live here.
 */
function HomeGame() {
  const { games, isLoading, loadError, reload } = useCatalog()
  const {
    room,
    roomSession,
    activeMatch,
    matchInProgress,
    matchRendererAvailable,
    activeExpulsionVote,
    currentBallot,
    currentParticipant,
    allReady,
    ownReady,
    busy,
    pendingAction,
    actionError,
    connectionError,
    voteNotice,
    countdown,
    countdownNotice,
    isJoined,
    createOrJoin,
    toggleReady,
    leaveRoom,
    startExpulsionVote,
    castExpulsionBallot,
    submitPick,
    setActionError,
  } = useRoomSession()

  const identityDialogRef = useRef<HTMLDialogElement>(null)
  const [intent, setIntent] = useState<RoomIntent | null>(null)
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null)
  const [identity, setIdentity] = useState<GuestIdentity>({
    displayName: '',
    gameMarker: '',
  })

  const activeGame = games.find((game) => game.id === room?.game_id)
  const selectedGame = games.find((game) => game.id === selectedGameId)

  useEffect(() => {
    const dialog = identityDialogRef.current
    if (intent === 'create' && selectedGame && dialog && !dialog.open) {
      dialog.showModal()
    }
  }, [intent, selectedGame])

  function selectGame(game: Game): void {
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
      void createOrJoin('create', game, savedIdentity)
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
      void createOrJoin('join', activeGame, savedIdentity)
    } else {
      setIntent('join')
    }
  }

  async function submitIdentity(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const game = intent === 'create' ? selectedGame : activeGame
    if (!intent || !game) return
    const outcome = await createOrJoin(intent, game, identity)
    // A joined room or a conflict both end the draft: the room moved under
    // this client, so the form it was composed against no longer applies.
    if (outcome !== 'rejected') {
      setIntent(null)
      setSelectedGameId(null)
    }
  }

  function cancelIdentity(): void {
    setIntent(null)
    setSelectedGameId(null)
    setActionError(null)
  }

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
          <button className="button button-primary" onClick={reload} type="button">
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

/**
 * App shell: the two providers wrap every view.
 *
 * Both sit above the view so navigating between pages never remounts them and
 * never closes the room socket.
 */
function App() {
  return (
    <CatalogProvider>
      <RoomSessionProvider>
        <HomeGame />
      </RoomSessionProvider>
    </CatalogProvider>
  )
}

export default App
