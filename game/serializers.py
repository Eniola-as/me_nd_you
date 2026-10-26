import re
import unicodedata

from rest_framework import serializers
from .models import Question

# Letters in any script, with single spaces, apostrophes, hyphens or periods
# between them (José, Anne-Marie, O'Neil, St. John).
NAME_RE = re.compile(r"[^\W\d_]+(?:[ '’.\-]+[^\W\d_]+)*")


class LoginSerializer(serializers.Serializer):
    partner1_name = serializers.CharField(min_length=2, max_length=100)
    partner2_name = serializers.CharField(min_length=2, max_length=100)
    secret_word = serializers.CharField(min_length=4, max_length=100, trim_whitespace=False)

    def _validate_name(self, value):
        value = unicodedata.normalize("NFC", value)
        if not NAME_RE.fullmatch(value):
            raise serializers.ValidationError(
                "Use letters, spaces, apostrophes or hyphens only."
            )
        return value

    def validate_partner1_name(self, value):
        return self._validate_name(value)

    def validate_partner2_name(self, value):
        return self._validate_name(value)

    def validate(self, data):
        if data["partner1_name"].casefold() == data["partner2_name"].casefold():
            raise serializers.ValidationError(
                {"partner2_name": "Your partner's name must be different from yours."}
            )
        return data


class QuestionInputSerializer(serializers.Serializer):
    """A couple's own question. Any other field (such as a couple id) is
    ignored: who it belongs to is never taken from the request body."""

    text = serializers.CharField(max_length=500)  # Trimmed; blank is rejected.
    mode = serializers.ChoiceField(choices=Question.MODES)


class CustomQuestionSerializer(QuestionInputSerializer):
    """Legacy endpoint: the couple is identified by its secret word."""

    secret = serializers.CharField(max_length=100, trim_whitespace=False)

