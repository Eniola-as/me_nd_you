"""The add-a-prompt form matches the current mode (owner, 2026-10-29), and
the backend enforces it rather than trusting the page:

- Truth or Dare: a Truth/Dare choice; the chosen kind is saved.
- Other single modes: no choice; the prompt is saved to the current mode.
- Mixed Mode: a category selector of the real categories (never "Mixed");
  choosing Truth or Dare also shows the Truth/Dare choice."""

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from couples import services
from game.models import CustomQuestion
from play import modes

ADD = "/api/space/custom-questions/"
CATEGORIES = ["questions", "truth", "challenge", "spicy", "would"]


class PromptFormTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.ann = get_user_model().objects.create_user(email="ann@example.com", password="a-long-passphrase-1")
        services.create_couple(self.ann)
        self.client = Client()
        self.client.force_login(self.ann)

    def play(self, mode):
        """Make `mode` the couple's mode and return its play page."""
        with mock.patch("play.modes.notify"), self.captureOnCommitCallbacks(execute=True):
            modes.start(self.ann, mode)
        return self.client.get(f"/play/?mode={mode}").content.decode()

    def add(self, **body):
        return self.client.post(ADD, body, content_type="application/json")

    @staticmethod
    def shown(html, element_id):
        tag = re.search(rf'<[^>]*id="{element_id}"[^>]*>', html).group(0)
        return " hidden" not in tag


class FormControlTests(PromptFormTestCase):
    def test_truth_or_dare_shows_the_truth_dare_choice_only(self):
        html = self.play("truth")
        self.assertTrue(self.shown(html, "new-kind-choice"))
        self.assertFalse(self.shown(html, "new-category-choice"))

    def test_other_single_modes_show_neither(self):
        for mode in ["questions", "challenge", "spicy", "would"]:
            with self.subTest(mode):
                # A couple of its own for each mode (a couple has one mode).
                self.ann = get_user_model().objects.create_user(email=f"{mode}@example.com",
                                                                password="a-long-passphrase-1")
                services.create_couple(self.ann)
                self.client = Client()
                self.client.force_login(self.ann)
                html = self.play(mode)
                self.assertFalse(self.shown(html, "new-kind-choice"))
                self.assertFalse(self.shown(html, "new-category-choice"))

    def test_mixed_offers_the_real_categories_not_mixed(self):
        html = self.play("mixed")
        self.assertTrue(self.shown(html, "new-category-choice"))
        self.assertFalse(self.shown(html, "new-kind-choice"))  # Until Truth or Dare is chosen.
        options = re.findall(r'<option value="([^"]+)"', html[html.index('id="new-category"'):])
        self.assertEqual(options[:5], CATEGORIES)


class SavedPromptTests(PromptFormTestCase):
    def test_truth_or_dare_saves_the_chosen_kind(self):
        self.play("truth")
        for kind in ["truth", "dare"]:
            self.assertEqual(self.add(text=f"A {kind}?", mode="truth", kind=kind).status_code, 201)
        self.assertEqual(set(CustomQuestion.objects.values_list("mode", "kind")), {("truth", "truth"), ("truth", "dare")})

    def test_other_modes_save_to_the_current_mode_without_a_kind(self):
        self.play("spicy")
        self.assertEqual(self.add(text="Ours?", mode="spicy", kind="dare").status_code, 201)
        self.assertEqual(list(CustomQuestion.objects.values_list("mode", "kind")), [("spicy", "")])

    def test_a_prompt_for_another_mode_than_the_couples_is_refused(self):
        self.play("spicy")
        response = self.add(text="Sneaky?", mode="questions")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CustomQuestion.objects.exists())

    def test_mixed_saves_the_chosen_category_and_kind(self):
        self.play("mixed")
        self.assertEqual(self.add(text="Dare me.", mode="truth", kind="dare").status_code, 201)
        self.assertEqual(self.add(text="Climb something.", mode="challenge").status_code, 201)
        self.assertEqual(set(CustomQuestion.objects.values_list("mode", "kind")),
                         {("truth", "dare"), ("challenge", "")})

    def test_mixed_itself_is_never_a_saved_category(self):
        self.play("mixed")
        self.assertEqual(self.add(text="Which?", mode="mixed").status_code, 400)
        self.assertFalse(CustomQuestion.objects.exists())

    def test_a_prompt_added_in_mixed_joins_the_mixed_deck_too(self):
        from play.cards import DatabaseCards

        couple = services.active_couple(self.ann)
        self.play("mixed")
        self.add(text="Ours to share?", mode="questions")
        self.assertIn("Ours to share?", [c["text"] for c in DatabaseCards(couple, "mixed").all()])
