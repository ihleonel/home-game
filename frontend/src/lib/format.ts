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

/**
 * The target refs a vote covers.
 *
 * The batch contract publishes ``targets``; a payload from before it carries
 * the single ``target_ref`` instead. Reading one as a batch of one keeps an
 * older response from costing the panel its list (S5/S9).
 */
export function expulsionVoteTargets(vote: ExpulsionVote): string[] {
  const raw = vote as { targets?: unknown; target_ref?: unknown }
  if (Array.isArray(raw.targets)) {
    return raw.targets.filter((ref): ref is string => typeof ref === 'string')
  }
  return typeof raw.target_ref === 'string' ? [raw.target_ref] : []
}

/**
 * The origin of a vote, defaulting to ``manual``.
 *
 * An older payload predates ``origin`` and every vote it could describe was
 * started by a human, so the missing field costs only the annotation (S9).
 */
function expulsionVoteOrigin(vote: ExpulsionVote): ExpulsionVote['origin'] {
  return (vote as { origin?: unknown }).origin === 'automatic' ? 'automatic' : 'manual'
}

/**
 * Resolve a vote's targets to the names the roster shows (S9).
 *
 * The vote publishes refs, never names, so the panel reads them from the same
 * room snapshot the roster does. A ref no longer on the roster keeps the ref
 * itself as a last resort, because a vote whose target just left still owes
 * the screen a slot rather than an empty list.
 */
export function expulsionVoteTargetNames(
  vote: ExpulsionVote,
  participants: Participant[],
): string[] {
  return expulsionVoteTargets(vote).map(
    (ref) =>
      participants.find((participant) => participant.participant_ref === ref)?.display_name ??
      ref,
  )
}

/**
 * The line that names who opened the vote (S6/S9).
 *
 * An automatic vote has no starter at all, so the copy says the sweep opened
 * it instead of pretending a participant did. A manual vote names the caller
 * from the same roster the targets come from, and falls back to a neutral
 * phrase when that participant is already gone.
 */
export function expulsionVoteOriginLabel(
  vote: ExpulsionVote,
  participants: Participant[],
): string {
  if (expulsionVoteOrigin(vote) === 'automatic') return 'La votación se abrió automáticamente.'
  const starter = vote.started_by_ref
    ? participants.find((participant) => participant.participant_ref === vote.started_by_ref)
        ?.display_name
    : undefined
  return starter ? `Votación iniciada por ${starter}.` : 'Votación iniciada manualmente.'
}

export function expulsionVoteMessage(vote: ExpulsionVote): string {
  if (vote.status === 'pending') {
    return `Votación de expulsión: ${vote.yes_count} de ${vote.eligible_count} votos emitidos son favorables.`
  }
  if (vote.status === 'approved') return 'La votación de expulsión ha sido aprobada por unanimidad.'
  // A rejection spends the absence (D6): the next sweep removes the target, so
  // the copy no longer promises that the player stays in the room.
  if (vote.status === 'rejected') return 'La votación de expulsión ha sido rechazada.'
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
