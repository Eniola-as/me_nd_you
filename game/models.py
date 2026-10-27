# Create your models here.
import time
import uuid
from datetime import timedelta
from django.core.cache import cache
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.utils import timezone


# Each couple shares a secret word (like a room code)
class CoupleSession(models.Model):
    # Sessions with no activity for this long are treated as expired and
    # removed by the purge_inactive_sessions management command.
    INACTIVITY_LIMIT = timedelta(days=30)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partner1_name = models.CharField(max_length=100)  # Changed from person1_name
    partner2_name = models.CharField(max_length=100)  # Changed from person2_name
    secret_word = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)
    session_key = models.CharField(max_length=255, unique=True, blank=True)

    class Meta:
        unique_together = ["partner1_name", "partner2_name", "secret_word"]

    def save(self, *args, **kwargs):
        # Sort names alphabetically (ignoring case) for consistency, but keep
        # them as typed: title() would turn "McDonald" into "Mcdonald".
        names = sorted(
            [self.partner1_name.strip(), self.partner2_name.strip()], key=str.casefold
        )
        self.partner1_name, self.partner2_name = names

        # Create unique session key
        if not self.session_key:
            self.session_key = f"{self.id}_{names[0].casefold()}_{names[1].casefold()}"

        super().save(*args, **kwargs)

    def clean(self):
        if self.partner1_name.lower() == self.partner2_name.lower():
            raise ValidationError("Names must be different")
        if len(self.secret_word) < 4:
            raise ValidationError("Secret word must be at least 4 characters")

    def is_expired(self):
        return timezone.now() - self.last_active > self.INACTIVITY_LIMIT

    def touch(self):
        """Record activity without re-running save() and its name handling."""
        self.last_active = timezone.now()
        CoupleSession.objects.filter(pk=self.pk).update(last_active=self.last_active)

    @classmethod
    def find_active(cls, secret):
        """The session for a secret, or None if it is unknown or expired.
        Callers treat both the same, so expiry never reveals that a secret
        exists. Logging in again renews an expired session."""
        session = cls.objects.filter(secret_word=secret).first() if secret else None
        if session is None or session.is_expired() or session.is_retired():
            return None
        return session

    def is_retired(self):
        """Whether the couple moved to accounts and the secret word no
        longer works (couples.legacy)."""
        from couples.legacy import secret_word_retired

        return secret_word_retired(self)

    @classmethod
    def inactive(cls):
        # A couple ever linked to a couple space is never purged: its
        # questions belong to that space too.
        return cls.objects.filter(
            last_active__lt=timezone.now() - cls.INACTIVITY_LIMIT, space_links__isnull=True
        )

    def __str__(self):
        return f"{self.partner1_name} & {self.partner2_name}"


# Admin-added questions
class Question(models.Model):
    MODES = [
        ("questions", "Questions"),
        ("truth", "Truth or Dare"),
        ("challenge", "Challenge"),
        ("spicy", "Spicy Only"),
        ("mixed", "Mixed Mode"),
        ("would", "Would You Rather"),
    ]
    text = models.TextField()
    mode = models.CharField(max_length=20, choices=MODES)

    def __str__(self):
        return f"[{self.mode}] {self.text[:50]}"


# Couple-created questions
class CustomQuestion(models.Model):
    # Exactly one owner: a legacy secret-word couple, or a couple space.
    couple = models.ForeignKey(CoupleSession, on_delete=models.CASCADE, null=True, blank=True)
    space = models.ForeignKey(
        "couples.Couple", on_delete=models.CASCADE, null=True, blank=True,
        related_name="custom_questions",
    )
    text = models.TextField()
    mode = models.CharField(max_length=20, choices=Question.MODES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(couple__isnull=False, space__isnull=True)
                    | models.Q(couple__isnull=True, space__isnull=False)
                ),
                name="game_customquestion_exactly_one_owner",
            ),
        ]

    def __str__(self):
        return f"Custom by {self.couple}: {self.text[:50]}"


def custom_questions_for_space(couple):
    """A couple space's own questions plus those of a secret-word couple
    linked to it."""
    return CustomQuestion.objects.filter(
        models.Q(space=couple)
        | models.Q(couple__space_links__couple=couple, couple__space_links__unlinked_at__isnull=True)
    ).distinct()


class PlayedQuestion(models.Model):
    couple = models.ForeignKey(CoupleSession, on_delete=models.CASCADE)
    text = models.TextField()
    mode = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)


# Cached question lists include this version in their key; any change to a
# question bumps it, so stale lists are never served.
QUESTIONS_CACHE_VERSION_KEY = "questions_version"


def questions_cache_version():
    return cache.get_or_set(QUESTIONS_CACHE_VERSION_KEY, time.time_ns, timeout=None)


@receiver([post_save, post_delete], sender=Question)
@receiver([post_save, post_delete], sender=CustomQuestion)
def bump_questions_cache_version(**kwargs):
    try:
        cache.incr(QUESTIONS_CACHE_VERSION_KEY)
    except ValueError:  # Key evicted: any fresh value avoids old entries.
        cache.set(QUESTIONS_CACHE_VERSION_KEY, time.time_ns(), timeout=None)
