"""The admin pages never show the text of a couple's custom questions
(they can be intimate). Admins see ids, counts, mode and kind only."""

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase

from couples import services
from game.models import CustomQuestion

PASSWORD = "a-long-passphrase-1"
SECRET = "zq-private-marker Describe our secret night"


class AdminNeverShowsCustomQuestionTextTests(TestCase):
    def setUp(self):
        User = get_user_model()
        ann = User.objects.create_user(email="ann@example.com", password=PASSWORD)
        self.couple = services.create_couple(ann)
        self.question = CustomQuestion.objects.create(space=self.couple, text=SECRET, mode="spicy")
        admin = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        self.client.force_login(admin)

    def assert_hidden(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        self.assertNotIn("zq-private-marker", response.content.decode(), url)
        return response

    def test_the_custom_question_list_shows_ids_mode_and_kind_only(self):
        page = self.assert_hidden("/admin/game/customquestion/")
        self.assertContains(page, f"Custom question #{self.question.pk}")
        self.assertContains(page, "spicy")

    def test_the_detail_and_history_pages_hide_the_text(self):
        self.assert_hidden(f"/admin/game/customquestion/{self.question.pk}/change/")
        self.assert_hidden(f"/admin/game/customquestion/{self.question.pk}/history/")

    def test_delete_confirmations_hide_the_text(self):
        self.assert_hidden(f"/admin/game/customquestion/{self.question.pk}/delete/")
        self.assert_hidden(f"/admin/couples/couple/{self.couple.pk}/delete/")

    def test_couple_pages_show_a_count_not_the_text(self):
        page = self.assert_hidden("/admin/couples/couple/")
        self.assertContains(page, "<td class=\"field-custom_question_count\">1</td>", html=False)
        self.assert_hidden(f"/admin/couples/couple/{self.couple.pk}/change/")

    def test_searching_cannot_be_used_to_probe_the_text(self):
        # No search box, and a query naming a word that is in the text gives
        # the same result as one that isn't: no signal about the text.
        self.assertNotContains(self.assert_hidden("/admin/game/customquestion/"), 'id="searchbar"')
        present = self.client.get("/admin/game/customquestion/?q=secret").context["cl"].result_count
        absent = self.client.get("/admin/game/customquestion/?q=xylophone").context["cl"].result_count
        self.assertEqual((present, absent), (1, 1))

    def test_admins_cannot_add_or_edit_question_text(self):
        self.assertEqual(self.client.get("/admin/game/customquestion/add/").status_code, 403)
        self.client.post(f"/admin/game/customquestion/{self.question.pk}/change/",
                         {"text": "changed by an admin", "mode": "spicy", "kind": ""})
        self.assertEqual(CustomQuestion.objects.get().text, SECRET)

    def test_the_admin_history_log_never_records_the_text(self):
        self.client.post(f"/admin/game/customquestion/{self.question.pk}/delete/", {"post": "yes"})
        self.assertFalse(CustomQuestion.objects.exists())
        self.assertTrue(LogEntry.objects.exists())
        self.assertFalse(LogEntry.objects.filter(object_repr__contains="zq-private-marker").exists())

    def test_the_label_used_everywhere_has_no_text(self):
        self.assertEqual(str(self.question), f"Custom question #{self.question.pk} (spicy)")
