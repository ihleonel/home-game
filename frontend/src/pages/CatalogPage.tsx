import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import type { Game, RoomIntent } from '../api/types'
import { GameCatalog } from '../components/GameCatalog'
import { IdentityForm } from '../components/IdentityForm'
import { readStoredIdentity } from '../lib/session'
import type { GuestIdentity } from '../lib/session'
import { useCatalog } from '../state/catalogContext'
import { useRoomSession } from '../state/roomSessionContext'

/**
 * The catalog page.
 *
 * It owns the create-room draft: which game was chosen and the identity being
 * typed. Once a room exists for this session the room page owns the view, so
 * this page hands over instead of rendering the catalog beside it.
 */
export function CatalogPage() {
  const { games } = useCatalog()
  const { room, roomSession, busy, createOrJoin, setActionError } = useRoomSession()

  const identityDialogRef = useRef<HTMLDialogElement>(null)
  const [intent, setIntent] = useState<RoomIntent | null>(null)
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null)
  const [identity, setIdentity] = useState<GuestIdentity>({
    displayName: '',
    gameMarker: '',
  })

  const selectedGame = games.find((game) => game.id === selectedGameId)

  useEffect(() => {
    const dialog = identityDialogRef.current
    if (intent === 'create' && selectedGame && dialog && !dialog.open) {
      dialog.showModal()
    }
  }, [intent, selectedGame])

  // A room exists, so the room page is the view; the URL follows the room, not
  // the game the player last clicked.
  if (room) return <Navigate to={`/rooms/${room.game_id}`} replace />

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

  async function submitIdentity(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!intent || !selectedGame) return
    const outcome = await createOrJoin(intent, selectedGame, identity)
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
    <>
      <GameCatalog
        busy={busy}
        games={games}
        hasSession={Boolean(roomSession)}
        onSelectGame={selectGame}
      />

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
    </>
  )
}
