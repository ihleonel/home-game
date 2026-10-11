def expulsion_vote_snapshot(vote):
    ballots = list(
        vote.ballots.select_related('voter').order_by('voter__public_id')
    )
    return {
        'vote_ref': str(vote.public_id),
        'target_ref': str(vote.target.public_id),
        'target_display_name': vote.target.display_name,
        'started_by_ref': str(vote.initiated_by.public_id),
        'status': vote.status,
        'resolution_reason': vote.resolution_reason,
        'started_at': vote.started_at.isoformat(),
        'resolved_at': vote.resolved_at.isoformat() if vote.resolved_at else None,
        'eligible_count': len(ballots),
        'yes_count': sum(ballot.choice == 'yes' for ballot in ballots),
        'no_count': sum(ballot.choice == 'no' for ballot in ballots),
        'ballots': [
            {
                'participant_ref': str(ballot.voter.public_id),
                'display_name': ballot.voter.display_name,
                'choice': ballot.choice,
            }
            for ballot in ballots
        ],
    }
