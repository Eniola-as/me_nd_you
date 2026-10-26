from django.db import migrations, models


SECRET_MAX_LENGTH = 100


def suffixed(secret, n):
    """secret-n, trimming the secret so the result fits the column. SQLite
    doesn't enforce max_length but PostgreSQL does, so this must hold on both."""
    suffix = f"-{n}"
    return secret[: SECRET_MAX_LENGTH - len(suffix)] + suffix


def rename_duplicate_secrets(apps, schema_editor):
    """Keep the oldest session's secret; suffix later duplicates so the
    unique constraint can be applied. Those couples were already unable to
    log in, because every lookup by secret raised MultipleObjectsReturned."""
    CoupleSession = apps.get_model("game", "CoupleSession")
    taken = set(CoupleSession.objects.values_list("secret_word", flat=True))
    seen = set()
    for session in CoupleSession.objects.order_by("created_at"):
        if session.secret_word not in seen:
            seen.add(session.secret_word)
            continue
        n = 2
        while (candidate := suffixed(session.secret_word, n)) in taken:
            n += 1
        session.secret_word = candidate
        taken.add(session.secret_word)
        session.save(update_fields=["secret_word"])


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0003_couplesession_last_active_couplesession_session_key_and_more"),
    ]

    operations = [
        migrations.RunPython(rename_duplicate_secrets, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="couplesession",
            name="secret_word",
            field=models.CharField(max_length=100, unique=True),
        ),
    ]
