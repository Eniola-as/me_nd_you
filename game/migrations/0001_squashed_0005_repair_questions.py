"""The game app's initial schema in one step, replacing 0001-0005.

Written by hand rather than with squashmigrations: the original 0003 turns
CoupleSession.id from an integer into a UUID, which PostgreSQL refuses
("cannot cast type bigint to uuid"), and Django's optimizer can't fold that
change into the CreateModel because RunPython steps sit in between. Here
the id is a UUID from the start.

Fresh databases (any backend) run only this migration. A database that
applied all of 0001-0005 treats it as applied; one that applied only some
of them keeps using the originals (Django's rule for replacing
migrations), so existing databases are never re-run or skipped. Keep the
originals until no database is part-way through them.

0004 (dedupe secrets) and 0005 (repair legacy question rows) change
nothing on a fresh database, so they have no step here.
"""

import json
import uuid
from pathlib import Path

import django.db.models.deletion
from django.core.management.color import no_style
from django.db import migrations, models

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "questions.json"

MODES = [
    ("questions", "Questions"),
    ("truth", "Truth or Dare"),
    ("challenge", "Challenge"),
    ("spicy", "Spicy Only"),
    ("mixed", "Mixed Mode"),
    ("would", "Would You Rather"),
]


def load_questions(apps, schema_editor):
    # Same as 0002: load the question bank with the historical model, then
    # reset PostgreSQL's id sequence past the explicit fixture ids.
    Question = apps.get_model("game", "Question")
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    Question.objects.bulk_create(
        Question(pk=row["pk"], text=row["fields"]["text"], mode=row["fields"]["mode"])
        for row in rows
    )
    for sql in schema_editor.connection.ops.sequence_reset_sql(no_style(), [Question]):
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    replaces = [
        ("game", "0001_initial"),
        ("game", "0002_load_questions"),
        ("game", "0003_couplesession_last_active_couplesession_session_key_and_more"),
        ("game", "0004_unique_secret_word"),
        ("game", "0005_repair_questions"),
    ]

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CoupleSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("partner1_name", models.CharField(max_length=100)),
                ("partner2_name", models.CharField(max_length=100)),
                ("secret_word", models.CharField(max_length=100, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_active", models.DateTimeField(auto_now=True)),
                ("session_key", models.CharField(blank=True, max_length=255, unique=True)),
            ],
            options={
                "unique_together": {("partner1_name", "partner2_name", "secret_word")},
            },
        ),
        migrations.CreateModel(
            name="Question",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("mode", models.CharField(choices=MODES, max_length=20)),
            ],
        ),
        migrations.CreateModel(
            name="CustomQuestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("mode", models.CharField(choices=MODES, max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("couple", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="game.couplesession")),
            ],
        ),
        migrations.CreateModel(
            name="PlayedQuestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("mode", models.CharField(max_length=20)),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                ("couple", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="game.couplesession")),
            ],
        ),
        migrations.RunPython(load_questions, migrations.RunPython.noop),
    ]
