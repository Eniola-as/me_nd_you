# Create your models here.
import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


# Each couple shares a secret word (like a room code)
class CoupleSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partner1_name = models.CharField(max_length=100)  # Changed from person1_name
    partner2_name = models.CharField(max_length=100)  # Changed from person2_name
    secret_word = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)
    session_key = models.CharField(max_length=255, unique=True, blank=True)

    class Meta:
        unique_together = ["partner1_name", "partner2_name", "secret_word"]

    def save(self, *args, **kwargs):
        # Sort names alphabetically for consistency
        names = sorted([self.partner1_name.lower(), self.partner2_name.lower()])
        self.partner1_name = names[0].title()
        self.partner2_name = names[1].title()

        # Create unique session key
        if not self.session_key:
            self.session_key = f"{self.id}_{names[0]}_{names[1]}"

        super().save(*args, **kwargs)

    def clean(self):
        if self.partner1_name.lower() == self.partner2_name.lower():
            raise ValidationError("Names must be different")
        if len(self.secret_word) < 4:
            raise ValidationError("Secret word must be at least 4 characters")

    @classmethod
    def find_session(cls, name1, name2, secret):
        # Sort names to match stored order
        names = sorted([name1, name2])
        return cls.objects.filter(
            partner1_name=names[0], partner2_name=names[1], secret_word=secret
        ).first()

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
    couple = models.ForeignKey(CoupleSession, on_delete=models.CASCADE)
    text = models.TextField()
    mode = models.CharField(max_length=20, choices=Question.MODES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Custom by {self.couple.secret_word}: {self.text[:50]}"


class PlayedQuestion(models.Model):
    couple = models.ForeignKey(CoupleSession, on_delete=models.CASCADE)
    text = models.TextField()
    mode = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)
