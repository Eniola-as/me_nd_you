import hashlib
import threading
from datetime import timedelta
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from couples import services
from couples.models import Couple, Invitation, Membership


def make_user(email):
    return get_user_model().objects.create_user(email=email, password="a-long-passphrase-1")


def plant_invitation(couple, creator, raw):
    """An extra valid invitation, bypassing the one-pending-invite rule."""
    return Invitation.objects.create(
        couple=couple,
        created_by=creator,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(days=1),
    )


class InvitationTokenTests(TestCase):
    def setUp(self):
        self.ann = make_user("ann@example.com")
        self.couple = services.create_couple(self.ann)

    def test_token_is_long_random_and_url_safe(self):
        tokens = {services.create_invitation(self.ann) for _ in range(5)}
        self.assertEqual(len(tokens), 5)
        for token in tokens:
            self.assertGreaterEqual(len(token), 43)  # 32 random bytes.
            self.assertRegex(token, r"^[A-Za-z0-9_-]+$")

    def test_only_the_hash_is_stored(self):
        token = services.create_invitation(self.ann)
        invitation = Invitation.objects.get()
        self.assertEqual(invitation.token_hash, hashlib.sha256(token.encode()).hexdigest())
        stored = " ".join(str(v) for v in Invitation.objects.values().get().values())
        self.assertNotIn(token, stored)

    def test_new_invitation_revokes_the_previous_pending_one(self):
        first = services.create_invitation(self.ann)
        services.create_invitation(self.ann)
        with self.assertRaises(services.InvalidInvitation):
            services.redeem_invitation(make_user("ben@example.com"), first)

    def test_invitation_expires(self):
        token = services.create_invitation(self.ann)
        Invitation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(services.InvalidInvitation):
            services.redeem_invitation(make_user("ben@example.com"), token)


class RedemptionTests(TestCase):
    def setUp(self):
        self.ann, self.ben = make_user("ann@example.com"), make_user("ben@example.com")
        self.couple = services.create_couple(self.ann)
        self.token = services.create_invitation(self.ann)

    def test_redeeming_adds_the_partner(self):
        couple = services.redeem_invitation(self.ben, self.token)
        self.assertEqual(couple, self.couple)
        self.assertEqual(services.active_couple(self.ben), self.couple)
        self.assertEqual(sorted(m.slot for m in Membership.objects.active()), [1, 2])

    def test_invitation_can_be_used_once(self):
        services.redeem_invitation(self.ben, self.token)
        with self.assertRaises(services.InvalidInvitation):
            services.redeem_invitation(make_user("cy@example.com"), self.token)

    def test_revoked_invitation_is_rejected(self):
        services.revoke_invitations(self.ann)
        with self.assertRaises(services.InvalidInvitation):
            services.redeem_invitation(self.ben, self.token)

    def test_unknown_used_expired_and_revoked_tokens_fail_the_same_way(self):
        # Used: Ben joins Ann's couple with self.token.
        services.redeem_invitation(self.ben, self.token)
        # Expired and revoked: invitations from two other couples.
        cy, di = make_user("cy@example.com"), make_user("di@example.com")
        services.create_couple(cy)
        expired = services.create_invitation(cy)
        Invitation.objects.filter(created_by=cy).update(expires_at=timezone.now() - timedelta(seconds=1))
        services.create_couple(di)
        revoked = services.create_invitation(di)
        services.revoke_invitations(di)

        messages = set()
        for n, token in enumerate(["not-a-real-token", self.token, expired, revoked]):
            with self.assertRaises(services.InvalidInvitation) as caught:
                services.redeem_invitation(make_user(f"x{n}@example.com"), token)
            messages.add(str(caught.exception))
        self.assertEqual(len(messages), 1)

    def test_creator_cannot_redeem_their_own_invitation(self):
        with self.assertRaises(services.AlreadyInCouple):
            services.redeem_invitation(self.ann, self.token)
        self.assertIsNone(Invitation.objects.get().used_at)  # Still usable by the partner.

    def test_user_already_in_another_couple_cannot_join(self):
        cy = make_user("cy@example.com")
        services.create_couple(cy)
        with self.assertRaises(services.AlreadyInCouple):
            services.redeem_invitation(cy, self.token)
        self.assertIsNone(Invitation.objects.get().used_at)

    def test_full_couple_cannot_create_invitations(self):
        services.redeem_invitation(self.ben, self.token)
        with self.assertRaises(services.CoupleFull):
            services.create_invitation(self.ann)

    def test_third_member_is_refused_even_with_a_second_valid_invitation(self):
        plant_invitation(self.couple, self.ann, "second-valid-invitation")
        services.redeem_invitation(self.ben, self.token)
        with self.assertRaises(services.CoupleFull):
            services.redeem_invitation(make_user("cy@example.com"), "second-valid-invitation")
        self.assertEqual(Membership.objects.active().filter(couple=self.couple).count(), 2)

    def test_only_members_can_invite(self):
        with self.assertRaises(services.NotInCouple):
            services.create_invitation(make_user("cy@example.com"))


class DatabaseConstraintTests(TestCase):
    def setUp(self):
        self.ann, self.ben = make_user("ann@example.com"), make_user("ben@example.com")
        self.couple = services.create_couple(self.ann)

    def test_database_refuses_a_second_active_couple_for_a_user(self):
        other = Couple.objects.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(couple=other, user=self.ann, slot=1)

    def test_database_refuses_two_members_in_one_slot(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(couple=self.couple, user=self.ben, slot=1)

    def test_database_refuses_a_third_slot(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(couple=self.couple, user=self.ben, slot=3)

    def test_a_user_who_left_may_join_another_couple(self):
        Membership.objects.filter(user=self.ann).update(left_at=timezone.now())
        self.assertIsNotNone(services.create_couple(self.ann))

    def test_cannot_start_a_second_couple(self):
        with self.assertRaises(services.AlreadyInCouple):
            services.create_couple(self.ann)


@skipUnless(connection.vendor == "postgresql", "Real concurrency needs PostgreSQL.")
class ConcurrentRedemptionTests(TransactionTestCase):
    # Restore the database snapshot afterwards, like the other database-level
    # test classes. Without it, this class's cleanup re-creates content types
    # with new ids and later snapshot restores collide with them.
    serialized_rollback = True

    def race(self, attempts):
        barrier = threading.Barrier(len(attempts))
        results = []

        def run(fn):
            try:
                barrier.wait()
                fn()
                results.append("ok")
            except services.InvitationError as exc:
                results.append(type(exc).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(fn,)) for fn in attempts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return sorted(results)

    def test_two_users_racing_for_one_invitation(self):
        ann = make_user("ann@example.com")
        couple = services.create_couple(ann)
        token = services.create_invitation(ann)
        ben, cy = make_user("ben@example.com"), make_user("cy@example.com")
        results = self.race([
            lambda: services.redeem_invitation(ben, token),
            lambda: services.redeem_invitation(cy, token),
        ])
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(Membership.objects.active().filter(couple=couple).count(), 2)

    def test_two_invitations_racing_for_the_last_place(self):
        ann = make_user("ann@example.com")
        couple = services.create_couple(ann)
        plant_invitation(couple, ann, "race-token-0")
        plant_invitation(couple, ann, "race-token-1")
        ben, cy = make_user("ben@example.com"), make_user("cy@example.com")
        results = self.race([
            lambda: services.redeem_invitation(ben, "race-token-0"),
            lambda: services.redeem_invitation(cy, "race-token-1"),
        ])
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(Membership.objects.active().filter(couple=couple).count(), 2)
