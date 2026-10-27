"""The 150 owner-approved dares (game migration 0009) join Truth or Dare as
dares. Existing questions are never edited."""

import json
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from game.models import Question

DATA = Path(settings.BASE_DIR) / "game" / "migrations" / "data" / "0009_new_dares.json"
NEW_DARES = json.loads(DATA.read_text(encoding="utf-8"))
TEXTS = [row["text"] for row in NEW_DARES]
BEFORE = [("game", "0008_truth_or_dare_kinds")]
AFTER = [("game", "0009_new_dares")]


class ApprovedListTests(TestCase):
    def test_the_list_matches_the_agreed_mix(self):
        self.assertEqual(len(NEW_DARES), 150)
        self.assertEqual(Counter(r["intensity"] for r in NEW_DARES), {"playful": 20, "flirty": 50, "spicy": 80})
        self.assertEqual(Counter(r["where"] for r in NEW_DARES), {"remote": 75, "in person": 75})

    def test_no_dare_repeats_another(self):
        self.assertEqual(len({t.strip().casefold() for t in TEXTS}), 150)


class BankTests(TestCase):
    def test_each_new_dare_is_in_truth_or_dare_once(self):
        for text in TEXTS:
            self.assertEqual(list(Question.objects.filter(text=text).values_list("mode", "kind")),
                             [("truth", "dare")], text)

    def test_truth_or_dare_now_has_251_dares_and_the_same_381_truths(self):
        truth_mode = Question.objects.filter(mode="truth")
        self.assertEqual(truth_mode.filter(kind="dare").count(), 251)
        self.assertEqual(truth_mode.filter(kind="truth").count(), 381)
        self.assertEqual(Question.objects.count(), 1917 + 150)


class NewDaresMigrationTests(TransactionTestCase):
    serialized_rollback = True  # Restore the question bank for later tests.

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    @staticmethod
    def rows(apps):
        return {q.pk: (q.text, q.mode, q.kind)
                for q in apps.get_model("game", "Question").objects.all()}

    def test_existing_questions_are_untouched_both_ways(self):
        before = self.rows(self.migrate(BEFORE))
        after = self.rows(self.migrate(AFTER))
        self.assertEqual({pk: row for pk, row in after.items() if pk in before}, before)
        added = sorted(row for pk, row in after.items() if pk not in before)
        self.assertEqual(added, sorted((text, "truth", "dare") for text in TEXTS))
        # Undoing it removes exactly the 150 again.
        self.assertEqual(self.rows(self.migrate(BEFORE)), before)
