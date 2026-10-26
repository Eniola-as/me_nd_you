import contextlib
import io

from django.contrib.auth.models import User
from django.test import TestCase

from game.models import CoupleSession, CustomQuestion

from .utils import load_settings

SECRET = "our-private-word"


class ApiSurfaceTests(TestCase):
    def test_production_serves_json_only(self):
        # Settings are computed at import, and the local .env enables DEBUG,
        # so check the production configuration in a fresh process.
        values = load_settings({"DEBUG": "False"}, ["REST_FRAMEWORK"])
        self.assertEqual(
            values["REST_FRAMEWORK"]["DEFAULT_RENDERER_CLASSES"],
            ["rest_framework.renderers.JSONRenderer"],
        )

    def test_invalid_custom_question_is_logged_not_printed(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertLogs("game.views", "WARNING"):
            self.client.post("/api/add-custom-question/", {}, content_type="application/json")
        self.assertEqual(stdout.getvalue(), "")


class AdminPrivacyTests(TestCase):
    def setUp(self):
        self.couple = CoupleSession.objects.create(
            partner1_name="Ann", partner2_name="Ben", secret_word=SECRET
        )
        self.question = CustomQuestion.objects.create(
            couple=self.couple, text="Ours?", mode="questions"
        )
        admin = User.objects.create_superuser("admin", "a@example.com", "pw-for-tests")
        self.client.force_login(admin)

    def test_custom_question_label_hides_the_secret(self):
        self.assertNotIn(SECRET, str(self.question))

    def test_admin_pages_do_not_show_the_secret(self):
        pages = [
            "/admin/game/couplesession/",
            f"/admin/game/couplesession/{self.couple.pk}/change/",
            "/admin/game/customquestion/",
            f"/admin/game/customquestion/{self.question.pk}/change/",
        ]
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(SECRET, response.content.decode())
