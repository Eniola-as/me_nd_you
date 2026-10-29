from django.conf import settings
from django.db import models
from django.db.models import Q


class Notification(models.Model):
    """Something happened that a member may have missed. Stored, so it's
    there after being offline. Holds only what kind of thing happened (and
    which game mode): never message text, answers or other content.

    At most one unread notification per member, couple, kind and mode: more
    of the same while it's unread just bump it, so ten messages are one
    "sent you a message"."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    couple = models.ForeignKey("couples.Couple", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=30)
    mode = models.CharField(max_length=20, blank=True, default="")  # A game mode, for game kinds.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "couple", "kind", "mode"],
                condition=Q(read_at__isnull=True),
                name="notifications_one_unread_per_kind",
            ),
        ]
        indexes = [models.Index(fields=["user", "read_at"], name="notifications_user_unread")]


class PushSubscription(models.Model):
    """One browser or installed app that may receive push notifications for
    a member (the Web Push subscription it gave us). A device belongs to
    whoever last turned notifications on with it."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
