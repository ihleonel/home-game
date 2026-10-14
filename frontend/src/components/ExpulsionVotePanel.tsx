import type { ExpulsionBallot, ExpulsionVote } from '../api/types'
import { voteChoiceLabel } from '../lib/format'

type ExpulsionVotePanelProps = {
  vote: ExpulsionVote
  isTarget: boolean
  ownBallot: ExpulsionBallot | undefined
  canVote: boolean
  busy: boolean
  onCast: (choice: 'yes' | 'no') => void
}

export function ExpulsionVotePanel({
  vote,
  isTarget,
  ownBallot,
  canVote,
  busy,
  onCast,
}: ExpulsionVotePanelProps) {
  return (
    <section className="vote-panel" aria-labelledby="vote-title">
      <div className="vote-heading">
        <div>
          <p className="eyebrow">Votación unánime de expulsión</p>
          <h3 id="vote-title">{vote.target_display_name}</h3>
        </div>
        <span className="vote-count">
          {vote.yes_count} / {vote.eligible_count} a favor
        </span>
      </div>
      <ul className="vote-ballots">
        {vote.ballots.map((ballot) => (
          <li key={ballot.participant_ref}>
            <span>{ballot.display_name}</span>
            <strong>{ballot.choice ? `Voto: ${voteChoiceLabel(ballot.choice)}` : 'Pendiente de voto'}</strong>
          </li>
        ))}
      </ul>
      {isTarget ? (
        <p className="quiet-copy">Eres la persona propuesta para la expulsión y no puedes votar.</p>
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
