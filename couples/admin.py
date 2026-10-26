from django.contrib import admin

from .models import Couple, Invitation, Membership


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    readonly_fields = ["user", "slot", "joined_at", "left_at"]
    can_delete = False


@admin.register(Couple)
class CoupleAdmin(admin.ModelAdmin):
    list_display = ["__str__", "created_at"]
    readonly_fields = ["id", "created_at"]
    inlines = [MembershipInline]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    # The token hash is never shown; invitations are created in the app.
    list_display = ["couple", "created_by", "created_at", "expires_at", "used_at", "revoked_at"]
    exclude = ["token_hash"]
    readonly_fields = ["couple", "created_by", "created_at", "expires_at", "used_at", "used_by"]

    def has_add_permission(self, request):
        return False
