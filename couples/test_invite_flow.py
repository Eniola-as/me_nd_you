"""The invitation flow: what the recipient sees before accepting, joining
after signing in or up, pasting a link, switching from another space only
after an explicit confirmation, and every way an invitation can fail."""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import DatabaseError
from django.test import Client, TestCase
from django.utils import timezone

from accounts.consents import CONSENT_KINDS, record_consents
from couples import services
from couples.models import Couple, Invitation, Membership

PASSWORD = "a-long-passphrase-1"
TICKED = {box: "on" for box in ["confirm_age", "agree_terms", "agree_sensitive", "agree_transfer"]}


def make_user(email, name=""):
    user = get_user_model().objects.create_user(email=email, password=PASSWORD, display_name=name)
    record_consents(user, CONSENT_KINDS)
    return user


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


class InviteSetup(TestCase):
    def setUp(self):
        cache.clear()
        self.ann = make_user("ann@example.com", "Ann")
        self.ann_couple = services.create_couple(self.ann)
        self.token = services.create_invitation(self.ann)

    def open_link(self, client, token=None):
        return client.post("/invite/", {"token": token or self.token})


class SeeingTheInvitationTests(InviteSetup):
    def test_the_space_page_says_who_invited_you_before_you_accept(self):
        ben = signed_in(make_user("ben@example.com"))
        self.open_link(ben)
        page = ben.get("/space/").content.decode()
        self.assertIn("Ann invited you", page)
        self.assertIn('value="accept_invite"', page)
        self.assertIn('value="dismiss_invite"', page)
        self.assertNotIn(self.token, page)
        self.assertNotIn("ann@example.com", page)

    def test_declining_forgets_the_invitation_and_leaves_it_usable(self):
        ben_user = make_user("ben@example.com")
        ben = signed_in(ben_user)
        self.open_link(ben)
        ben.post("/space/", {"action": "dismiss_invite"})
        self.assertNotIn("Ann invited you", ben.get("/space/").content.decode())
        self.assertIsNone(Invitation.objects.get().used_at)

    def test_an_invalid_link_says_so_instead_of_offering_to_join(self):
        ben = signed_in(make_user("ben@example.com"))
        self.open_link(ben, "not-a-real-token")
        page = ben.get("/space/").content.decode()
        self.assertIn("invalid or has expired", page)
        self.assertNotIn('value="accept_invite"', page)

    def test_a_link_to_a_space_that_closed_meanwhile_is_invalid(self):
        ben = signed_in(make_user("ben@example.com"))
        self.open_link(ben)
        services.close_couple(self.ann)
        response = ben.post("/space/", {"action": "accept_invite"}, follow=True)
        self.assertIn("invalid or has expired", response.content.decode())
        self.assertIsNone(services.active_couple(get_user_model().objects.get(email="ben@example.com")))

    def test_revoked_links_are_refused(self):
        ben = signed_in(make_user("ben@example.com"))
        self.open_link(ben)
        services.revoke_invitations(self.ann)
        response = ben.post("/space/", {"action": "accept_invite"}, follow=True)
        self.assertIn("invalid or has expired", response.content.decode())


class JoiningThroughSignInTests(InviteSetup):
    def test_signing_in_keeps_the_invitation(self):
        make_user("ben@example.com")
        client = Client()
        self.open_link(client)
        response = client.post("/accounts/login/?next=/space/",
                               {"username": "ben@example.com", "password": PASSWORD}, follow=True)
        self.assertIn("Ann invited you", response.content.decode())

    def test_signing_up_keeps_the_invitation_even_after_visiting_sign_in(self):
        client = Client()
        self.open_link(client)
        client.get("/accounts/login/?next=/space/")
        response = client.post("/accounts/register/", {
            "display_name": "Ben", "email": "ben@example.com", "password1": PASSWORD,
            "password2": PASSWORD, **TICKED,
        }, follow=True)
        self.assertIn("Ann invited you", response.content.decode())
        client.post("/space/", {"action": "accept_invite"})
        ben = get_user_model().objects.get(email="ben@example.com")
        self.assertEqual(services.active_couple(ben), self.ann_couple)

    def test_sign_in_and_sign_up_offer_to_join_with_an_invite(self):
        for url in ["/accounts/login/", "/accounts/register/"]:
            with self.subTest(url=url):
                page = Client().get(url).content.decode()
                self.assertIn("Have an invite?", page)
                self.assertIn('href="/invite/"', page)

    def test_sign_in_mentions_a_waiting_invitation(self):
        client = Client()
        self.open_link(client)
        self.assertIn("Sign in or create an account to see your invitation",
                      client.get("/accounts/login/?next=/space/").content.decode())

    def test_redirects_after_signing_in_stay_on_this_site(self):
        make_user("ben@example.com")
        client = Client()
        self.open_link(client)
        response = client.post("/accounts/login/?next=https://evil.example/",
                               {"username": "ben@example.com", "password": PASSWORD})
        self.assertFalse(response["Location"].startswith("https://evil.example"))


class PastingALinkTests(InviteSetup):
    def test_pasting_the_whole_link_on_the_space_page_opens_the_invitation(self):
        ben = signed_in(make_user("ben@example.com"))
        ben.post("/space/", {"action": "use_invite_link", "invite_link": f"https://me-nd-you.onrender.com/invite/#{self.token}"})
        self.assertIn("Ann invited you", ben.get("/space/").content.decode())

    def test_pasting_just_the_code_works_too(self):
        ben = signed_in(make_user("ben@example.com"))
        ben.post("/space/", {"action": "use_invite_link", "invite_link": f"  {self.token}  "})
        self.assertIn("Ann invited you", ben.get("/space/").content.decode())

    def test_pasting_nonsense_explains_what_to_paste(self):
        ben = signed_in(make_user("ben@example.com"))
        response = ben.post("/space/", {"action": "use_invite_link", "invite_link": "hello"}, follow=True)
        self.assertIn("invalid or has expired", response.content.decode())

    def test_signed_out_visitors_can_paste_a_link_on_the_invite_page(self):
        client = Client()
        response = client.post("/invite/", {"link": f"https://x/invite/#{self.token}"})
        self.assertRedirects(response, "/accounts/login/?next=/space/", fetch_redirect_response=False)
        make_user("ben@example.com")
        page = client.post("/accounts/login/?next=/space/",
                           {"username": "ben@example.com", "password": PASSWORD}, follow=True)
        self.assertIn("Ann invited you", page.content.decode())

    def test_the_invite_page_has_a_paste_box_for_when_there_is_no_link(self):
        page = Client().get("/invite/").content.decode()
        self.assertIn('name="link"', page)

    def test_the_space_page_offers_the_paste_box_to_people_without_a_partner(self):
        ben = signed_in(make_user("ben@example.com"))
        self.assertIn('name="invite_link"', ben.get("/space/").content.decode())


class AlreadyAMemberTests(InviteSetup):
    def test_opening_your_own_spaces_link_joins_nothing_and_says_so(self):
        ann = signed_in(self.ann)
        self.open_link(ann)
        page = ann.get("/space/").content.decode()
        self.assertIn("You're already in this space", page)
        ann.post("/space/", {"action": "accept_invite"})
        self.assertEqual(Membership.objects.filter(user=self.ann).count(), 1)
        self.assertIsNone(Invitation.objects.get().used_at)

    def test_accepting_twice_never_makes_a_second_membership(self):
        ben_user = make_user("ben@example.com")
        ben = signed_in(ben_user)
        self.open_link(ben)
        ben.post("/space/", {"action": "accept_invite"})
        self.open_link(ben)
        response = ben.post("/space/", {"action": "accept_invite"}, follow=True)
        self.assertEqual(Membership.objects.filter(user=ben_user).count(), 1)
        self.assertNotIn("Something went wrong", response.content.decode())


class SwitchingSpacesTests(InviteSetup):
    def setUp(self):
        super().setUp()
        self.ben = make_user("ben@example.com", "Ben")
        self.cy = make_user("cy@example.com", "Cy")
        self.ben_couple = services.create_couple(self.ben)
        services.redeem_invitation(self.cy, services.create_invitation(self.ben))
        self.client_ben = signed_in(self.ben)
        self.open_link(self.client_ben)

    def test_the_page_explains_what_switching_does_before_anything_happens(self):
        page = self.client_ben.get("/space/").content.decode()
        self.assertIn("closes your current couple space for both of you", page)
        self.assertIn('name="confirm_switch"', page)
        # Accurate about the data: nothing is deleted straight away.
        self.assertIn("30 days", page)
        self.assertEqual(services.active_couple(self.ben), self.ben_couple)

    def test_accepting_without_confirming_changes_nothing_and_keeps_the_invitation(self):
        response = self.client_ben.post("/space/", {"action": "accept_invite"}, follow=True)
        self.assertIn("Tick the box", response.content.decode())
        self.assertEqual(services.active_couple(self.ben), self.ben_couple)
        self.assertIsNone(Couple.objects.get(pk=self.ben_couple.pk).closed_at)
        self.assertIn("Ann invited you", response.content.decode())

    def test_confirming_closes_the_old_space_and_joins_the_new_one(self):
        self.client_ben.post("/space/", {"action": "accept_invite", "confirm_switch": "yes"})
        self.assertEqual(services.active_couple(self.ben), self.ann_couple)
        self.assertIsNotNone(Couple.objects.get(pk=self.ben_couple.pk).closed_at)
        self.assertIsNone(services.active_couple(self.cy))
        # The old partner gets the usual neutral closure email.
        self.assertIn("cy@example.com", [m.to[0] for m in mail.outbox])

    def test_a_failure_while_joining_keeps_the_old_space_open(self):
        with mock.patch("couples.services._add_member", side_effect=DatabaseError("boom")):
            response = self.client_ben.post("/space/", {"action": "accept_invite", "confirm_switch": "yes"},
                                            follow=True)
        self.assertEqual(services.active_couple(self.ben), self.ben_couple)
        self.assertEqual(services.active_couple(self.cy), self.ben_couple)
        self.assertIsNone(Couple.objects.get(pk=self.ben_couple.pk).closed_at)
        self.assertIsNone(Invitation.objects.get(couple=self.ann_couple, revoked_at__isnull=True).used_at)
        page = response.content.decode()
        self.assertIn("Nothing has changed", page)
        self.assertNotIn("boom", page)

    def test_an_invalid_invitation_never_closes_the_current_space(self):
        Invitation.objects.filter(couple=self.ann_couple).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.client_ben.post("/space/", {"action": "accept_invite", "confirm_switch": "yes"})
        self.assertEqual(services.active_couple(self.ben), self.ben_couple)
        self.assertIsNone(Couple.objects.get(pk=self.ben_couple.pk).closed_at)

    def test_a_full_destination_never_closes_the_current_space(self):
        services.redeem_invitation(make_user("dee@example.com"), services.create_invitation(self.ann))
        self.client_ben.post("/space/", {"action": "accept_invite", "confirm_switch": "yes"})
        self.assertEqual(services.active_couple(self.ben), self.ben_couple)
        self.assertIsNone(Couple.objects.get(pk=self.ben_couple.pk).closed_at)

    def test_the_service_refuses_to_switch_without_confirmation(self):
        with self.assertRaises(services.SwitchNeedsConfirmation):
            services.redeem_invitation(self.ben, self.token)


class SecondAcceptanceTests(TestCase):
    # True simultaneous acceptance is covered on PostgreSQL by
    # couples.tests.ConcurrentRedemptionTests.
    def test_one_invitation_accepted_twice_makes_one_member(self):
        ann = make_user("ann@example.com")
        services.create_couple(ann)
        token = services.create_invitation(ann)
        ben, cy = make_user("ben@example.com"), make_user("cy@example.com")
        services.redeem_invitation(ben, token)
        with self.assertRaises(services.InvalidInvitation):
            services.redeem_invitation(cy, token)
        self.assertEqual(Membership.objects.active().filter(couple=services.active_couple(ann)).count(), 2)
        self.assertIsNone(services.active_couple(cy))
