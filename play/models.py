import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class GameRoom(models.Model):
    """The authoritative state of one game for one couple space. Every change
    goes through play.services, which bumps `version` by exactly one."""

    ACTIVE, CLOSED = "active", "closed"
    STATUSES = [(ACTIVE, "Active"), (CLOSED, "Closed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    couple = models.ForeignKey("couples.Couple", on_delete=models.CASCADE, related_name="game_rooms")
    game = models.CharField(max_length=30)  # A key in play.games.GAMES.
    variant = models.CharField(max_length=20)  # The question mode.
    state = models.JSONField()
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["couple", "game", "variant"],
                condition=Q(status="active"),
                name="play_one_active_room_per_game",
            ),
        ]

    def __str__(self):
        return f"{self.game}/{self.variant} for {self.couple} (v{self.version})"


class RoomEvent(models.Model):
    """Append-only history: one row per committed change."""

    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name="events")
    version = models.PositiveIntegerField()  # The room version this change produced.
    kind = models.CharField(max_length=30)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    payload = models.JSONField(default=dict, blank=True)
    # The client's id for the request, so a retried request is applied once.
    request_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["room", "version"], name="play_one_event_per_version"),
            models.UniqueConstraint(
                fields=["room", "request_id"],
                condition=Q(request_id__isnull=False),
                name="play_request_applied_once",
            ),
        ]
        ordering = ["room", "version"]
