"""Web flows: registration, sign-in, the couple page and invitation links."""

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from couples import services
from couples.models import Invitation, Membership

PASSWORD = "a-long-passphrase-1"


def make_user(email):
    return get_user_model().objects.create_user(email=email, password=PASSWORD)


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def register(self, email="new@example.com", password=PASSWORD, confirm=None, client=None):
        return (client or self.client).post("/accounts/register/", {
            "display_name": "New", "email": email, "password1": password, "password2": confirm or password,
        })

    def test_registering_creates_the_account_and_signs_in(self):
        response = self.register("New@Example.com")
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)
        user = get_user_model().objects.get()
        self.assertEqual(user.email, "new@example.com")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(self.client.get("/space/").status_code, 200)

    def test_email_already_registered_in_any_case_is_refused(self):
        make_user("new@example.com")
        response = self.register("NEW@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_weak_or_mismatched_passwords_are_refused(self):
        for password, confirm in [("12345678", None), ("password", None), (PASSWORD, PASSWORD + "x")]:
            with self.subTest(password=password):
                self.register(f"{len(password)}{confirm is None}@example.com", password, confirm)
        self.assertFalse(get_user_model().objects.exists())

    def test_csrf_token_is_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.register(client=client).status_code, 403)
        self.assertFalse(get_user_model().objects.exists())

    def test_repeated_attempts_are_rate_limited(self):
        statuses = [self.register(f"user{n}@example.com", "short").status_code for n in range(11)]
        self.assertEqual(statuses[-1], 429)


class SignInTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user("ann@example.com")

    def test_sign_in_with_email_and_password(self):
        response = self.client.post("/accounts/login/", {"username": "Ann@Example.com", "password": PASSWORD})
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)

    def test_wrong_password_is_refused_without_detail(self):
        response = self.client.post("/accounts/login/", {"username": "ann@example.com", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_repeated_attempts_are_rate_limited(self):
        statuses = [
            self.client.post("/accounts/login/", {"username": "ann@example.com", "password": "wrong"}).status_code
            for _ in range(11)
        ]
        self.assertEqual(statuses[-1], 429)

    def test_sign_out_requires_post(self):
        client = signed_in(self.user)
        self.assertEqual(client.get("/accounts/logout/").status_code, 405)
        client.post("/accounts/logout/")
        self.assertNotIn("_auth_user_id", client.session)

    def test_couple_page_requires_sign_in(self):
        response = self.client.get("/space/")
        self.assertRedirects(response, "/accounts/login/?next=/space/", fetch_redirect_response=False)


class CouplePageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ann = make_user("ann@example.com")
        self.client = signed_in(self.ann)

    def test_start_a_couple(self):
        self.client.post("/space/", {"action": "create_couple"})
        self.assertIsNotNone(services.active_couple(self.ann))

    def test_invitation_link_is_shown_once(self):
        self.client.post("/space/", {"action": "create_couple"})
        self.client.post("/space/", {"action": "create_invite"})
        first = self.client.get("/space/").content.decode()
        self.assertIn("/invite/", first)
        second = self.client.get("/space/").content.decode()
        self.assertNotIn("http://testserver/invite/", second)
        self.assertEqual(Invitation.objects.count(), 1)

    def test_revoke_invitation(self):
        self.client.post("/space/", {"action": "create_couple"})
        self.client.post("/space/", {"action": "create_invite"})
        self.client.post("/space/", {"action": "revoke_invites"})
        self.assertIsNotNone(Invitation.objects.get().revoked_at)

    def test_actions_require_post_and_sign_in(self):
        self.assertEqual(Client().post("/space/", {"action": "create_couple"}).status_code, 302)
        self.assertFalse(Membership.objects.exists())


class InvitationLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ann, self.ben = make_user("ann@example.com"), make_user("ben@example.com")
        services.create_couple(self.ann)
        self.token = services.create_invitation(self.ann)

    def test_signed_out_visitor_is_sent_to_sign_in_without_the_token_in_the_url(self):
        client = Client()
        response = client.get(f"/invite/{self.token}/")
        self.assertRedirects(response, "/accounts/login/?next=/space/", fetch_redirect_response=False)
        self.assertNotIn(self.token, response["Location"])

    def test_opening_the_link_does_not_join_until_accepted(self):
        client = signed_in(self.ben)
        client.get(f"/invite/{self.token}/")
        self.assertIsNone(services.active_couple(self.ben))
        page = client.get("/space/").content.decode()
        self.assertIn("accept_invite", page)
        self.assertNotIn(self.token, page)

    def test_accepting_joins_the_couple(self):
        client = signed_in(self.ben)
        client.get(f"/invite/{self.token}/")
        client.post("/space/", {"action": "accept_invite"})
        self.assertEqual(services.active_couple(self.ben), services.active_couple(self.ann))

    def test_used_link_is_refused(self):
        signed = signed_in(self.ben)
        signed.get(f"/invite/{self.token}/")
        signed.post("/space/", {"action": "accept_invite"})
        cy = signed_in(make_user("cy@example.com"))
        cy.get(f"/invite/{self.token}/")
        response = cy.post("/space/", {"action": "accept_invite"}, follow=True)
        self.assertIn("invalid or has expired", response.content.decode())
        self.assertIsNone(services.active_couple(get_user_model().objects.get(email="cy@example.com")))

    def test_expired_link_is_refused(self):
        Invitation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        client = signed_in(self.ben)
        client.get(f"/invite/{self.token}/")
        response = client.post("/space/", {"action": "accept_invite"}, follow=True)
        self.assertIn("invalid or has expired", response.content.decode())

    def test_third_member_is_refused(self):
        client = signed_in(self.ben)
        client.get(f"/invite/{self.token}/")
        client.post("/space/", {"action": "accept_invite"})
        with self.assertRaises(services.CoupleFull):
            services.create_invitation(self.ann)


class FragmentInvitationTests(TestCase):
    """New links carry the token after "#", which browsers never send, so it
    stays out of server and proxy logs; the page posts it instead."""

    def setUp(self):
        cache.clear()
        self.ann, self.ben = make_user("ann@example.com"), make_user("ben@example.com")
        self.client = signed_in(self.ann)
        self.client.post("/space/", {"action": "create_couple"})

    def new_link(self):
        self.client.post("/space/", {"action": "create_invite"})
        page = self.client.get("/space/").content.decode()
        match = re.search(r"http://testserver/invite/#([A-Za-z0-9_-]+)", page)
        self.assertIsNotNone(match, "the link should carry the token in the fragment")
        return match.group(1)

    def test_new_links_put_the_token_in_the_fragment(self):
        token = self.new_link()
        self.assertEqual(Invitation.objects.get().token_hash, services.hash_token(token))

    def test_invite_page_holds_no_token_and_sets_the_csrf_cookie(self):
        response = Client().get("/invite/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)
        self.assertContains(response, "location.hash")
        self.assertContains(response, 'name="token"')

    def test_posting_the_token_works_like_opening_an_old_link(self):
        token = self.new_link()
        visitor = Client()
        response = visitor.post("/invite/", {"token": token})
        self.assertRedirects(response, "/accounts/login/?next=/space/", fetch_redirect_response=False)
        self.assertNotIn(token, response["Location"])
        ben = signed_in(self.ben)
        self.assertRedirects(ben.post("/invite/", {"token": token}), "/space/", fetch_redirect_response=False)
        self.assertIsNone(services.active_couple(self.ben))  # Not joined until accepted.
        ben.post("/space/", {"action": "accept_invite"})
        self.assertEqual(services.active_couple(self.ben), services.active_couple(self.ann))

    def test_posting_needs_the_csrf_token(self):
        token = self.new_link()
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post("/invite/", {"token": token}).status_code, 403)

    def test_empty_or_oversized_tokens_are_not_kept(self):
        visitor = Client()
        for token in ["", "x" * 500]:
            visitor.post("/invite/", {"token": token})
            self.assertNotIn("pending_invite", visitor.session)

    def test_old_path_links_still_work_until_they_expire(self):
        token = services.create_invitation(self.ann)
        ben = signed_in(self.ben)
        ben.get(f"/invite/{token}/")
        ben.post("/space/", {"action": "accept_invite"})
        self.assertEqual(services.active_couple(self.ben), services.active_couple(self.ann))


class FrontendModeTests(TestCase):
    def test_play_page_uses_the_server_room_for_members(self):
        ann = make_user("ann@example.com")
        services.create_couple(ann)
        html = signed_in(ann).get("/play/?mode=questions").content.decode()
        self.assertIn("js/room-client.js", html)
        self.assertIn("/ws/room/questions/", html)
        # Next and Reset are requests to the server, not local deck moves.
        self.assertIn('room.act("next")', html)
        self.assertIn('room.act("reset")', html)

    def test_home_page_links_to_accounts(self):
        html = self.client.get("/").content.decode()
        self.assertIn('href="/accounts/login/"', html)
        self.assertIn('href="/accounts/register/"', html)
