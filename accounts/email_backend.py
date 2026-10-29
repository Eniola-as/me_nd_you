from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend


class DisabledEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if email_messages:
            raise ImproperlyConfigured(
                "Email delivery is disabled until an email provider is configured."
            )
        return 0
