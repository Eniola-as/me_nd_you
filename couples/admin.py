from django.contrib import admin

from . import legacy, services
from .models import Couple, Invitation, LegacyLink, Membership


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


@admin.register(LegacyLink)
class LegacyLinkAdmin(admin.ModelAdmin):
    # Links change only through the app and these actions, never by hand.
    list_display = ["__str__", "claimed_at", "retire_at", "retired_at", "needs_resolution_at", "unlinked_at"]
    list_filter = [("needs_resolution_at", admin.EmptyFieldListFilter), ("retired_at", admin.EmptyFieldListFilter)]
    readonly_fields = [f.name for f in LegacyLink._meta.fields] + ["ready"]
    actions = ["clear_retirements", "unlink_links"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Clear the retirement (the secret word works again)")
    def clear_retirements(self, request, queryset):
        for link in queryset:
            legacy.clear_retirement(link)
        self.message_user(request, f"Cleared {queryset.count()} link(s).")

    @admin.action(description="Unlink (undo the claim; nothing is deleted)")
    def unlink_links(self, request, queryset):
        for link in queryset.filter(unlinked_at__isnull=True):
            legacy.unlink(link)
        self.message_user(request, "Unlinked.")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    # The token hash is never shown; invitations are created in the app.
    list_display = ["couple", "created_by", "created_at", "expires_at", "used_at", "revoked_at"]
    exclude = ["token_hash"]
    readonly_fields = ["couple", "created_by", "created_at", "expires_at", "used_at", "used_by"]

    def has_add_permission(self, request):
        return False
