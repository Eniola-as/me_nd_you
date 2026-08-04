from rest_framework import serializers
from .models import Question, CustomQuestion, CoupleSession


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ["id", "text", "mode"]


class CustomQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomQuestion
        fields = "__all__"

        couple = serializers.PrimaryKeyRelatedField(
            queryset=CoupleSession.objects.all()
        )


class CoupleSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoupleSession
        fields = ["id", "partner1_name", "partner2_name", "secret_word", "session_key"]
        read_only_fields = ["id", "session_key"]

    def validate(self, data):
        # Sort names for consistent validation
        names = sorted([data["partner1_name"].lower(), data["partner2_name"].lower()])
        data["partner1_name"] = names[0].title()
        data["partner2_name"] = names[1].title()
        return data
