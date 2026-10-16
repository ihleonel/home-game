from ..domain.errors import (
    VotingConflict,
    VotingNotFound,
    VotingPermissionDenied,
)
from ..domain.rules import (
    ballot_is_unanswered,
    grace_has_expired,
    is_connected_voter,
    is_inactive_target,
    is_self_target,
    resolve_ballot,
    resolve_electorate,
)
from .cancellations import ExpulsionVoteCancellation
from .ports import ExpulsionVotingPorts


def start_vote(ports: ExpulsionVotingPorts, data):
    with ports.atomic():
        room_id = ports.active_room_for_session_for_update(data['session_id'])
        if room_id is None:
            raise VotingNotFound('No hay ninguna sala activa.')

        caller = ports.participant_for_session_for_update(
            room_id, data['session_id']
        )
        if caller is None:
            raise VotingNotFound('La sesión no pertenece a ningún participante activo de la sala.')
        if not is_connected_voter(
            caller.presence,
            lambda: ports.has_connection(room_id, str(caller.session_id)),
        ):
            raise VotingPermissionDenied('Solo los participantes conectados de la sala pueden votar.')

        target = ports.participant_for_public_ref_for_update(
            room_id, data['target_ref']
        )
        if target is None:
            raise VotingNotFound('La persona propuesta no es un participante activo de la sala.')
        if is_self_target(caller.id, target.id):
            raise VotingPermissionDenied(
                'No puedes iniciar una votación contra ti mismo.'
            )

        now = ports.now()
        if not is_inactive_target(target, now):
            raise VotingConflict(
                'La persona propuesta aún está dentro del plazo de reconexión.'
            )
        if ports.pending_vote_for_update(room_id) is not None:
            raise VotingConflict('Ya hay una votación en curso en esta sala.')

        if grace_has_expired(target, now):
            ports.mark_target_inactive(target.id)
            ports.schedule_room_event(
                room_id,
                'participant_inactive',
                ports.room_snapshot(room_id),
            )

        online_participants = ports.online_active_participants_for_update(room_id)
        connected_sessions = {
            str(participant.session_id)
            for participant in online_participants
            if ports.has_connection(room_id, str(participant.session_id))
        }
        electorate = resolve_electorate(
            caller.id, target.id, online_participants, connected_sessions
        )
        if not electorate.caller_is_eligible:
            raise VotingPermissionDenied('No tienes permiso para votar.')
        if not electorate.participant_ids:
            raise VotingConflict('No hay votantes conectados disponibles.')

        vote = ports.create_vote(
            room_id, (target.id,), caller_id=caller.id, origin='manual'
        )
        ports.create_ballots(vote.id, electorate.participant_ids)
        vote_summary = ports.vote_snapshot(vote.id)
        response = {'room': ports.room_snapshot(room_id), 'vote': vote_summary}
        ports.schedule_room_event(
            room_id,
            'expulsion_vote_started',
            ports.room_snapshot(room_id),
            vote=vote_summary,
        )
    return response


def cast_ballot(ports: ExpulsionVotingPorts, vote_ref, data):
    with ports.atomic():
        room_id = ports.room_for_vote_for_update(vote_ref)
        if room_id is None:
            raise VotingNotFound('No hay ninguna sala activa.')

        vote = ports.vote_for_public_ref_for_update(room_id, vote_ref)
        if vote is None:
            raise VotingNotFound('La votación de expulsión no existe.')
        if vote.status != 'pending':
            raise VotingConflict('La votación de expulsión ya se ha resuelto.')

        caller = ports.participant_for_session_for_update(
            room_id, data['session_id']
        )
        if caller is None:
            raise VotingNotFound('La sesión no pertenece a ningún participante activo de la sala.')
        if not is_connected_voter(
            caller.presence,
            lambda: ports.has_connection(room_id, str(caller.session_id)),
        ):
            raise VotingPermissionDenied('Solo los participantes conectados de la sala pueden votar.')
        if caller.id in vote.target_ids:
            raise VotingPermissionDenied('La persona propuesta no puede votar sobre su propia expulsión.')

        ballot = ports.ballot_for_voter_for_update(vote.id, caller.id)
        if ballot is None:
            raise VotingPermissionDenied(
                'No tenías derecho a votar cuando comenzó la votación.'
            )
        if not ballot_is_unanswered(ballot.choice):
            raise VotingConflict('Cada participante con derecho a voto solo puede votar una vez.')

        targets = tuple(
            ports.participant_by_id_for_update(target_id)
            for target_id in vote.target_ids
        )
        inactivity_checked_at = ports.now()
        reconnected = next(
            (
                target
                for target in targets
                if not is_inactive_target(target, inactivity_checked_at)
            ),
            None,
        )
        if reconnected is not None:
            cancelled_vote = ExpulsionVoteCancellation(ports).for_target(
                room_id, reconnected.id, 'target_reconnected'
            )
            snapshot = ports.room_snapshot(room_id)
            vote_summary = cancelled_vote or ports.vote_snapshot(vote.id)
            response = {'room': snapshot, 'vote': vote_summary}
            ports.schedule_room_event(
                room_id,
                'expulsion_vote_cancelled',
                snapshot,
                vote=vote_summary,
            )
            return response

        for target in targets:
            if target.presence == 'reconnecting' and grace_has_expired(
                target, ports.now()
            ):
                ports.mark_target_inactive(target.id)
        ports.save_ballot(ballot.id, data['choice'], ports.now())

        if data['choice'] == 'no':
            yes_count, no_count, eligible_count = 0, 0, 0
        else:
            yes_count, no_count, eligible_count = ports.ballot_counts(vote.id)
        resolution = resolve_ballot(
            data['choice'], yes_count, no_count, eligible_count
        )
        departure_session_ids = ()
        if resolution.remove_target:
            # The wire keeps one ``departed_session_id`` per event, so every
            # expelled target gets its own removal event in the order the
            # targets are removed. One target stays one event.
            departure_session_ids = tuple(
                target.session_id for target in targets
            )
            for target in targets:
                ports.remove_target(target.id, ports.now())
        if resolution.status != 'pending':
            ports.save_vote_resolution(
                vote.id, resolution.status, resolution.reason, ports.now()
            )

        vote_summary = ports.vote_snapshot(vote.id)
        snapshot = ports.room_snapshot(room_id)
        response = {'room': snapshot, 'vote': vote_summary}
        if departure_session_ids:
            for departed_session_id in departure_session_ids:
                ports.schedule_room_event(
                    room_id,
                    resolution.event_name,
                    snapshot,
                    departed_session_id=departed_session_id,
                    vote=vote_summary,
                )
        else:
            ports.schedule_room_event(
                room_id,
                resolution.event_name,
                snapshot,
                departed_session_id=None,
                vote=vote_summary,
            )
    return response
