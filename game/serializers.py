from rest_framework import serializers

from .models import Question


class QuestionInputSerializer(serializers.Serializer):
    """A couple's own question. Any other field (such as a couple id) is
    ignored: who it belongs to is never taken from the request body."""

    text = serializers.CharField(max_length=500)  # Trimmed; blank is rejected.
    mode = serializers.ChoiceField(choices=Question.MODES)
