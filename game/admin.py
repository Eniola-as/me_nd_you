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
    """Couples' own questions can be intimate, so admins never see their
    text: only ids, the couple, mode and kind. There is no search either
    (it would let an admin probe the text), and no adding or editing."""

    list_display = ["__str__", "space", "mode", "kind", "created_at"]
    list_filter = ["mode", "kind"]
    exclude = ["text"]
    readonly_fields = ["space", "mode", "kind", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
