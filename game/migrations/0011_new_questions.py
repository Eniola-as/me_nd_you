"""Add the owner's new questions (game/data/me_and_you_new_questions.tsv) as
normal questions in their modes, with Truth or Dare kinds from the file.

Rows 397 and 398 are left out as near-duplicates (owner, 2026-10-29). The
tone and level columns are for reference only and not stored; the file stays
so the comfort (Sweet/Spicy) migration can mark these Sweet later. No
existing question is edited. Reversing deletes only these rows.
"""

import csv
from pathlib import Path

from django.db import migrations

DATA = Path(__file__).resolve().parent.parent / "data" / "me_and_you_new_questions.tsv"
DROPPED = {"397", "398"}


def rows():
    with DATA.open(encoding="utf-8", newline="") as file:
        return [row for row in csv.DictReader(file, delimiter="\t") if row["number"] not in DROPPED]


def add_questions(apps, schema_editor):
    Question = apps.get_model("game", "Question")
    Question.objects.bulk_create(
        [Question(text=row["text"], mode=row["mode"], kind=row["kind"]) for row in rows()]
    )


def remove_questions(apps, schema_editor):
    Question = apps.get_model("game", "Question")
    for row in rows():
        Question.objects.filter(text=row["text"], mode=row["mode"], kind=row["kind"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0010_customquestion_author"),
    ]

    operations = [
        migrations.RunPython(add_questions, remove_questions),
    ]
