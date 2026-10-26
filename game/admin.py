from django.contrib import admin

# Register your models here.
from .models import CoupleSession, Question, CustomQuestion

@admin.register(CoupleSession)
class CoupleSessionAdmin(admin.ModelAdmin):
    # The secret word works like a password, so it is never shown here.
    # Sessions are created by couples through the app, not by admins.
    exclude = ["secret_word"]
    list_display = ["__str__", "created_at", "last_active"]
    readonly_fields = ["session_key", "created_at", "last_active"]

    def has_add_permission(self, request):
        return False


admin.site.register(Question)
admin.site.register(CustomQuestion)
