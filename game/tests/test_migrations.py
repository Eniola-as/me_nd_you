"""Migration tests: roll back, build a scenario with historical models,
migrate forward (or back), and check exactly what changed."""

import json
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

PLAN = json.loads(
    (Path(settings.BASE_DIR) / "game" / "migrations" / "legacy" / "0005_question_repairs.json")
    .read_text(encoding="utf-8")
)
UPDATES = [e for e in PLAN if e["action"] == "update"]
DELETES = [e for e in PLAN if e["action"] == "delete"]
BEFORE_0004 = [("game", "0003_couplesession_last_active_couplesession_session_key_and_more")]
BEFORE_0005 = [("game", "0004_unique_secret_word")]
AFTER_0005 = [("game", "0005_repair_questions")]
ADMIN_PK = 100_000  # Above every legacy fixture id, like a row an admin adds.


class MigrationTestCase(TransactionTestCase):
    # Restore the question bank for the TestCase tests that run afterwards.
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes("game")
        self.migrate(latest)
        super().tearDown()


class RepairQuestionsMigrationTests(MigrationTestCase):
    def setUp(self):
        apps = self.migrate(BEFORE_0005)
        self.Question = apps.get_model("game", "Question")
        self.Question.objects.all().delete()

    def add(self, pk, text, mode):
        self.Question.objects.create(pk=pk, text=text, mode=mode)

    def add_legacy(self, entry):
        self.add(entry["pk"], entry["old_text"], entry["old_mode"])

    def rows_after_migrating(self):
        apps = self.migrate(AFTER_0005)
        Question = apps.get_model("game", "Question")
        return {q.pk: (q.text, q.mode) for q in Question.objects.all()}

    # Intended legacy repairs

    def test_repairs_garbled_text_of_an_untouched_legacy_row(self):
        entry = next(e for e in UPDATES if e["pk"] == 1)
        self.add_legacy(entry)
        self.assertEqual(self.rows_after_migrating()[1], (entry["new_text"], entry["new_mode"]))
        self.assertEqual(entry["new_text"], "What’s your favorite memory of us?")

    def test_remaps_invalid_mode_of_an_untouched_legacy_row(self):
        entry = next(e for e in UPDATES if e["old_mode"] == "icebreaker")
        self.add_legacy(entry)
        self.assertEqual(self.rows_after_migrating()[entry["pk"]][1], "questions")

    def test_deletes_same_mode_duplicate_when_its_keeper_is_legacy(self):
        entry = DELETES[0]
        self.add(entry["keeper"], entry["keeper_old_text"], entry["keeper_old_mode"])
        self.add_legacy(entry)
        rows = self.rows_after_migrating()
        self.assertNotIn(entry["pk"], rows)
        self.assertIn(entry["keeper"], rows)

    # Records whose legacy identity can't be established are left alone

    def test_keeps_and_repairs_duplicate_when_keeper_was_edited_by_an_admin(self):
        entry = DELETES[0]
        self.add(entry["keeper"], "An admin rewrote this question.", entry["keeper_old_mode"])
        self.add_legacy(entry)
        rows = self.rows_after_migrating()
        self.assertEqual(rows[entry["pk"]], (entry["new_text"], entry["new_mode"]))
        self.assertEqual(rows[entry["keeper"]][0], "An admin rewrote this question.")

    def test_keeps_duplicate_when_keeper_was_deleted(self):
        entry = DELETES[0]
        self.add_legacy(entry)
        self.assertIn(entry["pk"], self.rows_after_migrating())

    def test_ignores_admin_row_whose_text_matches_garbled_fixture_text(self):
        entry = next(e for e in UPDATES if e["pk"] == 1)
        self.add(ADMIN_PK, entry["old_text"], entry["old_mode"])
        self.assertEqual(
            self.rows_after_migrating()[ADMIN_PK], (entry["old_text"], entry["old_mode"])
        )

    def test_ignores_legacy_row_that_an_admin_edited(self):
        entry = next(e for e in UPDATES if e["pk"] == 1)
        self.add(1, entry["old_text"] + " (edited)", entry["old_mode"])
        self.assertEqual(self.rows_after_migrating()[1][0], entry["old_text"] + " (edited)")

    def test_never_changes_legitimate_accented_text(self):
        texts = [
            "Who sings like Björk?",
            "Quote an Encyclopædia entry.",
            "Côte d’Ivoire or Søren’s Denmark?",
            "Pick: Æsir or Vanir?",
        ]
        for offset, text in enumerate(texts):
            self.add(ADMIN_PK + offset, text, "questions")
        legacy = next(e for e in UPDATES if e["pk"] == 1)
        self.add(1, "Who sings like Björk?", legacy["old_mode"])  # edited legacy row
        rows = self.rows_after_migrating()
        for offset, text in enumerate(texts):
            self.assertEqual(rows[ADMIN_PK + offset][0], text)
        self.assertEqual(rows[1][0], "Who sings like Björk?")

    def test_keeps_admin_duplicates_including_across_modes(self):
        self.add(ADMIN_PK, "Same question?", "questions")
        self.add(ADMIN_PK + 1, "Same question?", "questions")
        self.add(ADMIN_PK + 2, "Same question?", "truth")
        self.assertEqual(len(self.rows_after_migrating()), 3)

    def test_keeps_legacy_duplicates_that_are_in_different_modes(self):
        fixture = json.loads(
            (Path(settings.BASE_DIR) / "game" / "fixtures" / "questions.json").read_text(
                encoding="utf-8"
            )
        )
        by_text = {}
        for row in fixture:
            by_text.setdefault(row["fields"]["text"].strip().casefold(), []).append(row)
        pair = next(rows for rows in by_text.values() if len({r["fields"]["mode"] for r in rows}) > 1)
        originals = {e["pk"]: e for e in PLAN}
        for row in pair[:2]:
            entry = originals.get(row["pk"])
            if entry:
                self.add_legacy(entry)
            else:
                self.add(row["pk"], row["fields"]["text"], row["fields"]["mode"])
        rows = self.rows_after_migrating()
        self.assertEqual(sum(pk in rows for pk in (pair[0]["pk"], pair[1]["pk"])), 2)

    # Whole-database behaviour

    def test_fresh_database_from_clean_fixture_is_unchanged(self):
        self.migrate(BEFORE_0004)  # Unapply, then rebuild as a fresh database would.
        apps = self.migrate(BEFORE_0005)
        Question = apps.get_model("game", "Question")
        Question.objects.all().delete()
        fixture = json.loads(
            (Path(settings.BASE_DIR) / "game" / "fixtures" / "questions.json").read_text(
                encoding="utf-8"
            )
        )
        Question.objects.bulk_create(
            Question(pk=r["pk"], text=r["fields"]["text"], mode=r["fields"]["mode"])
            for r in fixture
        )
        before = {q.pk: (q.text, q.mode) for q in Question.objects.all()}
        self.assertEqual(self.rows_after_migrating(), before)

    def reverse(self):
        apps = self.migrate(BEFORE_0005)
        Question = apps.get_model("game", "Question")
        return {q.pk: (q.text, q.mode) for q in Question.objects.all()}

    def test_reverse_restores_repaired_and_deleted_legacy_rows(self):
        update, delete = UPDATES[0], DELETES[0]
        keeper = next((e for e in PLAN if e["pk"] == delete["keeper"]), None)
        self.add_legacy(update)
        if keeper:
            self.add_legacy(keeper)
        else:
            self.add(delete["keeper"], delete["keeper_old_text"], delete["keeper_old_mode"])
        self.add_legacy(delete)
        # Only plan rows whose keeper is present can come back.
        restorable = {
            e["pk"]
            for e in DELETES
            if e["keeper"] in {update["pk"], delete["keeper"], delete["pk"]}
        }
        before = {q.pk: (q.text, q.mode) for q in self.Question.objects.all()}
        after_forward = self.rows_after_migrating()
        self.assertNotIn(delete["pk"], after_forward)
        restored = self.reverse()
        for pk, values in before.items():
            self.assertEqual(restored[pk], values)
        self.assertLessEqual(set(restored) - set(before), restorable)

    def test_reverse_never_recreates_a_duplicate_whose_keeper_is_missing(self):
        delete = DELETES[0]
        self.add(ADMIN_PK, "Unrelated admin question", "questions")
        self.rows_after_migrating()
        self.assertNotIn(delete["pk"], self.reverse())

    def test_reverse_leaves_rows_edited_after_the_repair(self):
        update = next(e for e in UPDATES if e["pk"] == 1)
        self.add_legacy(update)
        apps = self.migrate(AFTER_0005)
        apps.get_model("game", "Question").objects.filter(pk=1).update(text="Edited later")
        self.assertEqual(self.reverse()[1][0], "Edited later")


class UniqueSecretMigrationTests(MigrationTestCase):
    def setUp(self):
        apps = self.migrate(BEFORE_0004)
        self.Session = apps.get_model("game", "CoupleSession")

    def add(self, secret, p1, p2):
        return self.Session.objects.create(
            partner1_name=p1, partner2_name=p2, secret_word=secret, session_key=f"{p1}-{p2}"
        )

    def secrets_after_migrating(self):
        apps = self.migrate(BEFORE_0005)
        Session = apps.get_model("game", "CoupleSession")
        return {s.session_key: s.secret_word for s in Session.objects.all()}

    def test_oldest_session_keeps_a_duplicated_secret(self):
        self.add("sunflower", "Ann", "Ben")
        self.add("sunflower", "Cy", "Di")
        secrets = self.secrets_after_migrating()
        self.assertEqual(secrets["Ann-Ben"], "sunflower")
        self.assertEqual(secrets["Cy-Di"], "sunflower-2")

    def test_rename_skips_suffixes_already_in_use(self):
        self.add("sunflower", "Ann", "Ben")
        self.add("sunflower-2", "Ed", "Fy")
        self.add("sunflower", "Cy", "Di")
        self.assertEqual(self.secrets_after_migrating()["Cy-Di"], "sunflower-3")

    def test_renamed_max_length_secret_still_fits_the_column(self):
        long_secret = "s" * 100
        self.add(long_secret, "Ann", "Ben")
        self.add(long_secret, "Cy", "Di")
        secrets = self.secrets_after_migrating()
        self.assertEqual(secrets["Ann-Ben"], long_secret)
        self.assertLessEqual(len(secrets["Cy-Di"]), 100)
        self.assertNotEqual(secrets["Cy-Di"], long_secret)
