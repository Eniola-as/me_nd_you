from django.conf import settings
from django.db import models

from .truth_or_dare import KINDS, MODE as TRUTH_OR_DARE

# Truth or Dare questions are truths or dares; no other mode has a kind.
KIND_MATCHES_MODE = (
    models.Q(mode=TRUTH_OR_DARE, kind__in=[value for value, _ in KINDS])
    | (~models.Q(mode=TRUTH_OR_DARE) & models.Q(kind=""))
)


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
    kind = models.CharField(max_length=5, choices=KINDS, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=KIND_MATCHES_MODE, name="game_question_kind_matches_mode"),
        ]

    def __str__(self):
        return f"[{self.mode}{'/' + self.kind if self.kind else ''}] {self.text[:50]}"


# Questions a couple adds to their own space
class CustomQuestion(models.Model):
    space = models.ForeignKey(
        "couples.Couple", on_delete=models.CASCADE, related_name="custom_questions",
    )
    text = models.TextField()
    mode = models.CharField(max_length=20, choices=Question.MODES)
    kind = models.CharField(max_length=5, choices=KINDS, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # Who added it, recorded from the pre-launch release on; older questions
    # have none. Used for "Download my data" and account deletion.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=KIND_MATCHES_MODE, name="game_customquestion_kind_matches_mode"),
        ]

    def __str__(self):
        # Never the text: this label appears across the admin (lists, delete
        # confirmations, its history log), and custom questions can be intimate.
        return f"Custom question #{self.pk} ({self.mode})"
