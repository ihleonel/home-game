"""Pure unit tests for the automatic-expulsion sweep rules (S2, S4).

The rules below are framework-free: they decide what an expired absence is,
whether a resolved vote already spent that absence, and whether the room holds
the quorum that authorizes an automatic vote. The sweep use case composes them;
nothing here touches the database or the connection registry.
"""

from datetime import datetime, timedelta

from django.test import SimpleTestCase

from modules.rooms.features.expulsion_voting.domain.rules import (
    LEAVE,
    MIN_VOTE_QUORUM,
    REAP,
    VOTE,
    absence_is_spent,
    expired_absence,
    has_vote_quorum,
    resolve_sweep_action,
)

NOW = datetime(2026, 10, 16, 12, 0, 0)


class ExpiredAbsenceTests(SimpleTestCase):
    def test_inactive_presence_is_an_expired_absence(self):
        self.assertTrue(expired_absence('inactive', NOW - timedelta(days=1), NOW))

    def test_reconnecting_past_the_grace_is_an_expired_absence(self):
        self.assertTrue(
            expired_absence('reconnecting', NOW - timedelta(seconds=61), NOW)
        )

    def test_reconnecting_exactly_at_the_grace_boundary_is_expired(self):
        self.assertTrue(
            expired_absence('reconnecting', NOW - timedelta(seconds=60), NOW)
        )

    def test_reconnecting_inside_the_grace_is_not_expired(self):
        self.assertFalse(
            expired_absence('reconnecting', NOW - timedelta(seconds=59), NOW)
        )

    def test_never_socketed_offline_row_is_never_a_vote_target(self):
        # ``offline`` with no disconnection moment never held a socket, so it is
        # only ever reapable (S2).
        self.assertFalse(expired_absence('offline', None, NOW))
        self.assertFalse(expired_absence('offline', NOW - timedelta(days=1), NOW))

    def test_reconnecting_without_a_disconnection_moment_is_not_expired(self):
        self.assertFalse(expired_absence('reconnecting', None, NOW))

    def test_online_presence_is_not_an_expired_absence(self):
        self.assertFalse(expired_absence('online', NOW - timedelta(days=1), NOW))


class AbsenceSpendingTests(SimpleTestCase):
    def test_approved_vote_started_after_the_absence_spends_it(self):
        self.assertTrue(
            absence_is_spent(
                'approved', NOW, NOW - timedelta(seconds=10)
            )
        )

    def test_rejected_vote_started_after_the_absence_spends_it(self):
        # D6: the rejection spends the absence, so the next sweep removes the
        # row regardless of the 'no'.
        self.assertTrue(
            absence_is_spent(
                'rejected', NOW, NOW - timedelta(seconds=10)
            )
        )

    def test_cancelled_vote_does_not_spend_the_absence(self):
        self.assertFalse(
            absence_is_spent(
                'cancelled', NOW, NOW - timedelta(seconds=10)
            )
        )

    def test_pending_vote_does_not_spend_the_absence(self):
        self.assertFalse(
            absence_is_spent(
                'pending', NOW, NOW - timedelta(seconds=10)
            )
        )

    def test_vote_started_before_the_absence_does_not_cover_it(self):
        # Absence identity is the ``disconnected_at`` value: a vote that
        # resolved before this absence began belongs to an older one.
        self.assertFalse(
            absence_is_spent(
                'approved',
                NOW - timedelta(seconds=30),
                NOW - timedelta(seconds=10),
            )
        )

    def test_absence_without_a_moment_is_never_spent(self):
        self.assertFalse(absence_is_spent('approved', NOW, None))


class VoteQuorumTests(SimpleTestCase):
    def test_a_single_connected_voter_does_not_reach_the_quorum(self):
        self.assertFalse(has_vote_quorum(1))

    def test_two_connected_voters_reach_the_quorum(self):
        self.assertTrue(has_vote_quorum(2))

    def test_quorum_constant_is_two(self):
        self.assertEqual(MIN_VOTE_QUORUM, 2)

    def test_quorum_can_be_narrowed_for_other_policies(self):
        self.assertTrue(has_vote_quorum(1, quorum=1))
        self.assertFalse(has_vote_quorum(0, quorum=1))


class SweepActionTests(SimpleTestCase):
    def test_expired_absence_with_quorum_is_included_in_the_vote(self):
        self.assertEqual(
            resolve_sweep_action(
                expired=True, spent=False, already_voting=False, has_quorum=True
            ),
            VOTE,
        )

    def test_expired_absence_without_quorum_is_reaped(self):
        self.assertEqual(
            resolve_sweep_action(
                expired=True, spent=False, already_voting=False, has_quorum=False
            ),
            REAP,
        )

    def test_spent_absence_is_reaped_even_with_quorum(self):
        self.assertEqual(
            resolve_sweep_action(
                expired=True, spent=True, already_voting=False, has_quorum=True
            ),
            REAP,
        )

    def test_absence_with_a_pending_vote_is_left_alone(self):
        self.assertEqual(
            resolve_sweep_action(
                expired=True, spent=False, already_voting=True, has_quorum=True
            ),
            LEAVE,
        )

    def test_pending_vote_wins_over_missing_quorum(self):
        # A vote already in progress is never reaped by the sweep, even if the
        # voters that opened it have since left; its own cancellation rules
        # own that case.
        self.assertEqual(
            resolve_sweep_action(
                expired=True, spent=False, already_voting=True, has_quorum=False
            ),
            LEAVE,
        )

    def test_non_expired_absence_is_reaped(self):
        self.assertEqual(
            resolve_sweep_action(
                expired=False, spent=False, already_voting=False, has_quorum=True
            ),
            REAP,
        )
