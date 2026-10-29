"""Truth or Dare questions are split into truths and dares (owner-approved
rule). Only that mode has kinds; the stored text never changes."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase

from couples import services
from game.models import CustomQuestion, Question
from game.tests.test_new_dares import TEXTS as APPROVED_NEW_DARES
from game.truth_or_dare import DARE, TRUTH, classify

BEFORE = [("game", "0007_remove_secret_word_couples")]
AFTER = [("game", "0008_truth_or_dare_kinds")]


class ClassifyTests(TestCase):
    def test_an_explicit_prefix_wins(self):
        self.assertEqual(classify("Truth: Kiss me?"), TRUTH)
        self.assertEqual(classify("Dare: What's your secret?"), DARE)
        self.assertEqual(classify("dare - send a voice note."), DARE)

    def test_a_question_mark_makes_a_truth(self):
        self.assertEqual(classify("Have you ever been caught in the act? Tell us what happened."), TRUTH)

    def test_tell_describe_and_share_are_spoken_truths(self):
        for text in ["Tell me your favorite thing.", "Describe your dream date.", "Share a secret."]:
            self.assertEqual(classify(text), TRUTH, text)

    def test_other_prompts_are_dares(self):
        for text in ["Give me a lap dance for 30 seconds.", "Kiss me softly on the neck.", "Whisper something."]:
            self.assertEqual(classify(text), DARE, text)


class BankSplitTests(TestCase):
    # The split of the original bank. The owner-approved dares added later
    # (migration 0009) are dares by approval, not by this rule.

    def original(self):
        from game.tests.test_new_questions_import import TEXTS as IMPORTED  # Migration 0011.

        return Question.objects.filter(mode="truth").exclude(text__in=APPROVED_NEW_DARES).exclude(text__in=IMPORTED)

    def test_the_bank_has_381_truths_and_101_dares(self):
        truth_mode = self.original()
        self.assertEqual(truth_mode.count(), 482)
        self.assertEqual(truth_mode.filter(kind=TRUTH).count(), 381)
        self.assertEqual(truth_mode.filter(kind=DARE).count(), 101)

    def test_other_modes_have_no_kind(self):
        self.assertFalse(Question.objects.exclude(mode="truth").exclude(kind="").exists())

    def test_stored_text_keeps_its_prefix(self):
        self.assertTrue(Question.objects.filter(mode="truth", text__startswith="Dare:").exists())

    def test_every_kind_matches_the_rule(self):
        for question in self.original():
            self.assertEqual(question.kind, classify(question.text), question.pk)


class KindConstraintTests(TestCase):
    def setUp(self):
        self.space = services.create_couple(
            get_user_model().objects.create_user(email="ann@example.com", password="a-long-passphrase-1")
        )

    def test_truth_or_dare_questions_need_a_kind(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Question.objects.create(text="No kind?", mode="truth")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomQuestion.objects.create(space=self.space, text="No kind?", mode="truth")

    def test_other_modes_cannot_have_one(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Question.objects.create(text="Hmm?", mode="questions", kind=DARE)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomQuestion.objects.create(space=self.space, text="Hmm?", mode="spicy", kind=TRUTH)


class CustomQuestionKindApiTests(TestCase):
    def setUp(self):
        cache.clear()
        member = get_user_model().objects.create_user(email="ann@example.com", password="a-long-passphrase-1")
        services.create_couple(member)
        self.client = Client()
        self.client.force_login(member)

    def add(self, **body):
        return self.client.post("/api/space/custom-questions/", body, content_type="application/json")

    def test_an_explicit_kind_is_kept(self):
        self.assertEqual(self.add(text="What do you love?", mode="truth", kind="dare").status_code, 201)
        self.assertEqual(CustomQuestion.objects.get().kind, DARE)

    def test_without_a_kind_the_rule_decides(self):
        self.add(text="Hold my hand for a minute.", mode="truth")
        self.add(text="What made you smile?", mode="truth")
        self.assertEqual(dict(CustomQuestion.objects.values_list("text", "kind")),
                         {"Hold my hand for a minute.": DARE, "What made you smile?": TRUTH})

    def test_other_modes_ignore_a_kind(self):
        self.assertEqual(self.add(text="Plain?", mode="questions", kind="dare").status_code, 201)
        self.assertEqual(CustomQuestion.objects.get().kind, "")

    def test_an_unknown_kind_is_rejected(self):
        self.assertEqual(self.add(text="Odd?", mode="truth", kind="both").status_code, 400)
        self.assertFalse(CustomQuestion.objects.exists())


class SplitMigrationTests(TransactionTestCase):
    serialized_rollback = True  # Restore the question bank for later tests.

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_custom_questions_are_classified_and_unchanged(self):
        apps = self.migrate(BEFORE)
        space = apps.get_model("couples", "Couple").objects.create()
        Custom = apps.get_model("game", "CustomQuestion")
        dare = Custom.objects.create(space=space, text="Give me a hug.", mode="truth")
        truth = Custom.objects.create(space=space, text="Why me?", mode="truth")
        plain = Custom.objects.create(space=space, text="Give me a hug.", mode="questions")

        Custom = self.migrate(AFTER).get_model("game", "CustomQuestion")
        kinds = {q.pk: (q.kind, q.text) for q in Custom.objects.all()}
        self.assertEqual(kinds, {dare.pk: (DARE, "Give me a hug."), truth.pk: (TRUTH, "Why me?"),
                                 plain.pk: ("", "Give me a hug.")})
