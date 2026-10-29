"""The owner's new questions (game/data/me_and_you_new_questions.tsv, game
migration 0011) join the bank as normal questions in their modes. Rows 397
and 398 are left out as near-duplicates (owner, 2026-10-29). Existing
questions are never edited, and undoing it removes only these rows. The file
stays in the repository so the comfort migration can mark them Sweet later."""

import csv
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from game.models import Question

DATA = Path(settings.BASE_DIR) / "game" / "data" / "me_and_you_new_questions.tsv"
with DATA.open(encoding="utf-8", newline="") as _file:
    ROWS = list(csv.DictReader(_file, delimiter="\t"))
DROPPED = {"397", "398"}
IMPORTED = [row for row in ROWS if row["number"] not in DROPPED]
TEXTS = [row["text"] for row in IMPORTED]
BEFORE = [("game", "0010_customquestion_author")]
AFTER = [("game", "0011_new_questions")]


class FileTests(TestCase):
    def test_the_file_is_the_owners_1040_rows(self):
        self.assertEqual(len(ROWS), 1040)
        self.assertEqual(Counter(r["mode"] for r in ROWS),
                         {"questions": 340, "truth": 200, "would": 250, "challenge": 150, "mixed": 100})

    def test_1038_are_imported_without_the_two_near_duplicates(self):
        self.assertEqual(len(IMPORTED), 1038)
        dropped = {r["number"]: r["text"] for r in ROWS if r["number"] in DROPPED}
        self.assertEqual(dropped, {"397": "What's your most irrational pet peeve?",
                                   "398": "What's something you're secretly very competitive about?"})


class BankTests(TestCase):
    def test_each_imported_question_is_in_its_mode_once(self):
        for row in IMPORTED:
            self.assertEqual(list(Question.objects.filter(text=row["text"]).values_list("mode", "kind")),
                             [(row["mode"], row["kind"])], row["number"])

    def test_the_dropped_rows_are_not_in_the_bank(self):
        for row in ROWS:
            if row["number"] in DROPPED:
                self.assertFalse(Question.objects.filter(text=row["text"]).exists())

    def test_the_bank_grew_by_exactly_the_imported_rows(self):
        self.assertEqual(Question.objects.count(), 2067 + 1038)
        new = Question.objects.filter(text__in=TEXTS)
        self.assertEqual(Counter(new.values_list("mode", flat=True)),
                         {"questions": 340, "truth": 198, "would": 250, "challenge": 150, "mixed": 100})


class ImportMigrationTests(TransactionTestCase):
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
        return {q.pk: (q.text, q.mode, q.kind) for q in apps.get_model("game", "Question").objects.all()}

    def test_existing_questions_are_untouched_both_ways(self):
        before = self.rows(self.migrate(BEFORE))
        after = self.rows(self.migrate(AFTER))
        self.assertEqual({pk: row for pk, row in after.items() if pk in before}, before)
        added = sorted(row for pk, row in after.items() if pk not in before)
        self.assertEqual(added, sorted((r["text"], r["mode"], r["kind"]) for r in IMPORTED))
        # Undoing it removes exactly these rows again.
        self.assertEqual(self.rows(self.migrate(BEFORE)), before)
