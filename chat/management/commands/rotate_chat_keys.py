"""Re-encrypt every chat message with the first key in CHAT_ENCRYPTION_KEYS.

Rotating a key: put the new key first ("new,old"), deploy, run this
command, then remove the old key. Messages no key can decrypt are counted
and left as they are."""

from cryptography.fernet import InvalidToken
from django.core.management.base import BaseCommand
from django.db import transaction

from chat import crypto
from chat.models import ChatMessage


class Command(BaseCommand):
    help = "Re-encrypt every chat message with the first key in CHAT_ENCRYPTION_KEYS."

    def handle(self, *args, **options):
        done = unreadable = 0
        for message_id in ChatMessage.objects.values_list("pk", flat=True).iterator():
            with transaction.atomic():
                message = ChatMessage.objects.select_for_update().filter(pk=message_id).first()
                if message is None:
                    continue  # Deleted meanwhile.
                try:
                    message.body = crypto.rotate(message.body)
                except (InvalidToken, ValueError):
                    unreadable += 1
                    continue
                message.save(update_fields=["body"])
                done += 1
        summary = f"Re-encrypted {done} messages"
        if unreadable:
            summary += f"; {unreadable} could not be decrypted and were left as they are"
        self.stdout.write(summary + ".")
