"""Add 150 owner-approved dares to Truth or Dare (mode "truth", kind "dare").

The texts are in data/0009_new_dares.json, exactly as approved; the
intensity and remote/in-person tags there are for reference only and are not
stored. No existing question is edited. Reversing deletes these 150 again.
"""

import json
from pathlib import Path

from django.db import migrations

DATA = Path(__file__).resolve().parent / "data" / "0009_new_dares.json"


def texts():
    return [row["text"] for row in json.loads(DATA.read_text(encoding="utf-8"))]


def add_dares(apps, schema_editor):
    Question = apps.get_model("game", "Question")
    Question.objects.bulk_create([Question(text=text, mode="truth", kind="dare") for text in texts()])


def remove_dares(apps, schema_editor):
    apps.get_model("game", "Question").objects.filter(mode="truth", kind="dare", text__in=texts()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0008_truth_or_dare_kinds"),
    ]

    operations = [
        migrations.RunPython(add_dares, remove_dares),
    ]
