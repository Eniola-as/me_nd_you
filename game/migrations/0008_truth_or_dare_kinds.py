"""Split Truth or Dare questions into truths and dares (owner-approved rule:
381 truths and 101 dares in the bank). Only the new `kind` field is set;
no question's text changes. Custom questions in that mode get the same rule.
"""

import re

from django.db import migrations, models

# A frozen copy of game.truth_or_dare.classify, so later edits there can't
# change what this migration did.
_PREFIX = re.compile(r"^\s*(truth|dare)\s*[:\-]\s*", re.IGNORECASE)
_SPOKEN = re.compile(r"^(tell|describe|share)\b", re.IGNORECASE)


def classify(text):
    text = text.strip()
    prefix = _PREFIX.match(text)
    if prefix:
        return prefix.group(1).lower()
    if "?" in text or _SPOKEN.match(text):
        return "truth"
    return "dare"


def split_truth_or_dare(apps, schema_editor):
    for name in ["Question", "CustomQuestion"]:
        model = apps.get_model("game", name)
        for question in model.objects.filter(mode="truth").only("pk", "text"):
            model.objects.filter(pk=question.pk).update(kind=classify(question.text))


KIND_MATCHES_MODE = models.Q(
    models.Q(("kind__in", ["truth", "dare"]), ("mode", "truth")),
    models.Q(models.Q(("mode", "truth"), _negated=True), ("kind", "")),
    _connector="OR",
)


class Migration(migrations.Migration):

    dependencies = [
        ("couples", "0004_remove_legacy_link"),
        ("game", "0007_remove_secret_word_couples"),
    ]

    operations = [
        migrations.AddField(
            model_name="customquestion",
            name="kind",
            field=models.CharField(blank=True, choices=[("truth", "Truth"), ("dare", "Dare")], default="", max_length=5),
        ),
        migrations.AddField(
            model_name="question",
            name="kind",
            field=models.CharField(blank=True, choices=[("truth", "Truth"), ("dare", "Dare")], default="", max_length=5),
        ),
        # Reversing drops the fields, so there is nothing to undo here.
        migrations.RunPython(split_truth_or_dare, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="customquestion",
            constraint=models.CheckConstraint(condition=KIND_MATCHES_MODE, name="game_customquestion_kind_matches_mode"),
        ),
        migrations.AddConstraint(
            model_name="question",
            constraint=models.CheckConstraint(condition=KIND_MATCHES_MODE, name="game_question_kind_matches_mode"),
        ),
    ]
