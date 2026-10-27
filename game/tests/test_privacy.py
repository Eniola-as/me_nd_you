import contextlib
import io

from django.contrib.auth import get_user_model
from django.test import TestCase

from couples import services
from game.models import CustomQuestion

from .utils import load_settings


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
        member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        services.create_couple(member)
        self.client.force_login(member)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertLogs("game.views", "WARNING"):
            self.client.post("/api/space/custom-questions/", {}, content_type="application/json")
        self.assertEqual(stdout.getvalue(), "")


class AdminPrivacyTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
        couple = services.create_couple(self.member)
        self.question = CustomQuestion.objects.create(space=couple, text="Ours?", mode="questions")
        admin = get_user_model().objects.create_superuser(email="a@example.com", password="pw-for-tests")
        self.client.force_login(admin)

    def test_custom_question_label_names_no_member(self):
        self.assertNotIn(self.member.email, str(self.question))

    def test_custom_question_admin_pages_render(self):
        for url in ["/admin/game/customquestion/", f"/admin/game/customquestion/{self.question.pk}/change/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
