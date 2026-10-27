from django.contrib import admin

from .models import CustomQuestion, Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    # Truth or Dare questions need a kind; other modes must leave it blank.
    list_display = ["__str__", "mode", "kind"]
    list_filter = ["mode", "kind"]
    search_fields = ["text"]


@admin.register(CustomQuestion)
class CustomQuestionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "mode", "kind", "created_at"]
    list_filter = ["mode", "kind"]
