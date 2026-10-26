import json
from pathlib import Path

from django.core.management.color import no_style
from django.db import migrations

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "questions.json"


def load_questions(apps, schema_editor):
    # Use the historical model so later model changes can't break this step,
    # and let any error fail the migration instead of leaving an empty bank.
    Question = apps.get_model("game", "Question")
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    Question.objects.bulk_create(
        Question(pk=row["pk"], text=row["fields"]["text"], mode=row["fields"]["mode"])
        for row in rows
    )
    # Explicit ids don't advance PostgreSQL's id sequence (loaddata used to
    # reset it), so do it here. SQLite needs no reset and returns no SQL.
    connection = schema_editor.connection
    for sql in connection.ops.sequence_reset_sql(no_style(), [Question]):
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(load_questions, migrations.RunPython.noop),
    ]
