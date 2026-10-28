from django.conf import settings
from django.db import models
from django.db.models import Q

from couples.models import Couple


class ChatMessage(models.Model):
    """One message in a couple's private chat. Only the two active members
    can read it (chat.services); while the couple is closed nobody can, and
    it isn't in the admin."""

    couple = models.ForeignKey(Couple, on_delete=models.CASCADE, related_name="chat_messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    # A Fernet token (chat.crypto), never the plain text.
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # The sender's id for the request, so a retried send is saved once.
    request_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["author", "request_id"],
                condition=Q(request_id__isnull=False),
                name="chat_message_sent_once",
            ),
        ]
        indexes = [models.Index(fields=["couple", "id"], name="chat_message_couple_order")]


class ChatReaction(models.Model):
    """One person's reaction (a single emoji) to a chat message. Not
    encrypted: it's one emoji. Deleted with its message."""

    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    emoji = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["message", "user"], name="chat_one_reaction_per_person"),
        ]
