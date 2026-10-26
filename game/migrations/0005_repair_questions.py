"""Repair question rows loaded from the original (pre-cleanup) fixture.

The repairs are a precomputed list (legacy/0005_question_repairs.json) built
from the original fixture, not a text transformation applied at runtime. A
row is only touched when its id, text and mode still exactly match the
original fixture record, which proves it is untouched legacy data: ids are
never reused (AUTOINCREMENT), so admin-added rows can't match, and rows an
admin edited no longer match. Everything else is left exactly as it is.

Running it again is a no-op: repaired rows no longer match their old values.
Reversing it is close to exact but not perfect; see restore_questions.
"""

import json
from pathlib import Path

from django.db import migrations

PLAN_FILE = Path(__file__).resolve().parent / "legacy" / "0005_question_repairs.json"


def load_plan():
    return json.loads(PLAN_FILE.read_text(encoding="utf-8"))


def matches(row, text, mode):
    return row is not None and row.text == text and row.mode == mode


def repair_questions(apps, schema_editor):
    Question = apps.get_model("game", "Question")
    plan = load_plan()
    ids = {e["pk"] for e in plan} | {e["keeper"] for e in plan if "keeper" in e}
    rows = Question.objects.in_bulk(list(ids))

    for entry in plan:
        row = rows.get(entry["pk"])
        if not matches(row, entry["old_text"], entry["old_mode"]):
            continue  # Not provably untouched legacy data: leave it alone.
        if entry["action"] == "delete":
            # A same-mode duplicate is only removed if the copy it defers to
            # is itself verified legacy data (original or already repaired).
            keeper = rows.get(entry["keeper"])
            if matches(keeper, entry["keeper_old_text"], entry["keeper_old_mode"]) or matches(
                keeper, entry["keeper_new_text"], entry["keeper_new_mode"]
            ):
                row.delete()
                continue
        row.text, row.mode = entry["new_text"], entry["new_mode"]
        row.save(update_fields=["text", "mode"])


def restore_questions(apps, schema_editor):
    """Undo repair_questions. Repaired rows are restored only if still
    unedited. A deleted duplicate is recreated only while its keeper still
    exists with matching text; nothing records which duplicates the forward
    run removed, so one that was already missing beforehand would also come
    back, but only ever as an identical copy of a question that is present."""
    Question = apps.get_model("game", "Question")
    plan = load_plan()
    ids = {e["pk"] for e in plan} | {e["keeper"] for e in plan if "keeper" in e}
    rows = Question.objects.in_bulk(list(ids))
    for entry in plan:
        row = rows.get(entry["pk"])
        if row is None and entry["action"] == "delete":
            keeper = rows.get(entry["keeper"])
            if matches(keeper, entry["keeper_new_text"], entry["keeper_new_mode"]) or matches(
                keeper, entry["keeper_old_text"], entry["keeper_old_mode"]
            ):
                Question.objects.create(
                    pk=entry["pk"], text=entry["old_text"], mode=entry["old_mode"]
                )
        elif matches(row, entry["new_text"], entry["new_mode"]):
            row.text, row.mode = entry["old_text"], entry["old_mode"]
            row.save(update_fields=["text", "mode"])


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0004_unique_secret_word"),
    ]

    operations = [
        migrations.RunPython(repair_questions, restore_questions),
    ]
