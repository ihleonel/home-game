import type { ExpulsionBallot, ExpulsionVote, Game, Participant } from '../api/types'

export function markerLabel(game: Game | undefined, markerId: string): string {
  return game?.markers.find((marker) => marker.id === markerId)?.label ?? 'Ficha'
}

export function presenceLabel(presence: Participant['presence']): string {
  const labels: Record<Participant['presence'], string> = {
    offline: 'Sin conexión',
    online: 'En línea',
    reconnecting: 'Reconectando…',
    inactive: 'Inactivo',
  }
  return labels[presence]
}

export function voteChoiceLabel(choice: NonNullable<ExpulsionBallot['choice']>): string {
  return choice === 'yes' ? 'Sí' : 'No'
}

/**
 * Split a room's participants into the seats and the visitors.
 *
 * A missing ``role`` counts as a player, matching the server's own rule, so an
 * older payload never turns a seat into a visit.
 */
export function splitRoomParticipants(participants: Participant[]): {
  players: Participant[]
  spectators: Participant[]
} {
  return {
    players: participants.filter((participant) => participant.role !== 'spectator'),
    spectators: participants.filter((participant) => participant.role === 'spectator'),
  }
}

/**
 * The lobby's summary line, counting seats and visitors separately.
 *
 * A spectator holds no seat, so calling it a player would contradict both the
 * roster badge and the server's own lobby rule (S3/S8).
 */
export function roomSummary(players: number, spectators: number): string {
  const playersText = `${players} ${players === 1 ? 'jugador' : 'jugadores'}`
  const spectatorsText = `${spectators} ${spectators === 1 ? 'espectador' : 'espectadores'}`
  if (spectators === 0) return `${playersText} en la sala`
  // A room can hold only visitors, for example after every player left while
  // one spectator stayed, so the empty seat count is dropped instead of
  // reading "0 jugadores y 1 espectador".
  if (players === 0) return `${spectatorsText} en la sala`
  return `${playersText} y ${spectatorsText} en la sala`
}

export function expulsionVoteMessage(vote: ExpulsionVote): string {
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
