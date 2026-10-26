import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from game.models import Question

ROOT = Path(settings.BASE_DIR)
FIXTURE = ROOT / "game" / "fixtures" / "questions.json"
PLAN = ROOT / "game" / "migrations" / "legacy" / "0005_question_repairs.json"
# Characters produced when Windows-1252 punctuation is misread as code page 437.
MOJIBAKE = "ÆæΘùûôö"
# What that mojibake decodes to: ’ ‘ “ ” – — é.
DECODED_PUNCTUATION = set("’‘“”–—é")
VALID_MODES = {value for value, _ in Question.MODES}
LEGACY_FIXTURE_SIZE = 2059  # Records in the original questions.json.


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_rows():
    return [row["fields"] for row in load(FIXTURE)]


class QuestionFixtureTests(SimpleTestCase):
    def test_fixture_has_no_mojibake(self):
        bad = [r["text"] for r in fixture_rows() if any(c in r["text"] for c in MOJIBAKE)]
        self.assertEqual(bad, [])

    def test_fixture_uses_only_valid_modes(self):
        modes = {r["mode"] for r in fixture_rows()}
        self.assertLessEqual(modes, VALID_MODES)

    def test_fixture_has_no_duplicates_within_a_mode(self):
        keys = [(r["text"].strip().casefold(), r["mode"]) for r in fixture_rows()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_fixture_keeps_questions_shared_across_modes(self):
        texts = [r["text"].strip().casefold() for r in fixture_rows()]
        self.assertGreater(len(texts), len(set(texts)))


class RepairPlanTests(SimpleTestCase):
    """The 0005 plan is data, so check it is internally consistent."""

    def setUp(self):
        self.plan = load(PLAN)
        self.fixture = {row["pk"]: row["fields"] for row in load(FIXTURE)}

    def test_plan_only_targets_legacy_fixture_ids(self):
        self.assertTrue(all(1 <= e["pk"] <= LEGACY_FIXTURE_SIZE for e in self.plan))

    def test_text_repairs_only_introduce_the_expected_punctuation(self):
        for entry in self.plan:
            added = {c for c in entry["new_text"] if ord(c) > 127} - set(entry["old_text"])
            with self.subTest(pk=entry["pk"]):
                self.assertLessEqual(added, DECODED_PUNCTUATION)
                self.assertFalse(set(MOJIBAKE) & set(entry["new_text"]))

    def test_repairs_match_the_clean_fixture(self):
        for entry in (e for e in self.plan if e["action"] == "update"):
            with self.subTest(pk=entry["pk"]):
                fixed = self.fixture[entry["pk"]]
                self.assertEqual((fixed["text"], fixed["mode"]), (entry["new_text"], entry["new_mode"]))

    def test_deletions_are_same_mode_duplicates_of_a_kept_question(self):
        for entry in (e for e in self.plan if e["action"] == "delete"):
            with self.subTest(pk=entry["pk"]):
                self.assertNotIn(entry["pk"], self.fixture)
                keeper = self.fixture[entry["keeper"]]
                self.assertEqual(keeper["mode"], entry["new_mode"])
                self.assertEqual(
                    keeper["text"].strip().casefold(), entry["new_text"].strip().casefold()
                )


class QuestionMigrationTests(TestCase):
    def test_fresh_database_contains_exactly_the_fixture(self):
        self.assertEqual(Question.objects.count(), len(fixture_rows()))

    def test_new_questions_get_ids_after_the_fixture(self):
        # 0002 inserts explicit ids; PostgreSQL's id sequence must be reset
        # afterwards or the next insert collides with id 1.
        highest_fixture_id = max(row["pk"] for row in load(FIXTURE))
        question = Question.objects.create(text="Added by an admin", mode="questions")
        self.assertGreater(question.pk, highest_fixture_id)
