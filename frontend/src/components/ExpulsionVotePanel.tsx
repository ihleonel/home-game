import type { ExpulsionBallot, ExpulsionVote, Participant } from '../api/types'
import {
  expulsionVoteOriginLabel,
  expulsionVoteTargetNames,
  voteChoiceLabel,
} from '../lib/format'

type ExpulsionVotePanelProps = {
  vote: ExpulsionVote
  /**
   * The same room snapshot the roster draws from, so the panel can resolve the
   * vote's target refs and its starter to the names on screen (S9).
   */
  participants: Participant[]
  isTarget: boolean
  ownBallot: ExpulsionBallot | undefined
  canVote: boolean
  busy: boolean
  onCast: (choice: 'yes' | 'no') => void
}

/**
 * The open ballot of a room, rendered above the roster (S9).
 *
 * It decides no rule: it shows the batch the server published and who opened
 * it. The set of targets is the server's, never a client guess, so this panel
 * never computes an electorate, a quorum or whether a target is still absent.
 */
export function ExpulsionVotePanel({
  vote,
  participants,
  isTarget,
  ownBallot,
  canVote,
  busy,
  onCast,
}: ExpulsionVotePanelProps) {
  const targetNames = expulsionVoteTargetNames(vote, participants)
  const title =
    targetNames.length === 0
      ? 'Votación de expulsión'
      : targetNames.length === 1
        ? targetNames[0]
        : `Expulsión de ${targetNames.length} jugadores`

  return (
    <section className="vote-panel" aria-labelledby="vote-title">
      <div className="vote-heading">
        <div>
          <p className="eyebrow">Votación unánime de expulsión</p>
          <h3 id="vote-title">{title}</h3>
          <p className="vote-origin">{expulsionVoteOriginLabel(vote, participants)}</p>
        </div>
        <span className="vote-count">
          {vote.yes_count} / {vote.eligible_count} a favor
        </span>
      </div>
      {targetNames.length > 1 && (
        <ul className="vote-targets">
          {targetNames.map((name, index) => (
            <li key={`${name}-${index}`}>{name}</li>
          ))}
        </ul>
      )}
      <ul className="vote-ballots">
        {vote.ballots.map((ballot) => (
          <li key={ballot.participant_ref}>
            <span>{ballot.display_name}</span>
            <strong>{ballot.choice ? `Voto: ${voteChoiceLabel(ballot.choice)}` : 'Pendiente de voto'}</strong>
          </li>
        ))}
      </ul>
      {isTarget ? (
        <p className="quiet-copy">Eres una de las personas propuestas para la expulsión y no puedes votar.</p>
      ) : ownBallot?.choice ? (
        <p className="quiet-copy">Has votado: {voteChoiceLabel(ownBallot.choice)}.</p>
      ) : canVote ? (
        <div className="vote-actions">
          <button
            className="button button-primary"
            disabled={busy}
            onClick={() => onCast('yes')}
            type="button"
          >
            Votar a favor
          </button>
          <button
            className="button button-quiet"
            disabled={busy}
            onClick={() => onCast('no')}
            type="button"
          >
            Votar en contra
          </button>
        </div>
      ) : (
        <p className="quiet-copy">Solo pueden votar los participantes que estaban conectados cuando comenzó la votación.</p>
      )}
    </section>
  )
}
