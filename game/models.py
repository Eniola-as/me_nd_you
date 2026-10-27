from django.db import models


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


# Questions a couple adds to their own space
class CustomQuestion(models.Model):
    space = models.ForeignKey(
        "couples.Couple", on_delete=models.CASCADE, related_name="custom_questions",
    )
    text = models.TextField()
    mode = models.CharField(max_length=20, choices=Question.MODES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Custom in {self.space}: {self.text[:50]}"
