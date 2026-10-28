"""The 18+ confirmation and explicit consents: four separate boxes at sign-up,
each stored with its time and policy version; existing accounts must accept
before using anything; the profile lists them."""

import importlib

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

import me_nd_you.asgi
from accounts.consents import CONSENT_KINDS, missing_consents, record_consents
from accounts.models import Consent
from accounts.testing import without_auto_consent
from chat.tests import with_chat_key
from couples import services as couples
from game.models import CustomQuestion

PASSWORD = "a-long-passphrase-1"
BOXES = ["confirm_age", "agree_terms", "agree_sensitive", "agree_transfer"]


def sign_up_data(**overrides):
    data = {"display_name": "Ann", "email": "ann@example.com", "password1": PASSWORD,
            "password2": PASSWORD, **{box: "on" for box in BOXES}}
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


class SignUpConsentTests(TestCase):
    def test_the_form_has_four_separate_required_boxes(self):
        html = Client().get("/accounts/register/").content.decode()
        for box in BOXES:
            self.assertIn(f'name="{box}"', html)
        self.assertIn("I confirm I&#x27;m 18 or older.", html)
        self.assertIn('href="/terms/"', html)
        self.assertIn('href="/privacy/"', html)
        self.assertNotIn("checked", html)  # Nothing is ticked for you.

    def test_each_box_is_required(self):
        for box in BOXES:
            with self.subTest(box), without_auto_consent():
                response = Client().post("/accounts/register/", sign_up_data(**{box: None}))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(get_user_model().objects.exists())

    def test_signing_up_stores_each_consent_with_its_time_and_version(self):
        with without_auto_consent():
            before = timezone.now()
            response = Client().post("/accounts/register/", sign_up_data())
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)
        user = get_user_model().objects.get()
        consents = Consent.objects.filter(user=user)
        self.assertEqual(sorted(c.kind for c in consents), sorted(CONSENT_KINDS))
        for consent in consents:
            self.assertEqual(consent.policy_version, settings.POLICY_VERSION)
            self.assertGreaterEqual(consent.given_at, before)
        self.assertEqual(missing_consents(user), [])


class ExistingAccountTests(TestCase):
    def setUp(self):
        with without_auto_consent():
            self.ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
        couples.create_couple(self.ann)
        self.client.force_login(self.ann)

    def test_every_page_asks_for_consent_first(self):
        for page in ["/space/", "/modes/", "/play/?mode=questions", "/accounts/profile/"]:
            with self.subTest(page):
                response = self.client.get(page)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/accounts/consent/?next="), response["Location"])

    def test_signing_in_leads_to_the_consent_page(self):
        client = Client()
        response = client.post("/accounts/login/", {"username": "ann@example.com", "password": PASSWORD},
                               follow=True)
        self.assertEqual(response.redirect_chain[-1][0].split("?")[0], "/accounts/consent/")

    def test_the_api_refuses_without_redirecting(self):
        response = self.client.post("/api/space/custom-questions/", {"mode": "questions", "text": "Hi?"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "consent_required")
        self.assertFalse(CustomQuestion.objects.exists())

    def test_policy_pages_and_signing_out_still_work(self):
        for page in ["/privacy/", "/terms/"]:
            self.assertEqual(self.client.get(page).status_code, 200)
        self.client.post("/accounts/logout/")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_consent_page_shows_only_what_is_missing(self):
        record_consents(self.ann, ["age_18"])
        html = self.client.get("/accounts/consent/").content.decode()
        self.assertNotIn('name="confirm_age"', html)
        for box in BOXES[1:]:
            self.assertIn(f'name="{box}"', html)

    def test_accepting_everything_unlocks_the_app_and_returns_you(self):
        response = self.client.post("/accounts/consent/", {**{box: "on" for box in BOXES}, "next": "/modes/"})
        self.assertRedirects(response, "/modes/", fetch_redirect_response=False)
        self.assertEqual(missing_consents(self.ann), [])
        self.assertEqual(self.client.get("/space/").status_code, 200)

    def test_a_partial_answer_records_nothing(self):
        response = self.client.post("/accounts/consent/", {"confirm_age": "on", "agree_terms": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Consent.objects.filter(user=self.ann).exists())

    def test_an_unsafe_next_url_is_ignored(self):
        response = self.client.post("/accounts/consent/",
                                    {**{box: "on" for box in BOXES}, "next": "https://evil.example/"})
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)

    def test_a_new_policy_version_asks_again_but_not_for_the_age_confirmation(self):
        record_consents(self.ann, CONSENT_KINDS)
        self.assertEqual(self.client.get("/space/").status_code, 200)
        with override_settings(POLICY_VERSION="2027-01-01"):
            self.assertEqual(sorted(missing_consents(self.ann)), sorted(set(CONSENT_KINDS) - {"age_18"}))
            response = self.client.get("/space/")
            self.assertEqual(response.status_code, 302)
            html = self.client.get("/accounts/consent/").content.decode()
            self.assertNotIn('name="confirm_age"', html)
            self.assertIn("updated", html)


class ProfileConsentListTests(TestCase):
    def test_the_profile_lists_each_consent_with_its_date_and_how_to_withdraw(self):
        with without_auto_consent():
            ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
        record_consents(ann, CONSENT_KINDS)
        Consent.objects.filter(user=ann).update(given_at=timezone.make_aware(timezone.datetime(2026, 11, 2, 9)))
        client = Client()
        client.force_login(ann)
        html = client.get("/accounts/profile/").content.decode()
        self.assertIn("2 November 2026", html)
        self.assertIn("18 or older", html)
        self.assertIn("Terms of Use and Privacy Policy", html)
        self.assertIn("intimate", html)
        self.assertIn("outside Nigeria", html)
        self.assertIn("delete your account", html)


class AutoConsentTests(TestCase):
    def test_test_users_get_the_current_consents_unless_switched_off(self):
        # Only the test runner does this, so the many tests that create users
        # directly aren't all sent to the consent page.
        ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
        self.assertEqual(missing_consents(ann), [])
        with without_auto_consent():
            ben = get_user_model().objects.create_user(email="ben@example.com", password=PASSWORD)
        self.assertEqual(sorted(missing_consents(ben)), sorted(CONSENT_KINDS))


@with_chat_key
@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class SocketConsentTests(TransactionTestCase):
    serialized_rollback = True

    def test_game_and_chat_sockets_refuse_without_consent(self):
        with without_auto_consent():
            ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
        couples.create_couple(ann)
        client = Client()
        client.force_login(ann)
        cookie = f"sessionid={client.cookies['sessionid'].value}".encode()

        async def scenario():
            application = importlib.reload(me_nd_you.asgi).application
            results = {}
            for path in ["/ws/room/questions/questions/", "/ws/chat/"]:
                page = WebsocketCommunicator(application, path,
                                             headers=[(b"origin", b"https://me-nd-you.onrender.com"),
                                                      (b"cookie", cookie)])
                results[path], _ = await page.connect()
                await page.disconnect()
            return results

        self.assertEqual(async_to_sync(scenario)(), {"/ws/room/questions/questions/": False, "/ws/chat/": False})
