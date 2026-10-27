"""Moving a secret-word couple over to accounts. A space member claims the old
couple by its names and secret word; nothing is copied or deleted. Once both
partners confirm, the secret word keeps working for a 14-day grace period,
then stops only if the move is complete; otherwise access stays and the link
is flagged for an admin. Every step can be undone by an admin."""

import importlib
import io
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import dateformat, timezone

import me_nd_you.asgi
from couples import legacy, services
from couples.models import LegacyLink
from game.models import CoupleSession, CustomQuestion
from play.cards import DatabaseCards

PASSWORD = "a-long-passphrase-1"
SECRET = "moonlight"


def make_user(email, name=""):
    return get_user_model().objects.create_user(email=email, password=PASSWORD, display_name=name)


def make_couple(a_email="ann@example.com", b_email="ben@example.com"):
    ann, ben = make_user(a_email, "Ann"), make_user(b_email, "Ben")
    couple = services.create_couple(ann)
    services.redeem_invitation(ben, services.create_invitation(ann))
    return couple, ann, ben


def make_legacy(secret=SECRET):
    session = CoupleSession.objects.create(partner1_name="Ann", partner2_name="Ben", secret_word=secret)
    CustomQuestion.objects.create(couple=session, text="Our old question?", mode="questions")
    return session


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def legacy_login(secret=SECRET):
    return Client().post("/api/login/", {"partner1_name": "Ben", "partner2_name": "Ann", "secret_word": secret},
                         content_type="application/json")


def legacy_questions(secret=SECRET):
    return Client().get("/api/questions/questions/", {"secret": secret}).json()


def date_format(moment):
    return dateformat.format(timezone.localtime(moment), "j F Y")


def past_deadline(link):
    LegacyLink.objects.filter(pk=link.pk).update(retire_at=timezone.now() - timedelta(seconds=1))


class ClaimTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple()
        self.session = make_legacy()

    def test_claim_links_without_copying_or_deleting(self):
        link = legacy.claim(self.ann, "ben", "ANN", SECRET)
        self.assertEqual((link.legacy, link.couple, link.claimed_by), (self.session, self.couple, self.ann))
        self.assertEqual(CustomQuestion.objects.count(), 1)
        self.assertEqual(CustomQuestion.objects.get().couple, self.session)
        self.assertTrue(CoupleSession.objects.filter(pk=self.session.pk, secret_word=SECRET).exists())

    def test_wrong_names_or_secret_are_refused_the_same_way(self):
        for names, secret in [(("Ann", "Cy"), SECRET), (("Ann", "Ben"), "wrong-word"), (("Ann", "Ben"), "")]:
            with self.assertRaises(legacy.NoSuchLegacyCouple):
                legacy.claim(self.ann, *names, secret)
        self.assertFalse(LegacyLink.objects.exists())

    def test_only_a_space_member_can_claim(self):
        with self.assertRaises(services.NotInCouple):
            legacy.claim(make_user("cy@example.com"), "Ann", "Ben", SECRET)

    def test_a_legacy_couple_links_to_one_space_only(self):
        legacy.claim(self.ann, "Ann", "Ben", SECRET)
        _, cy, _ = make_couple("cy@example.com", "di@example.com")
        with self.assertRaises(legacy.AlreadyLinked):
            legacy.claim(cy, "Ann", "Ben", SECRET)
        with self.assertRaises(legacy.AlreadyLinked):  # And a space links one legacy couple.
            make_legacy("other-secret")
            legacy.claim(self.ben, "Ann", "Ben", "other-secret")

    def test_linked_questions_appear_in_the_space(self):
        signed_in(self.ben).get("/api/space/questions/questions/")  # Cached before the claim.
        legacy.claim(self.ann, "Ann", "Ben", SECRET)
        texts =[q["text"] for q in signed_in(self.ben).get("/api/space/questions/questions/").json()]
        self.assertIn("Our old question?", texts)
        cards = DatabaseCards(self.couple, "questions")
        card = next(c for c in cards.all() if c["text"] == "Our old question?")
        self.assertEqual(cards.get(card["key"]), card)

    def test_unlinked_legacy_questions_stay_out_of_spaces(self):
        texts = [q["text"] for q in signed_in(self.ben).get("/api/space/questions/questions/").json()]
        self.assertNotIn("Our old question?", texts)
        question = CustomQuestion.objects.get()
        self.assertIsNone(DatabaseCards(self.couple, "questions").get(f"c:{question.pk}"))

    def test_claiming_keeps_the_secret_word_working(self):
        legacy.claim(self.ann, "Ann", "Ben", SECRET)
        self.assertTrue(legacy_login().json()["success"])
        self.assertIn("Our old question?", [q["text"] for q in legacy_questions()])


class CountdownTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple()
        self.session = make_legacy()
        self.link = legacy.claim(self.ann, "Ann", "Ben", SECRET)

    def test_countdown_waits_for_both_partners(self):
        legacy.mark_ready(self.ann)
        self.link.refresh_from_db()
        self.assertIsNone(self.link.retire_at)

    def test_countdown_waits_for_a_second_member(self):
        lone = make_user("cy@example.com")
        services.create_couple(lone)
        make_legacy("solo-secret")
        link = legacy.claim(lone, "Ann", "Ben", "solo-secret")
        legacy.mark_ready(lone)
        link.refresh_from_db()
        self.assertIsNone(link.retire_at)

    def test_both_ready_starts_a_14_day_grace_period(self):
        legacy.mark_ready(self.ann)
        before = timezone.now()
        legacy.mark_ready(self.ben)
        self.link.refresh_from_db()
        self.assertGreaterEqual(self.link.retire_at, before + timedelta(days=14))
        self.assertLessEqual(self.link.retire_at, timezone.now() + timedelta(days=14))
        self.assertTrue(legacy_login().json()["success"])  # Still works during the grace period.

    def test_withdrawing_stops_the_countdown(self):
        legacy.mark_ready(self.ann)
        legacy.mark_ready(self.ben)
        legacy.withdraw_ready(self.ben)
        self.link.refresh_from_db()
        self.assertIsNone(self.link.retire_at)


class RetirementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple()
        self.session = make_legacy()
        self.link = legacy.claim(self.ann, "Ann", "Ben", SECRET)
        legacy.mark_ready(self.ann)
        legacy.mark_ready(self.ben)

    # Each access point is checked on its own, each as the first request
    # after the deadline, so one refusal can't stand in for another.

    def test_completed_move_retires_the_secret_word_after_the_deadline(self):
        past_deadline(self.link)
        response = legacy_login()
        self.assertEqual(response.status_code, 403)
        self.assertIn("sign in", response.json()["detail"].lower())
        self.link.refresh_from_db()
        self.assertIsNotNone(self.link.retired_at)

    def test_retired_secret_loads_no_questions(self):
        self.assertNotEqual(legacy_questions(), [])  # Works before the deadline.
        cache.clear()
        past_deadline(self.link)
        self.assertEqual(legacy_questions(), [])

    def test_retired_secret_cannot_add_custom_questions(self):
        def add(text):
            return Client().post("/api/add-custom-question/", {"secret": SECRET, "text": text, "mode": "questions"},
                                 content_type="application/json")

        self.assertEqual(add("Before?").status_code, 201)  # The route and payload are right.
        past_deadline(self.link)
        self.assertEqual(add("After?").status_code, 404)
        self.assertFalse(CustomQuestion.objects.filter(text="After?").exists())

    def test_retirement_keeps_the_record_and_its_questions(self):
        past_deadline(self.link)
        legacy_login()
        self.assertTrue(CoupleSession.objects.filter(pk=self.session.pk).exists())
        texts = [q["text"] for q in signed_in(self.ann).get("/api/space/questions/questions/").json()]
        self.assertIn("Our old question?", texts)

    def test_incomplete_move_keeps_access_and_is_flagged(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.close_couple(self.ben)
        past_deadline(self.link)
        self.assertTrue(legacy_login().json()["success"])
        self.link.refresh_from_db()
        self.assertIsNone(self.link.retired_at)
        self.assertIsNotNone(self.link.needs_resolution_at)

    def test_admin_can_clear_a_retirement(self):
        past_deadline(self.link)
        legacy_login()
        legacy.clear_retirement(self.link)
        self.assertTrue(legacy_login().json()["success"])
        self.link.refresh_from_db()
        self.assertIsNone(self.link.retire_at)

    def test_admin_can_unlink(self):
        signed_in(self.ann).get("/api/space/questions/questions/")  # Cached while linked.
        legacy.unlink(self.link)
        texts = [q["text"] for q in signed_in(self.ann).get("/api/space/questions/questions/").json()]
        self.assertNotIn("Our old question?", texts)
        self.assertTrue(legacy_login().json()["success"])
        self.assertEqual(legacy.claim(self.ben, "Ann", "Ben", SECRET).couple, self.couple)  # Claimable again.

    def test_admin_actions(self):
        admin = get_user_model().objects.create_superuser(email="admin@example.com", password=PASSWORD)
        client = signed_in(admin)
        past_deadline(self.link)
        legacy_login()
        client.post("/admin/couples/legacylink/", {"action": "clear_retirements", "_selected_action": [str(self.link.pk)]})
        self.assertTrue(legacy_login().json()["success"])
        client.post("/admin/couples/legacylink/", {"action": "unlink_links", "_selected_action": [str(self.link.pk)]})
        self.link.refresh_from_db()
        self.assertIsNotNone(self.link.unlinked_at)


class PurgeTests(TestCase):
    def test_purge_never_deletes_a_linked_legacy_couple(self):
        couple, ann, _ = make_couple()
        linked, loose = make_legacy(), make_legacy("loose-secret")
        legacy.claim(ann, "Ann", "Ben", SECRET)
        old = timezone.now() - timedelta(days=60)
        CoupleSession.objects.update(last_active=old)
        call_command("purge_inactive_sessions", stdout=io.StringIO())
        self.assertTrue(CoupleSession.objects.filter(pk=linked.pk).exists())
        self.assertTrue(CustomQuestion.objects.filter(couple=linked).exists())
        self.assertFalse(CoupleSession.objects.filter(pk=loose.pk).exists())


class SpacePageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, self.ann, self.ben = make_couple()
        self.session = make_legacy()

    def claim(self, client, secret=SECRET):
        return client.post("/space/", {"action": "claim_legacy", "partner1_name": "Ann",
                                        "partner2_name": "Ben", "secret_word": secret}, follow=True)

    def test_page_offers_the_claim(self):
        self.assertContains(signed_in(self.ann).get("/space/"), 'value="claim_legacy"')

    def test_claim_from_the_page(self):
        page = self.claim(signed_in(self.ann))
        self.assertTrue(LegacyLink.objects.filter(couple=self.couple).exists())
        self.assertContains(page, "Ann &amp; Ben")
        self.assertContains(page, 'value="mark_ready"')

    def test_wrong_secret_shows_an_error(self):
        page = self.claim(signed_in(self.ann), "wrong-word")
        self.assertContains(page, "don&#x27;t match")
        self.assertFalse(LegacyLink.objects.exists())

    def test_claims_are_rate_limited(self):
        client = signed_in(self.ann)
        for _ in range(5):
            self.claim(client, "wrong-word")
        self.claim(client)  # Right secret, but over the limit.
        self.assertFalse(LegacyLink.objects.exists())

    def test_readiness_shows_names_and_the_date(self):
        legacy.claim(self.ann, "Ann", "Ben", SECRET)
        signed_in(self.ann).post("/space/", {"action": "mark_ready"})
        page = signed_in(self.ben).get("/space/")
        self.assertContains(page, "Ann is ready")
        self.assertNotContains(page, "ann@example.com")
        signed_in(self.ben).post("/space/", {"action": "mark_ready"})
        link = LegacyLink.objects.get()
        self.assertContains(signed_in(self.ann).get("/space/"), date_format(link.retire_at))


class LegacyNoticeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.session = make_legacy()

    def test_unclaimed_couples_are_told_how_to_move(self):
        page = Client().get("/modes/", {"secret": SECRET})
        self.assertContains(page, "/accounts/register/")

    def test_retiring_couples_see_the_date(self):
        couple, ann, ben = make_couple()
        link = legacy.claim(ann, "Ann", "Ben", SECRET)
        legacy.mark_ready(ann)
        legacy.mark_ready(ben)
        link.refresh_from_db()
        page = Client().get("/modes/", {"secret": SECRET})
        self.assertContains(page, "stops working")
        self.assertContains(page, date_format(link.retire_at))

    def test_unknown_secrets_get_no_notice(self):
        page = Client().get("/modes/", {"secret": "nobody-has-this"})
        self.assertNotContains(page, "stops working")
        self.assertNotContains(page, 'class="legacy-notice"')


@override_settings(ALLOWED_HOSTS=["me-nd-you.onrender.com"])
class LegacyConnectionTests(TransactionTestCase):
    serialized_rollback = True
    ORIGIN = b"https://me-nd-you.onrender.com"

    def test_open_legacy_connection_ends_once_retired(self):
        couple, ann, ben = make_couple()
        link = legacy.claim(ann, "Ann", "Ben", make_legacy().secret_word)
        legacy.mark_ready(ann)
        legacy.mark_ready(ben)

        async def scenario():
            app = importlib.reload(me_nd_you.asgi).application
            page = WebsocketCommunicator(app, f"/ws/game/{SECRET}/questions/", headers=[(b"origin", self.ORIGIN)])
            assert (await page.connect())[0]
            import asyncio
            await asyncio.get_running_loop().run_in_executor(None, past_deadline, link)
            await page.send_json_to({"type": "next", "userId": "u1"})
            return await page.receive_output(timeout=2)

        self.assertEqual(async_to_sync(scenario)()["type"], "websocket.close")
