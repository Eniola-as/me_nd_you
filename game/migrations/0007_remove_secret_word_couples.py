"""Remove secret-word couples (there were no real users of them).

Data effect: on a database that has secret-word couples, their custom
questions, play history and the couples themselves are permanently deleted.
Couple-space questions and the question bank are untouched. The schema can
be migrated back, but deleted rows are not restored.
"""

import django.db.models.deletion
from django.db import migrations, models


def delete_secret_word_questions(apps, schema_editor):
    # They have no space, and space is about to become required.
    apps.get_model("game", "CustomQuestion").objects.filter(space__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("couples", "0004_remove_legacy_link"),
        ("game", "0006_custom_question_space"),
    ]

    operations = [
        migrations.RunPython(delete_secret_word_questions, migrations.RunPython.noop),
        # Before the field it checks, which some databases drop along with it.
        migrations.RemoveConstraint(
            model_name="customquestion",
            name="game_customquestion_exactly_one_owner",
        ),
        migrations.RemoveField(
            model_name="customquestion",
            name="couple",
        ),
        migrations.AlterField(
            model_name="customquestion",
            name="space",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="custom_questions",
                to="couples.couple",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="couplesession",
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name="playedquestion",
            name="couple",
        ),
        migrations.DeleteModel(
            name="PlayedQuestion",
        ),
        migrations.DeleteModel(
            name="CoupleSession",
        ),
    ]
