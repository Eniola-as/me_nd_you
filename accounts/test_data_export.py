"""Download my data: a JSON file with the account, consents, the couple's
custom questions (yours marked where known), your own chat messages
(decrypted) and your own reactions. Needs the password; 3 per hour per
account; also covers a space that closed within the last 30 days."""

import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from accounts.consents import CONSENT_KINDS
from chat import services as chat
from chat.tests import make_couple, with_chat_key
from couples import services as couples
from couples.models import Couple
from game.models import CustomQuestion

PASSWORD = "a-long-passphrase-1"
URL = "/accounts/profile/download/"


@with_chat_key
class DataExportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.couple, (self.ann, self.ben) = make_couple("ann@example.com", "ben@example.com")
        self.client.force_login(self.ann)

    def download(self, password=PASSWORD, client=None):
        return (client or self.client).post(URL, {"password": password})

    def data(self, response=None):
        response = response or self.download()
        self.assertEqual(response.status_code, 200, response.content[:300])
        return json.loads(b"".join(response.streaming_content) if response.streaming else response.content)

    def say(self, user, text):
        return chat.send(user, self.couple.id, text, str(uuid.uuid4()))

    def test_the_profile_offers_the_download_behind_a_password(self):
        html = self.client.get("/accounts/profile/").content.decode()
        self.assertIn(f'action="{URL}"', html)
        self.assertIn('type="password"', html)
        self.assertIn("Download my data", html)

    def test_it_is_a_private_json_attachment(self):
        response = self.download()
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertRegex(response["Content-Disposition"], r'^attachment; filename="me-and-you-data-\d{4}-\d{2}-\d{2}\.json"$')
        self.assertIn("no-store", response["Cache-Control"])

    def test_only_post_and_only_signed_in(self):
        self.assertEqual(self.client.get(URL).status_code, 405)
        response = Client().post(URL, {"password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_a_wrong_password_gives_no_file(self):
        response = self.download("not-my-password")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("attachment", response.get("Content-Disposition", ""))
        self.assertContains(response, "That password isn&#x27;t right.")
        self.assertNotContains(response, "ann@example.com")

    def test_the_account_and_consents_are_included(self):
        data = self.data()
        self.assertEqual(data["account"]["email"], "ann@example.com")
        self.assertEqual(data["account"]["display_name"], "Ann")
        self.assertIn("joined_at", data["account"])
        self.assertEqual(sorted(c["kind"] for c in data["consents"]), sorted(CONSENT_KINDS))
        self.assertTrue(all(c["given_at"] and c["policy_version"] for c in data["consents"]))
        self.assertNotIn("password", json.dumps(data["account"]))

    def test_custom_questions_are_marked_yours_where_known(self):
        CustomQuestion.objects.create(space=self.couple, text="Mine?", mode="questions", author=self.ann)
        CustomQuestion.objects.create(space=self.couple, text="His?", mode="questions", author=self.ben)
        CustomQuestion.objects.create(space=self.couple, text="Before authors?", mode="questions")
        questions = {q["text"]: q["yours"] for q in self.data()["couple_spaces"][0]["custom_questions"]}
        self.assertEqual(questions, {"Mine?": True, "His?": False, "Before authors?": None})

    def test_only_your_own_messages_and_reactions_decrypted(self):
        mine = self.say(self.ann, "Ann's secret")
        theirs = self.say(self.ben, "Ben's secret")
        chat.react(self.ann, self.couple.id, theirs.id, "❤️")
        chat.react(self.ben, self.couple.id, mine.id, "😂")
        raw = self.download().content.decode()
        data = json.loads(raw)
        space = data["couple_spaces"][0]
        self.assertEqual([m["text"] for m in space["chat_messages"]], ["Ann's secret"])
        self.assertEqual([r["emoji"] for r in space["chat_reactions"]], ["❤️"])
        for leaked in ["Ben's secret", "ben@example.com", "😂", mine.body]:
            self.assertNotIn(leaked, raw)

    def test_a_space_closed_within_30_days_is_included_and_older_ones_are_not(self):
        self.say(self.ann, "Before closing")
        with self.captureOnCommitCallbacks(execute=True):
            couples.close_couple(self.ben)
        space = self.data()["couple_spaces"][0]
        self.assertEqual(space["status"], "closed")
        self.assertEqual([m["text"] for m in space["chat_messages"]], ["Before closing"])
        self.assertIn("deleted_after", space)
        Couple.objects.filter(pk=self.couple.pk).update(closed_at=timezone.now() - timedelta(days=31))
        self.assertEqual(self.data()["couple_spaces"], [])

    def test_three_downloads_an_hour_per_account(self):
        for _ in range(2):
            self.data()
        self.download("wrong")  # Failed attempts count too.
        self.assertEqual(self.download().status_code, 429)
        # Per account, not per address: another browser doesn't reset it...
        other = Client(REMOTE_ADDR="10.0.0.9")
        other.force_login(self.ann)
        self.assertEqual(self.download(client=other).status_code, 429)
        # ...and another account isn't affected.
        ben = Client()
        ben.force_login(self.ben)
        self.data(self.download(client=ben))


class CustomQuestionAuthorTests(TestCase):
    def test_new_custom_questions_record_who_wrote_them(self):
        cache.clear()
        ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
        couples.create_couple(ann)
        client = Client()
        client.force_login(ann)
        response = client.post("/api/space/custom-questions/", {"mode": "questions", "text": "Who wrote me?"},
                               content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(CustomQuestion.objects.get().author, ann)

    def test_the_admin_list_still_hides_the_author_and_text(self):
        # The admin shows counts and ids only (game/tests/test_admin_privacy.py).
        from game.admin import CustomQuestionAdmin

        self.assertNotIn("author", CustomQuestionAdmin.list_display)
