import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

# A couple has exactly these member slots. The database refuses a second
# active member in the same slot, so "at most two members" holds even when
# two people accept invitations at the same moment.
MEMBER_SLOTS = (1, 2)


class Couple(models.Model):
    """A private space shared by (at most) two accounts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Couple {str(self.id)[:8]}"


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(left_at__isnull=True)


class Membership(models.Model):
    couple = models.ForeignKey(Couple, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    slot = models.PositiveSmallIntegerField()
    joined_at = models.DateTimeField(auto_now_add=True)
    # Set when a member leaves. Kept rather than deleted, so history stays.
    left_at = models.DateTimeField(null=True, blank=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(slot__in=MEMBER_SLOTS), name="couples_membership_valid_slot"
            ),
            models.UniqueConstraint(
                fields=["couple", "slot"],
                condition=Q(left_at__isnull=True),
                name="couples_membership_one_member_per_slot",
            ),
            # The "one active couple per user" rule for now. Allowing more
            # later means dropping this constraint in a migration.
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(left_at__isnull=True),
                name="couples_membership_one_active_couple_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} in {self.couple} (slot {self.slot})"


class Invitation(models.Model):
    """A single-use, expiring, revocable invitation to join a couple. Only a
    SHA-256 hash of the token is stored; the token itself is shown once."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    couple = models.ForeignKey(Couple, on_delete=models.CASCADE, related_name="invitations")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    def is_usable(self, now):
        return self.used_at is None and self.revoked_at is None and self.expires_at > now

    def __str__(self):
        return f"Invitation to {self.couple}"
