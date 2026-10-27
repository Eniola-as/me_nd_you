from django.contrib import admin

from . import services
from .models import Couple, Invitation, Membership


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    readonly_fields = ["user", "slot", "joined_at", "left_at"]
    can_delete = False


@admin.register(Couple)
class CoupleAdmin(admin.ModelAdmin):
    list_display = ["__str__", "created_at", "closed_at"]
    readonly_fields = ["id", "created_at", "closed_at", "closed_by"]
    inlines = [MembershipInline]
    actions = ["reopen_couples"]

    @admin.action(description="Reopen selected closed couples")
    def reopen_couples(self, request, queryset):
        for couple in queryset:
            restored = services.reopen_couple(couple)
            names = ", ".join(u.email for u in restored) or "nobody (both are in other couples)"
            self.message_user(request, f"{couple}: reopened; restored {names}.")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    # The token hash is never shown; invitations are created in the app.
    list_display = ["couple", "created_by", "created_at", "expires_at", "used_at", "revoked_at"]
    exclude = ["token_hash"]
    readonly_fields = ["couple", "created_by", "created_at", "expires_at", "used_at", "used_by"]

    def has_add_permission(self, request):
        return False
